from __future__ import annotations

"""Backfill about 20 years of agricultural commodity futures daily closes.

Run from the repository root:
    python scripts/backfill/backfill_futures_20y.py

Output:
    data/normalized/market_observations.csv
"""

import time
from datetime import date
from uuid import uuid4

from app.infrastructure.market_data import (
    DEFAULT_MARKET_SYMBOLS,
    MarketDataClient,
    MarketRepository,
)
from config.server_config import Settings
from log import app_logger


FUTURES_SERIES = {
    "corn_futures",
    "wheat_futures",
    "soybean_futures",
    "rough_rice_futures",
    "coffee_futures",
    "sugar_futures",
    "cotton_futures",
    "orange_juice_futures",
}
MAX_ATTEMPTS = 3


def start_date_20y(today: date) -> date:
    return date(today.year - 20, 1, 1)


def fetch_with_retry(
    client: MarketDataClient,
    series_id: str,
    start_date: date,
    end_date: date,
):
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return client.fetch(start_date, end_date, series_ids={series_id})
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt == MAX_ATTEMPTS:
                break
            wait_seconds = 2 ** (attempt - 1)
            print(
                f"[RETRY] {series_id}: {type(error).__name__}: {error} "
                f"-> retry in {wait_seconds}s"
            )
            time.sleep(wait_seconds)

    assert last_error is not None
    raise last_error


def main() -> int:
    settings = Settings.from_env()
    repository = MarketRepository(settings.data_dir, app_logger)
    client = MarketDataClient(None, app_logger)

    today = date.today()
    start = start_date_20y(today)
    run_id = f"futures-20y-{uuid4().hex}"

    print(f"[START] futures: {start} ~ {today}")
    print(f"[OUTPUT] {repository.path}")

    total = 0
    failures: list[str] = []

    for series_id in sorted(FUTURES_SERIES):
        ticker = DEFAULT_MARKET_SYMBOLS[series_id]
        print(f"\n[FETCH] {series_id} ({ticker})")
        try:
            rows = fetch_with_retry(client, series_id, start, today)
            repository.upsert(rows, run_id)
            total += len(rows)
            if rows:
                first = min(row.observed_date for row in rows)
                last = max(row.observed_date for row in rows)
                print(f"[OK] {series_id}: {len(rows):,} rows ({first} ~ {last})")
            else:
                print(f"[NO DATA] {series_id}")
        except Exception as error:  # noqa: BLE001
            failures.append(series_id)
            print(f"[FAILED] {series_id}: {type(error).__name__}: {error}")

    print("\n" + "=" * 72)
    print(f"[DONE] fetched/upserted rows: {total:,}")
    print(f"[FAILED SERIES] {', '.join(failures) if failures else 'none'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
