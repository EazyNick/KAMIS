from __future__ import annotations

from dataclasses import dataclass

from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from app.services.collection_service import KamisCollectionService
from config.server_config import Settings
from log import app_logger


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    catalog_repository: CatalogRepository
    price_repository: PriceRepository
    run_repository: RunRepository
    collection_service: KamisCollectionService

    @classmethod
    def build(cls, settings: Settings) -> ApplicationContainer:
        catalog = CatalogRepository(settings.data_dir, app_logger)
        prices = PriceRepository(settings.data_dir, app_logger)
        runs = RunRepository(settings.data_dir, app_logger)
        client = KamisClient(settings, build_requests_session(), app_logger)
        service = KamisCollectionService(client, catalog, prices, runs, app_logger)
        return cls(settings, catalog, prices, runs, service)
