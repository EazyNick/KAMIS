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
    def __init__(self):
        self.saved = []

    def save(self, run):
        self.saved.append(run)


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
