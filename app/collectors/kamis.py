from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections.abc import Sequence
from datetime import date

from app.collectors.shopping import local_today
from app.domain.models import CollectionRun, RunStatus
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from app.services.collection_service import KamisCollectionService
from config.server_config import Settings
from log import app_logger


def build_kamis_collector(
    settings: Settings,
    catalog_repository: CatalogRepository,
    price_repository: PriceRepository,
    run_repository: RunRepository,
) -> KamisCollectionService:
    client = KamisClient(settings, build_requests_session(), app_logger)
    return KamisCollectionService(
        client,
        catalog_repository,
        price_repository,
        run_repository,
        app_logger,
    )


def run_kamis(observed_date: date) -> CollectionRun:
    settings = Settings.from_env()
    catalog = CatalogRepository(settings.data_dir, app_logger)
    prices = PriceRepository(settings.data_dir, app_logger)
    runs = RunRepository(settings.data_dir, app_logger)
    return build_kamis_collector(settings, catalog, prices, runs).collect(
        observed_date, observed_date
    )


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Collect KAMIS daily prices")
    parser.add_argument("--date", type=date.fromisoformat)
    arguments = parser.parse_args(argv)
    observed_date = arguments.date or local_today(settings.timezone)
    run = run_kamis(observed_date)
    return 1 if run.status is RunStatus.FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
