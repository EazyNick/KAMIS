from datetime import date
from types import SimpleNamespace

import pytest

from app.core.errors import CollectionAlreadyRunning
from app.domain.models import RunStatus
from app.services.daily_pipeline import DailyPipeline
from log import app_logger


class Kamis:
    def collect(self, start_date, end_date):
        return SimpleNamespace(status=RunStatus.SUCCESS, record_count=2, error_count=0)


class Online:
    def collect(self, catalog, observed_date, run_id):
        return SimpleNamespace(
            offer_count=3, error_count=1, errors=("coupang:blocked",)
        )


class Market:
    def fetch(self, start_date, end_date):
        return [SimpleNamespace(series_id="kospi")]


class MarketRepo:
    def __init__(self):
        self.rows = []

    def upsert(self, rows, run_id):
        self.rows.extend(rows)


class Runs:
    def __init__(self, successful_sources=()):
        self.saved = []
        self.successful_sources = set(successful_sources)

    def save(self, run):
        self.saved.append(run)
        if run.status is RunStatus.SUCCESS:
            self.successful_sources.add(run.source)

    def has_successful_run(self, source, requested_date):
        return source in self.successful_sources


def test_daily_pipeline_isolates_source_partial_failure() -> None:
    runs = Runs()
    market_repository = MarketRepo()
    pipeline = DailyPipeline(
        Kamis(),
        Online(),
        Market(),
        market_repository,
        runs,
        lambda: [SimpleNamespace(item_code="111")],
        None,
        app_logger,
    )

    run = pipeline.collect(date(2026, 9, 24))

    assert run.status is RunStatus.PARTIAL_FAILURE
    assert run.record_count == 6
    assert run.error_count == 1
    assert len(market_repository.rows) == 1
    assert runs.saved[-1].status is RunStatus.PARTIAL_FAILURE


def test_daily_pipeline_rejects_concurrent_run() -> None:
    pipeline = DailyPipeline(
        Kamis(), Online(), Market(), MarketRepo(), Runs(), list, None, app_logger
    )
    pipeline.acquire_for_test()
    try:
        with pytest.raises(CollectionAlreadyRunning):
            pipeline.collect(date(2026, 9, 24))
    finally:
        pipeline.release_for_test()


def test_daily_pipeline_skips_sources_already_completed_for_date() -> None:
    class AlreadyCollectedKamis:
        def collect(self, start_date, end_date):
            raise AssertionError("completed KAMIS source must not run again")

    class CleanOnline:
        calls = 0

        def collect(self, catalog, observed_date, run_id):
            self.calls += 1
            return SimpleNamespace(offer_count=3, error_count=0, errors=())

    runs = Runs(successful_sources={"kamis"})
    online = CleanOnline()
    pipeline = DailyPipeline(
        AlreadyCollectedKamis(),
        online,
        Market(),
        MarketRepo(),
        runs,
        lambda: [SimpleNamespace(item_code="111")],
        None,
        app_logger,
    )

    first = pipeline.collect(date(2026, 9, 25))
    second = pipeline.collect(date(2026, 9, 25))

    assert first.status is RunStatus.SUCCESS
    assert second.status is RunStatus.SUCCESS
    assert online.calls == 1
    assert {"online", "market"}.issubset(runs.successful_sources)


def test_daily_pipeline_recovers_checkpoints_from_existing_dated_data() -> None:
    class StoredOnline:
        def has_collected_date(self, catalog, observed_date):
            return True

        def collect(self, catalog, observed_date, run_id):
            raise AssertionError("stored online data must not be recollected")

    class StoredMarketRepo(MarketRepo):
        def has_collected_date(self, observed_date):
            return True

    class AlreadyCollectedMarket:
        def fetch(self, start_date, end_date):
            raise AssertionError("stored market data must not be recollected")

    runs = Runs(successful_sources={"kamis"})
    pipeline = DailyPipeline(
        Kamis(),
        StoredOnline(),
        AlreadyCollectedMarket(),
        StoredMarketRepo(),
        runs,
        lambda: [SimpleNamespace(item_code="111")],
        None,
        app_logger,
    )

    result = pipeline.collect(date(2026, 9, 25))

    assert result.status is RunStatus.SUCCESS
    assert {"online", "market"}.issubset(runs.successful_sources)


def test_daily_pipeline_logs_each_source_before_collection() -> None:
    class RecordingLogger:
        def __init__(self):
            self.entries = []

        def info(self, event, message, **context):
            self.entries.append((event, context))

        def exception(self, event, message, error, **context):
            self.entries.append((event, context))

    logger = RecordingLogger()
    pipeline = DailyPipeline(
        Kamis(),
        Online(),
        Market(),
        MarketRepo(),
        Runs(),
        lambda: [SimpleNamespace(item_code="111")],
        None,
        logger,
    )

    pipeline.collect(date(2026, 9, 24))

    started_sources = [
        context["source"]
        for event, context in logger.entries
        if event == "daily_pipeline.source.started"
    ]
    assert started_sources == ["kamis", "online", "market"]
