from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from config.server_config import Settings
from log.context_logger import ContextLogger


class CollectionServiceProtocol(Protocol):
    def collect(self, start_date: Any, end_date: Any) -> Any: ...


class SchedulerProtocol(Protocol):
    def add_job(self, function: Any, trigger: str, **kwargs: Any) -> Any: ...

    def start(self, paused: bool = False) -> None: ...

    def shutdown(self, wait: bool = True) -> None: ...


class DailyScheduler:
    def __init__(
        self,
        scheduler: SchedulerProtocol,
        collection_service: CollectionServiceProtocol,
        settings: Settings,
        logger: ContextLogger,
    ) -> None:
        self._scheduler = scheduler
        self._service = collection_service
        self._settings = settings
        self._logger = logger
        self._registered = False

    def _collect_today(self) -> None:
        today = datetime.now(ZoneInfo(self._settings.timezone)).date()
        self._logger.info(  # noqa: PLE1205 - custom structured logger
            "scheduler.collection.started",
            "Scheduled daily KAMIS collection started",
            source="kamis",
            observed_date=today,
        )
        try:
            run = self._service.collect(today, today)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "scheduler.collection.completed",
                "Scheduled daily KAMIS collection completed",
                source="kamis",
                observed_date=today,
                run_id=getattr(run, "run_id", None),
                status=getattr(run, "status", None),
            )
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205 - custom structured logger
                "scheduler.collection.failed",
                "Scheduled daily KAMIS collection failed",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                source="kamis",
                observed_date=today,
            )
            raise

    def start(self, *, paused: bool = False) -> None:
        if not self._registered:
            self._scheduler.add_job(
                self._collect_today,
                "cron",
                id="kamis-daily-collection",
                hour=self._settings.scheduler_hour,
                minute=self._settings.scheduler_minute,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
                replace_existing=True,
            )
            self._registered = True
        self._logger.info(  # noqa: PLE1205 - custom structured logger
            "scheduler.started",
            "Daily scheduler started",
            hour=self._settings.scheduler_hour,
            minute=self._settings.scheduler_minute,
            timezone=self._settings.timezone,
            paused=paused,
        )
        self._scheduler.start(paused=paused)

    def shutdown(self) -> None:
        self._logger.info(  # noqa: PLE1205 - custom structured logger
            "scheduler.shutdown", "Daily scheduler is shutting down"
        )
        self._scheduler.shutdown(wait=True)
