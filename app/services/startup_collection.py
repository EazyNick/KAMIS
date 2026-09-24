from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from threading import Lock, Thread
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

from config.server_config import Settings
from log.context_logger import ContextLogger

StartupDecision = Literal["scheduled", "already_collected", "already_running"]


class DailyPipelineProtocol(Protocol):
    @property
    def is_running(self) -> bool: ...

    def collect(self, observed_date: date) -> Any: ...


class RunRepositoryProtocol(Protocol):
    def has_successful_run(self, source: str, requested_date: date) -> bool: ...


def start_daemon_task(target: Callable[[], None]) -> None:
    Thread(
        target=target,
        name="daily-startup-collection",
        daemon=True,
    ).start()


class StartupCollectionService:
    """Schedules today's unified collection once when the API process starts."""

    def __init__(
        self,
        pipeline: DailyPipelineProtocol,
        run_repository: RunRepositoryProtocol,
        settings: Settings,
        logger: ContextLogger,
        *,
        task_runner: Callable[[Callable[[], None]], None] = start_daemon_task,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._runs = run_repository
        self._logger = logger
        self._task_runner = task_runner
        self._today_provider = today_provider or (
            lambda: datetime.now(ZoneInfo(settings.timezone)).date()
        )
        self._lock = Lock()
        self._scheduled_dates: set[date] = set()

    def ensure_today(self) -> StartupDecision:
        observed_date = self._today_provider()
        with self._lock:
            if self._runs.has_successful_run("daily_pipeline", observed_date):
                self._logger.info(  # noqa: PLE1205 - custom structured logger
                    "startup.collection.skipped",
                    "Today's daily collection already succeeded",
                    source="daily_pipeline",
                    observed_date=observed_date,
                    reason="already_collected",
                )
                return "already_collected"
            if self._pipeline.is_running or observed_date in self._scheduled_dates:
                self._logger.info(  # noqa: PLE1205 - custom structured logger
                    "startup.collection.skipped",
                    "Daily collection is already running or scheduled",
                    source="daily_pipeline",
                    observed_date=observed_date,
                    reason="already_running",
                )
                return "already_running"
            self._scheduled_dates.add(observed_date)

        self._logger.info(  # noqa: PLE1205 - custom structured logger
            "startup.collection.scheduled",
            "Today's missing daily collection was scheduled",
            source="daily_pipeline",
            observed_date=observed_date,
        )
        self._task_runner(lambda: self._collect(observed_date))
        return "scheduled"

    def _collect(self, observed_date: date) -> None:
        try:
            run = self._pipeline.collect(observed_date)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "startup.collection.completed",
                "Startup daily collection completed",
                source="daily_pipeline",
                observed_date=observed_date,
                run_id=getattr(run, "run_id", None),
                status=getattr(run, "status", None),
                record_count=getattr(run, "record_count", 0),
                error_count=getattr(run, "error_count", 0),
            )
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205 - custom structured logger
                "startup.collection.failed",
                "Startup daily collection failed",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                source="daily_pipeline",
                observed_date=observed_date,
            )
        finally:
            with self._lock:
                self._scheduled_dates.discard(observed_date)
