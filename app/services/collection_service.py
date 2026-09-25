from __future__ import annotations

from datetime import date, timedelta
from threading import Lock
from time import perf_counter
from typing import Protocol

from app.core.errors import CollectionAlreadyRunning
from app.domain.models import (
    CollectionError,
    CollectionRun,
    DateRange,
    PriceObservation,
    PriceQuery,
    PriceType,
    ProductCatalogEntry,
    RunStatus,
)
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from log.logger import StructuredLogger


class KamisClientProtocol(Protocol):
    def fetch_catalog(self) -> list[ProductCatalogEntry]: ...

    def fetch_prices(self, query: PriceQuery) -> list[PriceObservation]: ...


class KamisCollectionService:
    """Orchestrates a complete, failure-isolated KAMIS collection run."""

    def __init__(
        self,
        client: KamisClientProtocol,
        catalog_repository: CatalogRepository,
        price_repository: PriceRepository,
        run_repository: RunRepository,
        logger: StructuredLogger,
    ) -> None:
        self._client = client
        self._catalog_repository = catalog_repository
        self.price_repository = price_repository
        self.run_repository = run_repository
        self._logger = logger
        self._run_lock = Lock()

    @staticmethod
    def split_backfill_period(start_date: date, end_date: date) -> list[DateRange]:
        if end_date < start_date:
            return []
        ranges: list[DateRange] = []
        cursor = start_date
        while cursor <= end_date:
            chunk_end = min(cursor + timedelta(days=365), end_date)
            ranges.append(DateRange(cursor, chunk_end))
            cursor = chunk_end + timedelta(days=1)
        return ranges

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    def acquire_for_test(self) -> None:
        self._run_lock.acquire()

    def release_for_test(self) -> None:
        self._run_lock.release()

    def collect(self, start_date: date, end_date: date) -> CollectionRun:
        if not self._run_lock.acquire(blocking=False):
            raise CollectionAlreadyRunning("a KAMIS collection is already running")

        run = CollectionRun.start("kamis", start_date, end_date)
        started = perf_counter()
        try:
            self.run_repository.save(run)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "collection.started",
                "KAMIS collection started",
                run_id=run.run_id,
                start_date=start_date,
                end_date=end_date,
            )
            catalog = self._client.fetch_catalog()
            self._catalog_repository.save_snapshot(catalog, end_date, run.run_id)
            observations, errors = self._collect_catalog_prices(
                catalog, start_date, end_date, run.run_id
            )
            write_result = self.price_repository.upsert(observations, run.run_id)
            status = RunStatus.PARTIAL_FAILURE if errors else RunStatus.SUCCESS
            completed = run.finish(
                status,
                record_count=len(observations),
                error_count=len(errors),
                errors=tuple(errors),
            )
            self.run_repository.save(completed)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "collection.completed",
                "KAMIS collection completed",
                run_id=run.run_id,
                status=completed.status,
                fetched_records=len(observations),
                inserted_records=write_result.inserted,
                updated_records=write_result.updated,
                error_count=len(errors),
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return completed
        except Exception as error:
            failed = run.finish(
                RunStatus.FAILED,
                record_count=0,
                error_count=1,
                errors=(CollectionError("run", type(error).__name__, str(error)),),
            )
            try:
                self.run_repository.save(failed)
            except Exception as persistence_error:
                self._logger.exception(  # noqa: PLE1205
                    "collection.failure_persistence.failed",
                    "Failed to persist failed collection run",
                    persistence_error,  # noqa: TRY401
                    run_id=run.run_id,
                    original_error_type=type(error).__name__,
                )
            self._logger.exception(  # noqa: PLE1205
                "collection.failed",
                "KAMIS collection failed",
                error,  # noqa: TRY401
                run_id=run.run_id,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise
        finally:
            self._run_lock.release()

    def _collect_catalog_prices(
        self,
        catalog: list[ProductCatalogEntry],
        start_date: date,
        end_date: date,
        run_id: str,
    ) -> tuple[list[PriceObservation], list[CollectionError]]:
        observations: list[PriceObservation] = []
        errors: list[CollectionError] = []
        ranges = self.split_backfill_period(start_date, end_date)
        for entry in catalog:
            price_ranks = (
                (PriceType.WHOLESALE, entry.wholesale_rank_codes),
                (PriceType.RETAIL, entry.retail_rank_codes),
            )
            for price_type, ranks in price_ranks:
                for rank_code in ranks:
                    for date_range in ranges:
                        query = PriceQuery(
                            price_type=price_type,
                            start_date=date_range.start,
                            end_date=date_range.end,
                            catalog_entry=entry,
                            rank_code=rank_code,
                        )
                        try:
                            observations.extend(self._client.fetch_prices(query))
                        except Exception as error:
                            scope = (
                                f"{entry.item_code}:{entry.kind_code}:"
                                f"{price_type.value}:{rank_code}:"
                                f"{date_range.start}/{date_range.end}"
                            )
                            errors.append(
                                CollectionError(scope, type(error).__name__, str(error))
                            )
                            self._logger.exception(  # noqa: PLE1205
                                "collection.query.failed",
                                "KAMIS item query failed; collection will continue",
                                error,  # noqa: TRY401
                                run_id=run_id,
                                item_code=entry.item_code,
                                kind_code=entry.kind_code,
                                price_type=price_type,
                                rank_code=rank_code,
                                start_date=date_range.start,
                                end_date=date_range.end,
                            )
        return observations, errors
