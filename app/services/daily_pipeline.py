from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from app.domain.models import (
    CollectionError,
    CollectionRun,
    ProductCatalogEntry,
    RunStatus,
)
from log.context_logger import ContextLogger


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
        logger: ContextLogger,
    ) -> None:
        self._kamis = kamis_service
        self._online = online_service
        self._market = market_client
        self._market_repository = market_repository
        self._runs = run_repository
        self._catalog_provider = catalog_provider
        self._analytics = analytics_refresher
        self._logger = logger

    def collect(
        self, observed_date: date, end_date: date | None = None
    ) -> CollectionRun:
        if end_date is not None and end_date != observed_date:
            raise ValueError("daily pipeline accepts one observed date")
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

        try:
            online_result = self._online.collect(catalog, observed_date, run.run_id)
            record_count += int(getattr(online_result, "offer_count", 0))
            for message in getattr(online_result, "errors", ()):
                errors.append(CollectionError("online", "SourceFailure", str(message)))
        except Exception as error:  # noqa: BLE001 - source isolation boundary
            self._record_error(errors, "online", error, run.run_id)

        try:
            market_rows = self._market.fetch(observed_date, observed_date)
            self._market_repository.upsert(market_rows, run.run_id)
            record_count += len(market_rows)
        except Exception as error:  # noqa: BLE001 - source isolation boundary
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
