from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any

import duckdb

from app.core.errors import StorageError
from app.domain.models import (
    CollectionRun,
    PriceObservation,
    ProductCatalogEntry,
    split_codes,
)
from log.logger import StructuredLogger


@dataclass(frozen=True, slots=True)
class RepositoryWriteResult:
    inserted: int
    updated: int
    total: int
    path: Path


@dataclass(frozen=True, slots=True)
class CatalogFilters:
    category_code: str | None = None
    item_code: str | None = None
    item_name: str | None = None


@dataclass(frozen=True, slots=True)
class PriceFilters:
    price_type: str | None = None
    item_code: str | None = None
    item_name: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class _AtomicCsvRepository:
    def __init__(self, path: Path, logger: StructuredLogger) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger
        self._lock = RLock()

    def _read(self) -> list[dict[str, str]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                return list(csv.DictReader(handle))
        except (OSError, csv.Error) as error:
            raise StorageError(f"failed to read {self.path}: {error}") from error

    @staticmethod
    def _serialize(path: Path, rows: list[dict[str, Any]]) -> None:
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            if not fieldnames:
                return
            writer = csv.DictWriter(
                handle, fieldnames=fieldnames, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())

    def _atomic_write(self, rows: list[dict[str, Any]], run_id: str) -> None:
        temporary = self.path.with_suffix(f"{self.path.suffix}.{run_id}.tmp")
        started = perf_counter()
        try:
            self._serialize(temporary, rows)
            os.replace(temporary, self.path)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "csv.write.succeeded",
                "CSV write completed",
                path=self.path,
                run_id=run_id,
                record_count=len(rows),
                duration_ms=round((perf_counter() - started) * 1000),
            )
        except OSError as error:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
            self._logger.exception(  # noqa: PLE1205 - custom structured logger
                "csv.write.failed",
                "CSV write failed",
                error,  # noqa: TRY401 - StructuredLogger records error metadata
                path=self.path,
                run_id=run_id,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise StorageError(f"failed to write {self.path}: {error}") from error


class CatalogRepository(_AtomicCsvRepository):
    def __init__(self, data_dir: Path, logger: StructuredLogger) -> None:
        super().__init__(data_dir / "normalized" / "kamis_catalog.csv", logger)
        self._raw_root = data_dir / "raw" / "kamis" / "catalog"

    @staticmethod
    def _key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row["category_code"]),
            str(row["item_code"]),
            str(row["kind_code"]),
        )

    def save_snapshot(
        self, rows: list[ProductCatalogEntry], observed_date: date, run_id: str
    ) -> Path:
        dictionaries = [row.to_dict() for row in rows]
        snapshot = self._raw_root / f"{observed_date.isoformat()}.csv"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot_writer = _AtomicCsvRepository(snapshot, self._logger)
        with self._lock:
            snapshot_writer._atomic_write(dictionaries, run_id)
            self._atomic_write(dictionaries, run_id)
        return snapshot

    def search(self, filters: CatalogFilters | None = None) -> list[dict[str, str]]:
        filters = filters or CatalogFilters()
        rows = self._read()
        return [
            row
            for row in rows
            if (
                filters.category_code is None
                or row.get("category_code") == filters.category_code
            )
            and (filters.item_code is None or row.get("item_code") == filters.item_code)
            and (
                filters.item_name is None
                or filters.item_name.casefold() in row.get("item_name", "").casefold()
            )
        ]

    def entries(self) -> list[ProductCatalogEntry]:
        return [
            ProductCatalogEntry(
                category_code=row["category_code"],
                category_name=row["category_name"],
                item_code=row["item_code"],
                item_name=row["item_name"],
                kind_code=row["kind_code"],
                variety=row["variety"],
                wholesale_unit=row.get("wholesale_unit") or None,
                wholesale_unit_size=row.get("wholesale_unit_size") or None,
                retail_unit=row.get("retail_unit") or None,
                retail_unit_size=row.get("retail_unit_size") or None,
                eco_unit=row.get("eco_unit") or None,
                eco_unit_size=row.get("eco_unit_size") or None,
                wholesale_rank_codes=split_codes(row.get("wholesale_rank_codes")),
                retail_rank_codes=split_codes(row.get("retail_rank_codes")),
                eco_rank_codes=split_codes(row.get("eco_rank_codes")),
            )
            for row in self._read()
        ]


class PriceRepository(_AtomicCsvRepository):
    _key_fields = (
        "price_type",
        "observed_date",
        "category_code",
        "item_code",
        "kind_code",
        "rank_code",
        "region",
        "market_name",
        "requested_convert_kg",
    )

    def __init__(self, data_dir: Path, logger: StructuredLogger) -> None:
        super().__init__(data_dir / "normalized" / "kamis_prices.csv", logger)

    @classmethod
    def _key(cls, row: dict[str, Any]) -> tuple[str, ...]:
        # CSV writes nullable fields as empty strings; keep the key stable on reload.
        return tuple(
            "" if row.get(field) is None else str(row[field])
            for field in cls._key_fields
        )

    def upsert(
        self, observations: list[PriceObservation], run_id: str
    ) -> RepositoryWriteResult:
        incoming = [observation.to_dict() for observation in observations]
        with self._lock:
            existing = self._read()
            by_key = {self._key(row): row for row in existing}
            inserted = 0
            updated = 0
            for row in incoming:
                key = self._key(row)
                if key in by_key:
                    updated += 1
                else:
                    inserted += 1
                by_key[key] = row
            ordered = sorted(
                by_key.values(),
                key=lambda row: (
                    row.get("observed_date", ""),
                    row.get("item_code", ""),
                    row.get("kind_code", ""),
                    row.get("price_type", ""),
                ),
            )
            self._atomic_write(ordered, run_id)
        return RepositoryWriteResult(inserted, updated, len(ordered), self.path)

    def search(self, filters: PriceFilters | None = None) -> list[dict[str, Any]]:
        filters = filters or PriceFilters()
        result: list[dict[str, Any]] = []
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return result
            try:
                # Filter in the native CSV scanner before materializing Python rows.
                # Codes remain strings (leading zeroes matter); imports need not be sorted.
                conditions = ["observed_date IS NOT NULL", "observed_date <> ''"]
                parameters: list[Any] = [str(self.path)]
                for column, value, operator in (
                    ("item_code", filters.item_code, "="),
                    ("price_type", filters.price_type, "="),
                    ("observed_date", filters.start_date, ">="),
                    ("observed_date", filters.end_date, "<="),
                ):
                    if value is not None:
                        conditions.append(f"{column} {operator} ?")
                        parameters.append(str(value))
                with duckdb.connect(config={"threads": 2}) as connection:
                    cursor = connection.execute(
                        "SELECT * FROM read_csv(?, header=true, all_varchar=true) WHERE "
                        + " AND ".join(conditions),
                        parameters,
                    )
                    columns = [column[0] for column in cursor.description]
                    while batch := cursor.fetchmany(4096):
                        for values in batch:
                            row = dict(
                                zip(
                                    columns,
                                    (
                                        value if value is not None else ""
                                        for value in values
                                    ),
                                )
                            )
                            if (
                                filters.item_name
                                and filters.item_name.casefold()
                                not in row.get("item_name", "").casefold()
                            ):
                                continue
                            date.fromisoformat(row["observed_date"])
                            row["price_krw"] = (
                                float(row["price_krw"])
                                if row.get("price_krw")
                                else None
                            )
                            result.append(row)
            except (OSError, csv.Error, ValueError, duckdb.Error) as error:
                raise StorageError(f"failed to search {self.path}: {error}") from error
        return result

    def item_date_stats(self) -> dict[str, tuple[date, date, int]]:
        """Return earliest/latest/count per item without materializing price rows."""
        stats: dict[str, tuple[date, date, int]] = {}
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return stats
            try:
                with self.path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        item_code = str(row.get("item_code", ""))
                        observed_text = row.get("observed_date", "")
                        if not item_code or not observed_text:
                            continue
                        observed = date.fromisoformat(observed_text)
                        current = stats.get(item_code)
                        if current is None:
                            stats[item_code] = (observed, observed, 1)
                        else:
                            earliest, latest, count = current
                            stats[item_code] = (
                                min(earliest, observed),
                                max(latest, observed),
                                count + 1,
                            )
            except (OSError, csv.Error, ValueError) as error:
                raise StorageError(
                    f"failed to inspect item date stats in {self.path}: {error}"
                ) from error
        return stats

    def count(self) -> int:
        return len(self._read())

    def has_collected_date(
        self,
        observed_date: date,
        required_scopes: set[tuple[str, str, str, str]]
        | frozenset[tuple[str, str, str, str]]
        | None = None,
    ) -> bool:
        """Return whether a date has sufficient stored KAMIS query coverage.

        A scope is (item_code, kind_code, price_type, rank_code). Requiring
        complete scopes prevents a partially written date from suppressing a
        recovery collection. With no scopes supplied, any row on the date is
        considered collected for backward compatibility.
        """
        expected = observed_date.isoformat()
        required = set(required_scopes or ())
        found_date = False
        found_scopes: set[tuple[str, str, str, str]] = set()

        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return False
            try:
                with self.path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        row_date = row.get("observed_date", "")
                        if row_date < expected:
                            continue
                        if row_date > expected:
                            break
                        found_date = True
                        if not required:
                            return True
                        found_scopes.add(
                            (
                                str(row.get("item_code", "")),
                                str(row.get("kind_code", "")),
                                str(row.get("price_type", "")),
                                str(row.get("rank_code", "")),
                            )
                        )
                        if required.issubset(found_scopes):
                            return True
            except (OSError, csv.Error) as error:
                raise StorageError(
                    f"failed to inspect collected KAMIS date in {self.path}: {error}"
                ) from error
        return found_date if not required else required.issubset(found_scopes)

    def covered_dates(
        self,
        start_date: date,
        end_date: date,
        required_scopes: set[tuple[str, str, str, str]]
        | frozenset[tuple[str, str, str, str]],
    ) -> set[date]:
        """Return dates whose stored rows cover every required KAMIS scope.

        A scope is (item_code, kind_code, price_type, rank_code). The CSV is
        scanned once for the bounded window so startup recovery remains cheap
        even with a large long-history file.
        """
        required = set(required_scopes)
        if not required:
            return self.observed_dates(start_date, end_date)

        start_text = start_date.isoformat()
        end_text = end_date.isoformat()
        scopes_by_date: dict[date, set[tuple[str, str, str, str]]] = {}
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return set()
            try:
                with self.path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        observed_text = row.get("observed_date", "")
                        if not observed_text or observed_text < start_text:
                            continue
                        if observed_text > end_text:
                            break
                        scope = (
                            str(row.get("item_code", "")),
                            str(row.get("kind_code", "")),
                            str(row.get("price_type", "")),
                            str(row.get("rank_code", "")),
                        )
                        if scope not in required:
                            continue
                        observed = date.fromisoformat(observed_text)
                        scopes_by_date.setdefault(observed, set()).add(scope)
            except (OSError, csv.Error, ValueError) as error:
                raise StorageError(
                    f"failed to inspect KAMIS scope coverage in {self.path}: {error}"
                ) from error

        return {
            observed
            for observed, scopes in scopes_by_date.items()
            if required.issubset(scopes)
        }

    def observed_dates(self, start_date: date, end_date: date) -> set[date]:
        """Return stored observation dates in a bounded window without loading rows."""
        result: set[date] = set()
        start_text = start_date.isoformat()
        end_text = end_date.isoformat()
        with self._lock:
            if not self.path.exists() or self.path.stat().st_size == 0:
                return result
            try:
                with self.path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        observed_text = row.get("observed_date", "")
                        if not observed_text or observed_text < start_text:
                            continue
                        if observed_text > end_text:
                            break
                        result.add(date.fromisoformat(observed_text))
            except (OSError, csv.Error, ValueError) as error:
                raise StorageError(
                    f"failed to inspect observed KAMIS dates in {self.path}: {error}"
                ) from error
        return result

    def observed_date_range(self) -> tuple[date, date] | None:
        """Scan the date column without loading the full price history into memory."""
        with self._lock:
            if not self.path.exists():
                return None
            earliest: date | None = None
            latest: date | None = None
            try:
                with self.path.open(encoding="utf-8-sig", newline="") as handle:
                    for row in csv.DictReader(handle):
                        observed = date.fromisoformat(row["observed_date"])
                        earliest = min(earliest, observed) if earliest else observed
                        latest = max(latest, observed) if latest else observed
            except (OSError, csv.Error, ValueError, KeyError) as error:
                raise StorageError(
                    f"failed to read date range from {self.path}: {error}"
                ) from error
            return (earliest, latest) if earliest and latest else None


class RunRepository(_AtomicCsvRepository):
    def __init__(self, data_dir: Path, logger: StructuredLogger) -> None:
        super().__init__(data_dir / "runs" / "collection_runs.csv", logger)

    def save(self, run: CollectionRun) -> None:
        row = run.to_dict()
        row["errors"] = json.dumps(row["errors"], ensure_ascii=False)
        with self._lock:
            runs = {existing["run_id"]: existing for existing in self._read()}
            runs[run.run_id] = row
            self._atomic_write(list(runs.values()), run.run_id)

    def get(self, run_id: str) -> dict[str, Any] | None:
        for row in self._read():
            if row.get("run_id") == run_id:
                result: dict[str, Any] = dict(row)
                result["errors"] = json.loads(row.get("errors", "[]"))
                return result
        return None

    def latest(self) -> dict[str, Any] | None:
        rows = self._read()
        return dict(rows[-1]) if rows else None

    def successful_covered_dates(
        self,
        source: str,
        start_date: date,
        end_date: date,
    ) -> set[date]:
        """Return dates covered by successful collection runs for a source."""
        covered: set[date] = set()
        for row in self._read():
            if row.get("source") != source or row.get("status") != "success":
                continue
            try:
                run_start = date.fromisoformat(str(row.get("requested_start", "")))
                run_end = date.fromisoformat(str(row.get("requested_end", "")))
            except ValueError:
                continue
            overlap_start = max(start_date, run_start)
            overlap_end = min(end_date, run_end)
            if overlap_start > overlap_end:
                continue
            covered.update(
                overlap_start + timedelta(days=offset)
                for offset in range((overlap_end - overlap_start).days + 1)
            )
        return covered

    def has_successful_run(self, source: str, requested_date: date) -> bool:
        expected_date = requested_date.isoformat()
        return any(
            row.get("source") == source
            and row.get("requested_start") == expected_date
            and row.get("requested_end") == expected_date
            and row.get("status") == "success"
            for row in self._read()
        )
