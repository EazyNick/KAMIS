from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.domain.models import RunStatus
from app.services.startup_collection import StartupCollectionService
from config.server_config import Settings
from log import app_logger

TODAY = date(2026, 9, 24)


class FakeRunRepository:
    def __init__(self, successful: bool) -> None:
        self.successful = successful
        self.queries: list[tuple[str, date]] = []

    def has_successful_run(self, source: str, requested_date: date) -> bool:
        self.queries.append((source, requested_date))
        return self.successful


class FakePipeline:
    def __init__(self, *, running: bool = False) -> None:
        self.is_running = running
        self.calls: list[date] = []

    def collect(self, observed_date: date):
        self.calls.append(observed_date)
        return SimpleNamespace(
            run_id="daily-run-1",
            status=RunStatus.SUCCESS,
            record_count=10,
            error_count=0,
        )


def run_immediately(target) -> None:
    target()


def test_startup_skips_when_today_was_successfully_collected() -> None:
    repository = FakeRunRepository(successful=True)
    pipeline = FakePipeline()
    service = StartupCollectionService(
        pipeline,
        repository,
        Settings.from_env(),
        app_logger,
        task_runner=run_immediately,
        today_provider=lambda: TODAY,
    )

    decision = service.ensure_today()

    assert decision == "already_collected"
    assert repository.queries == [("daily_pipeline", TODAY)]
    assert pipeline.calls == []


def test_startup_collects_today_when_successful_run_is_missing() -> None:
    pipeline = FakePipeline()
    service = StartupCollectionService(
        pipeline,
        FakeRunRepository(successful=False),
        Settings.from_env(),
        app_logger,
        task_runner=run_immediately,
        today_provider=lambda: TODAY,
    )

    decision = service.ensure_today()

    assert decision == "scheduled"
    assert pipeline.calls == [TODAY]


def test_startup_does_not_schedule_while_pipeline_is_running() -> None:
    pipeline = FakePipeline(running=True)
    service = StartupCollectionService(
        pipeline,
        FakeRunRepository(successful=False),
        Settings.from_env(),
        app_logger,
        task_runner=run_immediately,
        today_provider=lambda: TODAY,
    )

    assert service.ensure_today() == "already_running"
    assert pipeline.calls == []
