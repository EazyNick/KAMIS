from __future__ import annotations

from collections.abc import Callable
from datetime import date
from threading import Lock
from typing import Any, Protocol

from app.core.errors import CollectionAlreadyRunning
from app.domain.models import (
    CollectionError,
    CollectionRun,
    ProductCatalogEntry,
    RunStatus,
)
from log.logger import StructuredLogger


class AnalyticsRefresher(Protocol):
    def refresh(self, catalog: list[ProductCatalogEntry], run_id: str) -> int: ...


class DailyPipeline:
    """Runs every independent daily source and records one auditable outcome."""

    def __init__(
        self,
        kamis_service: Any,
        online_service: Any,
        market_client: Any,
        market_repository: Any,
        run_repository: Any,
        catalog_provider: Callable[[], list[ProductCatalogEntry]],
        analytics_refresher: AnalyticsRefresher | None,
        logger: StructuredLogger,
    ) -> None:
        self._kamis = kamis_service
        self._online = online_service
        self._market = market_client
        self._market_repository = market_repository
        self._runs = run_repository
        self._catalog_provider = catalog_provider
        self._analytics = analytics_refresher
        self._logger = logger
        self._run_lock = Lock()

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    def acquire_for_test(self) -> None:
        self._run_lock.acquire()

    def release_for_test(self) -> None:
        self._run_lock.release()

    def collect(
        self, observed_date: date, end_date: date | None = None
    ) -> CollectionRun:
        if end_date is not None and end_date != observed_date:
            raise ValueError("daily pipeline accepts one observed date")
        if not self._run_lock.acquire(blocking=False):
            raise CollectionAlreadyRunning(
                "a unified daily collection is already running"
            )
        try:
            return self._collect_unlocked(observed_date)
        finally:
            self._run_lock.release()

    def _collect_unlocked(self, observed_date: date) -> CollectionRun:
        run = CollectionRun.start("daily_pipeline", observed_date, observed_date)
        self._runs.save(run)
        record_count = 0
        errors: list[CollectionError] = []
        self._logger.info(  # noqa: PLE1205
            "daily_pipeline.started",
            "Unified daily collection started",
            run_id=run.run_id,
            observed_date=observed_date,
        )

        if self._source_completed("kamis", observed_date, run.run_id):
            self._log_source_skipped("kamis", observed_date, run.run_id)
        else:
            self._log_source_started("kamis", observed_date, run.run_id)
            try:
                kamis_run = self._kamis.collect(observed_date, observed_date)
                record_count += int(getattr(kamis_run, "record_count", 0))
                if getattr(kamis_run, "error_count", 0):
                    errors.append(
                        CollectionError(
                            "kamis",
                            "PartialFailure",
                            f"{kamis_run.error_count} KAMIS queries failed",
                        )
                    )
            except Exception as error:  # noqa: BLE001 - source isolation boundary
                self._record_error(errors, "kamis", error, run.run_id)

        try:
            catalog = self._catalog_provider()
        except Exception as error:  # noqa: BLE001 - source isolation boundary
            catalog = []
            self._record_error(errors, "catalog", error, run.run_id)

        if self._source_completed(
            "online",
            observed_date,
            run.run_id,
            data_probe=lambda: self._online.has_collected_date(catalog, observed_date),
        ):
            self._log_source_skipped("online", observed_date, run.run_id)
        else:
            online_checkpoint = CollectionRun.start(
                "online", observed_date, observed_date
            )
            self._runs.save(online_checkpoint)
            self._log_source_started(
                "online",
                observed_date,
                run.run_id,
                catalog_count=len(catalog),
            )
            try:
                online_result = self._online.collect(catalog, observed_date, run.run_id)
                online_count = int(getattr(online_result, "offer_count", 0))
                record_count += online_count
                online_errors = tuple(
                    CollectionError("online", "SourceFailure", str(message))
                    for message in getattr(online_result, "errors", ())
                )
                errors.extend(online_errors)
                online_status = (
                    RunStatus.PARTIAL_FAILURE if online_errors else RunStatus.SUCCESS
                )
                self._runs.save(
                    online_checkpoint.finish(
                        online_status,
                        record_count=online_count,
                        error_count=len(online_errors),
                        errors=online_errors,
                    )
                )
            except Exception as error:  # noqa: BLE001 - source isolation boundary
                self._save_failed_checkpoint(online_checkpoint, error)
                self._record_error(errors, "online", error, run.run_id)

        if self._source_completed(
            "market",
            observed_date,
            run.run_id,
            data_probe=lambda: self._market_repository.has_collected_date(
                observed_date
            ),
        ):
            self._log_source_skipped("market", observed_date, run.run_id)
        else:
            market_checkpoint = CollectionRun.start(
                "market", observed_date, observed_date
            )
            self._runs.save(market_checkpoint)
            symbols = getattr(self._market, "symbols", {})
            self._log_source_started(
                "market",
                observed_date,
                run.run_id,
                series_count=len(symbols) if symbols else None,
            )
            try:
                market_rows = self._market.fetch(observed_date, observed_date)
                self._market_repository.upsert(market_rows, run.run_id)
                record_count += len(market_rows)
                self._runs.save(
                    market_checkpoint.finish(
                        RunStatus.SUCCESS,
                        record_count=len(market_rows),
                        error_count=0,
                    )
                )
            except Exception as error:  # noqa: BLE001 - source isolation boundary
                self._save_failed_checkpoint(market_checkpoint, error)
                self._record_error(errors, "market", error, run.run_id)

        if self._analytics is not None:
            try:
                record_count += self._analytics.refresh(catalog, run.run_id)
            except Exception as error:  # noqa: BLE001 - source isolation boundary
                self._record_error(errors, "analytics", error, run.run_id)

        status = RunStatus.SUCCESS
        if errors:
            status = RunStatus.PARTIAL_FAILURE if record_count else RunStatus.FAILED
        completed = run.finish(
            status,
            record_count=record_count,
            error_count=len(errors),
            errors=tuple(errors),
        )
        self._runs.save(completed)
        self._logger.info(  # noqa: PLE1205
            "daily_pipeline.completed",
            "Unified daily collection completed",
            run_id=run.run_id,
            status=status,
            record_count=record_count,
            error_count=len(errors),
        )
        return completed

    def _source_completed(
        self,
        source: str,
        observed_date: date,
        run_id: str,
        *,
        data_probe: Callable[[], bool] | None = None,
    ) -> bool:
        try:
            if self._runs.has_successful_run(source, observed_date):
                return True
            if data_probe is None or not data_probe():
                return False
            recovered = CollectionRun.start(
                source, observed_date, observed_date
            ).finish(
                RunStatus.SUCCESS,
                record_count=0,
                error_count=0,
            )
            self._runs.save(recovered)
            self._logger.info(  # noqa: PLE1205
                "daily_pipeline.checkpoint.recovered",
                "Successful source checkpoint recovered from dated stored data",
                run_id=run_id,
                checkpoint_run_id=recovered.run_id,
                source=source,
                observed_date=observed_date,
            )
            return True
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205
                "daily_pipeline.checkpoint.failed",
                "Could not inspect source checkpoint; source will be collected",
                error,  # noqa: TRY401
                run_id=run_id,
                source=source,
                observed_date=observed_date,
            )
            return False

    def _log_source_skipped(
        self, source: str, observed_date: date, run_id: str
    ) -> None:
        self._logger.info(  # noqa: PLE1205
            "daily_pipeline.source.skipped",
            "Source already completed for observed date",
            run_id=run_id,
            source=source,
            observed_date=observed_date,
            reason="successful_checkpoint_exists",
        )

    def _log_source_started(
        self,
        source: str,
        observed_date: date,
        run_id: str,
        **context: object,
    ) -> None:
        self._logger.info(
            "daily_pipeline.source.started",
            "Daily source collection started",
            run_id=run_id,
            source=source,
            observed_date=observed_date,
            **{key: value for key, value in context.items() if value is not None},
        )

    def _save_failed_checkpoint(
        self, checkpoint: CollectionRun, error: Exception
    ) -> None:
        self._runs.save(
            checkpoint.finish(
                RunStatus.FAILED,
                record_count=0,
                error_count=1,
                errors=(
                    CollectionError(
                        checkpoint.source,
                        type(error).__name__,
                        str(error),
                    ),
                ),
            )
        )

    def _record_error(
        self,
        errors: list[CollectionError],
        scope: str,
        error: Exception,
        run_id: str,
    ) -> None:
        errors.append(CollectionError(scope, type(error).__name__, str(error)))
        self._logger.exception(  # noqa: PLE1205
            "daily_pipeline.source.failed",
            "Daily source failed; remaining sources will continue",
            error,
            run_id=run_id,
            source=scope,
        )
