from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections.abc import Sequence
from datetime import date

from app.collectors.shopping import local_today
from app.domain.models import CollectionError, CollectionRun, RunStatus
from app.infrastructure.csv_repository import RunRepository
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from config.server_config import Settings
from log import app_logger


def build_market_collector() -> MarketDataClient:
    return MarketDataClient(None, app_logger)


def run_market(observed_date: date) -> CollectionRun:
    settings = Settings.from_env()
    repository = MarketRepository(settings.data_dir, app_logger)
    runs = RunRepository(settings.data_dir, app_logger)
    collector = build_market_collector()
    run = CollectionRun.start("market", observed_date, observed_date)
    runs.save(run)
    try:
        rows = collector.fetch(observed_date, observed_date)
        repository.upsert(rows, run.run_id)
        completed = run.finish(
            RunStatus.SUCCESS,
            record_count=len(rows),
            error_count=0,
        )
        runs.save(completed)
        return completed
    except Exception as error:
        failed = run.finish(
            RunStatus.FAILED,
            record_count=0,
            error_count=1,
            errors=(CollectionError("market", type(error).__name__, str(error)),),
        )
        runs.save(failed)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Collect stock and futures data")
    parser.add_argument("--date", type=date.fromisoformat)
    arguments = parser.parse_args(argv)
    observed_date = arguments.date or local_today(settings.timezone)
    run = run_market(observed_date)
    return 1 if run.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
