from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.infrastructure.csv_repository import RunRepository
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from app.services.market_history import MarketHistoryService
from log import app_logger


def build_service(tmp_path, downloader, start, end, symbols=None):
    prices = SimpleNamespace(
        observed_date_range=lambda: (start, end) if start else None
    )
    market = MarketRepository(tmp_path, app_logger)
    runs = RunRepository(tmp_path, app_logger)
    client = MarketDataClient(
        downloader, app_logger, symbols=symbols or {"kospi": "^KS11", "sp500": "^GSPC"}
    )
    return MarketHistoryService(prices, market, client, runs, app_logger), market, runs


def test_backfill_matches_kamis_range_and_skips_existing_on_restart(tmp_path):
    calls = []

    def downloader(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame(
            {"Close": [10, 20, 30]},
            index=pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"]),
        )

    service, market, runs = build_service(
        tmp_path, downloader, date(2026, 9, 21), date(2026, 9, 23)
    )
    assert service.collect() == 6
    assert {tuple(call["tickers"]) for call in calls} == {("^KS11",), ("^GSPC",)}
    assert all(
        call["start"] == "2026-09-21" and call["end"] == "2026-09-24" for call in calls
    )
    assert len(market.search()) == 6
    assert runs.latest()["status"] == "success"
    assert service.collect() == 0
    assert len(calls) == 2


def test_backfill_repairs_internal_gap_and_retries_empty_series(tmp_path):
    calls = []

    def downloader(**kwargs):
        calls.append(kwargs)
        if kwargs["tickers"] == ["^GSPC"]:
            return pd.DataFrame()
        days = ["2026-09-21", "2026-09-23"] if len(calls) == 1 else ["2026-09-22"]
        return pd.DataFrame({"Close": [10] * len(days)}, index=pd.to_datetime(days))

    service, market, runs = build_service(
        tmp_path, downloader, date(2026, 9, 21), date(2026, 9, 23)
    )
    assert service.collect() == 2
    assert runs.latest()["status"] == "partial_failure"
    assert service.collect() == 1
    assert calls[2]["start"] == "2026-09-22"
    assert calls[2]["end"] == "2026-09-23"
    assert len(market.search(series_id="kospi")) == 3
    assert len(calls) == 4


def test_backfill_respects_korean_and_us_holidays(tmp_path):
    calls = []

    def downloader(**kwargs):
        calls.append(kwargs["tickers"])
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2026-09-25"]))

    service, _, _ = build_service(
        tmp_path, downloader, date(2026, 9, 25), date(2026, 9, 25)
    )
    assert service.collect() == 1
    assert calls == [["^GSPC"]]
    assert service.collect() == 0

    service, _, _ = build_service(
        tmp_path, downloader, date(2026, 7, 3), date(2026, 7, 3), {"sp500": "^GSPC"}
    )
    assert service.collect() == 0
    assert calls == [["^GSPC"]]


def test_backfill_without_kamis_does_not_download(tmp_path):
    def downloader(**kwargs):
        raise AssertionError("No KAMIS period exists")

    service, _, runs = build_service(tmp_path, downloader, None, None)
    assert service.collect() == 0
    assert runs.latest() is None


def test_backfill_preserves_other_series_when_one_download_fails(tmp_path):
    def downloader(**kwargs):
        if kwargs["tickers"] == ["^KS11"]:
            raise RuntimeError("upstream failed")
        return pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2026-09-23"]))

    service, market, runs = build_service(
        tmp_path, downloader, date(2026, 9, 23), date(2026, 9, 23)
    )
    assert service.collect() == 1
    assert len(market.search(series_id="sp500")) == 1
    assert runs.latest()["status"] == "partial_failure"
