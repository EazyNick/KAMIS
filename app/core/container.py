from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.collectors.kamis import build_kamis_collector
from app.collectors.market import build_market_collector
from app.infrastructure.analytics_repository import AnalyticsRepository
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from app.services.analytics import AnalyticsBatchService, AnalyticsService
from app.services.collection_service import KamisCollectionService
from app.services.comparison import ComparisonService
from app.services.daily_pipeline import DailyPipeline
from app.services.dashboard_bootstrap import DashboardBootstrapService
from app.services.kamis_history import KamisHistoryService
from app.services.market_history import MarketHistoryService
from app.services.startup_collection import StartupCollectionService
from scripts.backfill.backfill_kamis_20y import run_backfill
from config.server_config import Settings
from log import app_logger


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    catalog_repository: CatalogRepository
    price_repository: PriceRepository
    run_repository: RunRepository
    collection_service: KamisCollectionService
    online_repository: object | None = None
    market_repository: MarketRepository | None = None
    analytics_repository: AnalyticsRepository | None = None
    online_collection_service: object | None = None
    market_client: MarketDataClient | None = None
    comparison_service: ComparisonService | None = None
    daily_pipeline: DailyPipeline | None = None
    startup_collection_service: StartupCollectionService | None = None
    dashboard_bootstrap_service: DashboardBootstrapService | None = None
    coupang_agent_source: object | None = None
    naver_agent_source: object | None = None

    @classmethod
    def build(cls, settings: Settings) -> ApplicationContainer:
        catalog = CatalogRepository(settings.data_dir, app_logger)
        prices = PriceRepository(settings.data_dir, app_logger)
        runs = RunRepository(settings.data_dir, app_logger)
        service = build_kamis_collector(settings, catalog, prices, runs)
        # TEMP: Agent-based Naver/Coupang crawling is disabled for main.py startup.
        # Manual agent entrypoints remain available; only automatic startup/daily
        # execution is paused while the research focus is KAMIS wholesale/retail
        # prices versus stock indices and futures.
        #
        # Re-enable later by restoring the online repository/agent source/service
        # construction here and passing online_service to DailyPipeline below.
        online_repository = None
        online_service = None
        coupang_source = None
        naver_source = None

        market_repository = MarketRepository(settings.data_dir, app_logger)
        analytics_repository = AnalyticsRepository(settings.data_dir, app_logger)
        market_client = build_market_collector()
        analytics = AnalyticsService()
        comparison = ComparisonService(
            prices,
            online_repository,
            market_repository,
            analytics,
            target_keys=frozenset(),
            catalog_repository=catalog,
        )
        preferred_item_codes: tuple[str, ...] = ()
        dashboard_bootstrap = DashboardBootstrapService(
            analytics_repository,
            comparison,
            preferred_item_codes,
        )
        analytics_batch = AnalyticsBatchService(
            comparison, analytics, analytics_repository, app_logger
        )
        pipeline = DailyPipeline(
            service,
            None,  # TEMP: do not run Naver/Coupang Agent crawling from main.py
            market_client,
            market_repository,
            runs,
            catalog.entries,
            analytics_batch if settings.analytics_auto_refresh else None,
            app_logger,
            kamis_required_keys=frozenset(),
        )
        kamis_history = KamisHistoryService(
            prices,
            service,
            app_logger,
            timezone=settings.timezone,
            window_days=90,
            catalog_provider=catalog.entries,
            required_keys=frozenset(),
            successful_dates_provider=lambda start, end: runs.successful_covered_dates(
                "kamis_raw",
                start,
                end,
            ),
        )

        def recent_market_range():
            today = datetime.now(ZoneInfo(settings.timezone)).date()
            return today - timedelta(days=89), today - timedelta(days=1)

        recent_market_period = SimpleNamespace(observed_date_range=recent_market_range)
        market_history = MarketHistoryService(
            recent_market_period,
            market_repository,
            market_client,
            runs,
            app_logger,
        )

        def collect_startup_history() -> int:
            total = 0
            try:
                total += kamis_history.collect()
            except Exception as error:  # noqa: BLE001 - independent history source
                app_logger.exception(
                    "startup.kamis_history.failed",
                    "Recent KAMIS history backfill failed; long history will still be attempted",
                    error,
                )
            try:
                total += market_history.collect()
            except Exception as error:  # noqa: BLE001 - independent history source
                app_logger.exception(
                    "startup.market_history.failed",
                    "Market history backfill failed; startup will continue",
                    error,
                )
            try:
                raw_history = run_backfill(
                    settings,
                    workers=4,
                    chunk_days=31,
                )
                total += raw_history.fetched_rows
            except Exception as error:  # noqa: BLE001 - long history is retryable
                app_logger.exception(
                    "startup.kamis_long_history.failed",
                    "20-year raw KAMIS history reconciliation failed; incomplete query-years will retry next startup",
                    error,
                )
            if settings.analytics_auto_refresh:
                analytics_batch.refresh_if_stale(
                    catalog.entries(),
                    f"startup-history-{uuid4().hex}",
                    (prices.path, market_repository.path),
                )
            else:
                app_logger.info(
                    "analytics.refresh.skipped",
                    "Automatic analytics cache refresh is disabled at startup",
                    reason="auto_refresh_disabled",
                )
            return total

        startup_collection = StartupCollectionService(
            pipeline,
            runs,
            settings,
            app_logger,
            history_collector=collect_startup_history,
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
            startup_collection,
            dashboard_bootstrap,
            coupang_agent_source=coupang_source,
            naver_agent_source=naver_source,
        )
