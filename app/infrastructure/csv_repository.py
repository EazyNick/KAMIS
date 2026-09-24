from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import RLock
from time import perf_counter
from typing import Any

from app.core.errors import StorageError
from app.domain.models import (
    CollectionRun,
    PriceObservation,
    ProductCatalogEntry,
    split_codes,
)
from log.context_logger import ContextLogger


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
    def __init__(self, path: Path, logger: ContextLogger) -> None:
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
                error,  # noqa: TRY401 - ContextLogger records explicit error metadata
                path=self.path,
                run_id=run_id,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise StorageError(f"failed to write {self.path}: {error}") from error


class CatalogRepository(_AtomicCsvRepository):
    def __init__(self, data_dir: Path, logger: ContextLogger) -> None:
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

    def __init__(self, data_dir: Path, logger: ContextLogger) -> None:
        super().__init__(data_dir / "normalized" / "kamis_prices.csv", logger)

    @classmethod
    def _key(cls, row: dict[str, Any]) -> tuple[str, ...]:
        return tuple(str(row.get(field, "")) for field in cls._key_fields)

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
        for row in self._read():
            observed = date.fromisoformat(row["observed_date"])
            if filters.price_type and row.get("price_type") != filters.price_type:
                continue
            if filters.item_code and row.get("item_code") != filters.item_code:
                continue
            if (
                filters.item_name
                and filters.item_name.casefold()
                not in row.get("item_name", "").casefold()
            ):
                continue
            if filters.start_date and observed < filters.start_date:
                continue
            if filters.end_date and observed > filters.end_date:
                continue
            converted: dict[str, Any] = dict(row)
            converted["price_krw"] = (
                float(row["price_krw"]) if row.get("price_krw") else None
            )
            result.append(converted)
        return result

    def count(self) -> int:
        return len(self._read())


class RunRepository(_AtomicCsvRepository):
    def __init__(self, data_dir: Path, logger: ContextLogger) -> None:
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
