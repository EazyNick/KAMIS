from __future__ import annotations

from dataclasses import replace
from datetime import date
from threading import Event
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


def test_startup_checks_history_even_when_today_succeeded() -> None:
    pipeline = FakePipeline()
    history_calls = []
    queued = []
    service = StartupCollectionService(
        pipeline,
        FakeRunRepository(successful=True),
        Settings.from_env(),
        app_logger,
        task_runner=queued.append,
        today_provider=lambda: TODAY,
        history_collector=lambda: history_calls.append("history"),
    )
    assert service.ensure_today() == "scheduled"
    assert service.ensure_today() == "already_running"
    assert history_calls == []
    queued[0]()
    assert history_calls == ["history"]
    assert pipeline.calls == []


def test_startup_checks_history_after_daily_failure() -> None:
    history_calls = []

    class FailingPipeline(FakePipeline):
        def collect(self, observed_date):
            raise RuntimeError("daily unavailable")

    service = StartupCollectionService(
        FailingPipeline(),
        FakeRunRepository(successful=False),
        Settings.from_env(),
        app_logger,
        task_runner=run_immediately,
        today_provider=lambda: TODAY,
        history_collector=lambda: history_calls.append("history"),
    )
    assert service.ensure_today() == "scheduled"
    assert history_calls == ["history"]


def test_built_application_lifespan_starts_history_after_daily_success(
    tmp_path, monkeypatch
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from fastapi.testclient import TestClient

    from app.core.container import ApplicationContainer
    from app.domain.models import CollectionRun
    from app.main import create_app
    from app.services.market_history import MarketHistoryService

    history_started = Event()

    def collect_history(self):
        history_started.set()

    monkeypatch.setattr(MarketHistoryService, "collect", collect_history)
    settings = replace(Settings.from_env(), data_dir=tmp_path)
    container = ApplicationContainer.build(settings)
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    container.run_repository.save(
        CollectionRun.start("daily_pipeline", today, today).finish(
            RunStatus.SUCCESS,
            record_count=0,
            error_count=0,
        )
    )
    with TestClient(create_app(container)):
        assert history_started.wait(timeout=5)
