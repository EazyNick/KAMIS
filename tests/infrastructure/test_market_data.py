import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Event

import pandas as pd
import pytest

from app.infrastructure.market_data import MarketDataClient, MarketRepository
from log import app_logger
from log.logger import StructuredLogger


def test_market_client_normalizes_multi_ticker_close_data() -> None:
    index = pd.to_datetime(["2026-09-23", "2026-09-24"])
    frame = pd.DataFrame(
        {
            ("^KS11", "Close"): [2600.0, 2610.0],
            ("^GSPC", "Close"): [5000.0, 5010.0],
        },
        index=index,
    )

    def downloader(**kwargs):
        return frame

    client = MarketDataClient(
        downloader, app_logger, symbols={"kospi": "^KS11", "sp500": "^GSPC"}
    )
    rows = client.fetch(date(2026, 9, 23), date(2026, 9, 24))

    assert len(rows) == 4
    assert {row.series_id for row in rows} == {"kospi", "sp500"}
    assert rows[-1].observed_date == date(2026, 9, 24)


def test_market_repository_upserts_by_series_and_date(tmp_path: Path) -> None:
    frame = pd.DataFrame({"^KS11": [2600.0]}, index=pd.to_datetime(["2026-09-23"]))
    client = MarketDataClient(
        lambda **kwargs: frame, app_logger, symbols={"kospi": "^KS11"}
    )
    rows = client.fetch(date(2026, 9, 23), date(2026, 9, 23))
    repository = MarketRepository(tmp_path, app_logger)

    repository.upsert(rows, "run-1")
    repository.upsert(rows, "run-2")

    assert len(repository.search(series_id="kospi")) == 1


@pytest.mark.parametrize(
    ("observed_date", "reason"),
    [
        (date(2026, 9, 25), "추석"),
        (date(2026, 2, 17), "설날"),
        (date(2026, 3, 2), "대체"),
        (date(2026, 9, 27), "주말"),
        (date(2026, 12, 31), "연말"),
    ],
)
def test_krx_closed_day_logs_normal_skip_without_download(
    observed_date, reason, caplog
) -> None:
    def downloader(**kwargs):
        pytest.fail("Closed Korean markets must not be downloaded")

    logger = StructuredLogger(logging.getLogger("test.market.holiday"))
    client = MarketDataClient(
        downloader, logger, symbols={"kospi": "^KS11", "kosdaq": "^KQ11"}
    )
    with caplog.at_level(logging.INFO):
        rows = client.fetch(observed_date, observed_date)

    assert rows == []
    assert "event=market.collection.closed" in caplog.text
    assert reason in caplog.text
    assert observed_date.isoformat() in caplog.text
    assert "정상" in caplog.text
    assert all(record.levelno == logging.INFO for record in caplog.records)


def test_korean_holiday_keeps_foreign_market_download(caplog) -> None:
    def downloader(**kwargs):
        assert kwargs["tickers"] == ["^GSPC"]
        return pd.DataFrame({"Close": [5000.0]}, index=pd.to_datetime(["2026-09-25"]))

    logger = StructuredLogger(logging.getLogger("test.market.holiday"))
    client = MarketDataClient(
        downloader, logger, symbols={"kospi": "^KS11", "sp500": "^GSPC"}
    )
    with caplog.at_level(logging.INFO):
        rows = client.fetch(date(2026, 9, 25), date(2026, 9, 25))

    assert [(row.series_id, row.close) for row in rows] == [("sp500", 5000.0)]
    assert "market.collection.closed" in caplog.text


def test_trading_day_empty_data_is_not_reported_as_holiday(caplog) -> None:
    requested = []

    def downloader(**kwargs):
        requested.extend(kwargs["tickers"])
        return pd.DataFrame()

    logger = StructuredLogger(logging.getLogger("test.market.holiday"))
    client = MarketDataClient(downloader, logger, symbols={"kospi": "^KS11"})
    with caplog.at_level(logging.INFO):
        assert client.fetch(date(2026, 9, 23), date(2026, 9, 23)) == []

    assert requested == ["^KS11"]
    assert "market.collection.closed" not in caplog.text


def test_market_client_can_fetch_one_missing_series_with_flat_ohlc() -> None:
    def downloader(**kwargs):
        assert kwargs["tickers"] == ["^GSPC"]
        return pd.DataFrame(
            {"Open": [4900.0], "Close": [5000.0], "Volume": [10]},
            index=pd.to_datetime(["2026-09-23"]),
        )

    client = MarketDataClient(
        downloader, app_logger, symbols={"kospi": "^KS11", "sp500": "^GSPC"}
    )
    rows = client.fetch(date(2026, 9, 23), date(2026, 9, 23), series_ids={"sp500"})
    assert [(row.series_id, row.close) for row in rows] == [("sp500", 5000.0)]


def test_concurrent_market_upserts_preserve_both_collections(tmp_path, monkeypatch):
    repository = MarketRepository(tmp_path, app_logger)
    client = MarketDataClient(
        lambda **kwargs: pd.DataFrame(
            {"Close": [10, 20]}, index=pd.to_datetime(["2026-09-22", "2026-09-23"])
        ),
        app_logger,
        symbols={"kospi": "^KS11"},
    )
    rows = client.fetch(date(2026, 9, 22), date(2026, 9, 23))
    first_read = Event()
    second_started = Event()
    second_read = Event()
    release = Event()
    original_read = repository._storage._read

    def controlled_read():
        snapshot = original_read()
        if not first_read.is_set():
            first_read.set()
            assert release.wait(timeout=5)
        else:
            second_read.set()
        return snapshot

    def second_write():
        second_started.set()
        repository.upsert([rows[1]], "second")

    monkeypatch.setattr(repository._storage, "_read", controlled_read)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(repository.upsert, [rows[0]], "first")
        try:
            assert first_read.wait(timeout=5)
            second = executor.submit(second_write)
            assert second_started.wait(timeout=5)
            assert not second_read.wait(timeout=0.2)
        finally:
            release.set()
        first.result()
        second.result()
    assert len(repository.search()) == 2
