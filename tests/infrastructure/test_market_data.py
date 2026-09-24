from datetime import date
from pathlib import Path

import pandas as pd

from app.infrastructure.market_data import MarketDataClient, MarketRepository
from log import app_logger


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
    frame = pd.DataFrame({"^KS11": [2600.0]}, index=pd.to_datetime(["2026-09-24"]))
    client = MarketDataClient(
        lambda **kwargs: frame, app_logger, symbols={"kospi": "^KS11"}
    )
    rows = client.fetch(date(2026, 9, 24), date(2026, 9, 24))
    repository = MarketRepository(tmp_path, app_logger)

    repository.upsert(rows, "run-1")
    repository.upsert(rows, "run-2")

    assert len(repository.search(series_id="kospi")) == 1
