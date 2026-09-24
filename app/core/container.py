from __future__ import annotations

from dataclasses import dataclass

import requests

from app.infrastructure.analytics_repository import AnalyticsRepository
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from app.infrastructure.online_repository import OnlinePriceRepository
from app.infrastructure.shopping_sources import (
    CoupangShoppingSource,
    NaverShoppingSource,
)
from app.services.analytics import AnalyticsBatchService, AnalyticsService
from app.services.collection_service import KamisCollectionService
from app.services.comparison import ComparisonService
from app.services.daily_pipeline import DailyPipeline
from app.services.online_collection import OnlineCollectionService
from app.services.online_pricing import OnlinePriceCalculator
from config.server_config import Settings
from log import app_logger


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    catalog_repository: CatalogRepository
    price_repository: PriceRepository
    run_repository: RunRepository
    collection_service: KamisCollectionService
    online_repository: OnlinePriceRepository | None = None
    market_repository: MarketRepository | None = None
    analytics_repository: AnalyticsRepository | None = None
    online_collection_service: OnlineCollectionService | None = None
    market_client: MarketDataClient | None = None
    comparison_service: ComparisonService | None = None
    daily_pipeline: DailyPipeline | None = None

    @classmethod
    def build(cls, settings: Settings) -> ApplicationContainer:
        catalog = CatalogRepository(settings.data_dir, app_logger)
        prices = PriceRepository(settings.data_dir, app_logger)
        runs = RunRepository(settings.data_dir, app_logger)
        client = KamisClient(settings, build_requests_session(), app_logger)
        service = KamisCollectionService(client, catalog, prices, runs, app_logger)
        online_repository = OnlinePriceRepository(settings.data_dir, app_logger)
        market_repository = MarketRepository(settings.data_dir, app_logger)
        analytics_repository = AnalyticsRepository(settings.data_dir, app_logger)
        shopping_session = requests.Session()
        sources = [
            NaverShoppingSource(shopping_session, app_logger),
            CoupangShoppingSource(shopping_session, app_logger),
        ]
        online_service = OnlineCollectionService(
            sources,
            online_repository,
            OnlinePriceCalculator(),
            app_logger,
        )
        market_client = MarketDataClient(None, app_logger)
        analytics = AnalyticsService()
        comparison = ComparisonService(
            prices, online_repository, market_repository, analytics
        )
        analytics_batch = AnalyticsBatchService(
            comparison, analytics, analytics_repository
        )
        pipeline = DailyPipeline(
            service,
            online_service,
            market_client,
            market_repository,
            runs,
            catalog.entries,
            analytics_batch,
            app_logger,
        )
        return cls(
            settings,
            catalog,
            prices,
            runs,
            service,
            online_repository,
            market_repository,
            analytics_repository,
            online_service,
            market_client,
            comparison,
            pipeline,
        )
