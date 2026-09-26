from __future__ import annotations

from dataclasses import dataclass

from app.collectors.coupang import build_coupang_source
from app.collectors.kamis import build_kamis_collector
from app.collectors.market import build_market_collector
from app.collectors.naver import build_naver_source
from app.infrastructure.analytics_repository import AnalyticsRepository
from app.infrastructure.codex_cli import CodexCliRunner
from app.infrastructure.coupang_agent_csv import CoupangAgentCsvParser
from app.infrastructure.coupang_agent_source import CoupangAgentSource
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from app.infrastructure.naver_agent_csv import NaverAgentCsvParser
from app.infrastructure.naver_agent_source import NaverAgentSource
from app.infrastructure.online_repository import OnlinePriceRepository
from app.infrastructure.shopping_sources import PlaywrightShoppingSession
from app.services.analytics import AnalyticsBatchService, AnalyticsService
from app.services.collection_service import KamisCollectionService
from app.services.comparison import ComparisonService
from app.services.daily_pipeline import DailyPipeline
from app.services.dashboard_bootstrap import DashboardBootstrapService
from app.services.market_history import MarketHistoryService
from app.services.online_collection import OnlineCollectionService
from app.services.online_pricing import OnlinePriceCalculator
from app.services.startup_collection import StartupCollectionService
from config.server_config import DEFAULT_ONLINE_TARGET_KEYS, Settings
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
    startup_collection_service: StartupCollectionService | None = None
    dashboard_bootstrap_service: DashboardBootstrapService | None = None
    coupang_agent_source: CoupangAgentSource | None = None
    naver_agent_source: NaverAgentSource | None = None

    @classmethod
    def build(cls, settings: Settings) -> ApplicationContainer:
        catalog = CatalogRepository(settings.data_dir, app_logger)
        prices = PriceRepository(settings.data_dir, app_logger)
        runs = RunRepository(settings.data_dir, app_logger)
        service = build_kamis_collector(settings, catalog, prices, runs)
        online_repository = OnlinePriceRepository(settings.data_dir, app_logger)
        market_repository = MarketRepository(settings.data_dir, app_logger)
        analytics_repository = AnalyticsRepository(settings.data_dir, app_logger)
        shopping_session = PlaywrightShoppingSession(
            user_data_dir=(
                str(settings.shopping_user_data_dir)
                if settings.shopping_user_data_dir
                else None
            ),
            headless=settings.shopping_headless,
            browser_channel=settings.shopping_browser_channel,
            minimum_interval_seconds=settings.shopping_request_interval_seconds,
        )
        coupang_fallback = build_coupang_source(shopping_session)
        naver_fallback = build_naver_source(shopping_session)
        codex_runner = CodexCliRunner(
            settings.project_root,
            settings.codex_executable,
            app_logger,
            sandbox_mode=settings.codex_sandbox_mode,
        )
        coupang_source = (
            CoupangAgentSource(
                settings.project_root,
                settings.coupang_agent_run_dir,
                codex_runner,
                CoupangAgentCsvParser(),
                coupang_fallback,
                app_logger,
                timeout_seconds=settings.coupang_agent_timeout_seconds,
                minimum_delay_ms=round(
                    settings.shopping_request_interval_seconds * 1000
                ),
            )
            if settings.coupang_agent_enabled
            else coupang_fallback
        )
        naver_source = (
            NaverAgentSource(
                settings.project_root,
                settings.naver_agent_run_dir,
                codex_runner,
                NaverAgentCsvParser(),
                naver_fallback,
                app_logger,
                timeout_seconds=settings.coupang_agent_timeout_seconds,
                minimum_delay_ms=round(
                    settings.shopping_request_interval_seconds * 1000
                ),
            )
            if settings.naver_agent_enabled
            else naver_fallback
        )
        sources = [naver_source, coupang_source]
        online_service = OnlineCollectionService(
            sources,
            online_repository,
            OnlinePriceCalculator(),
            app_logger,
            target_keys=set(settings.online_target_keys),
        )
        market_client = build_market_collector()
        analytics = AnalyticsService()
        comparison = ComparisonService(
            prices, online_repository, market_repository, analytics
        )
        configured_targets = set(settings.online_target_keys)
        preferred_item_codes = tuple(
            dict.fromkeys(
                item_code
                for item_code, kind_code in DEFAULT_ONLINE_TARGET_KEYS
                if (item_code, kind_code) in configured_targets
            )
        )
        if not preferred_item_codes:
            preferred_item_codes = tuple(
                sorted({item_code for item_code, _ in configured_targets})
            )
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
            online_service,
            market_client,
            market_repository,
            runs,
            catalog.entries,
            analytics_batch,
            app_logger,
        )
        history = MarketHistoryService(
            prices,
            market_repository,
            market_client,
            runs,
            app_logger,
            on_collected=lambda run_id: analytics_batch.refresh_if_stale(
                catalog.entries(), run_id, (market_repository.path,)
            ),
        )
        startup_collection = StartupCollectionService(
            pipeline,
            runs,
            settings,
            app_logger,
            history_collector=history.collect,
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
            coupang_agent_source=(
                coupang_source
                if isinstance(coupang_source, CoupangAgentSource)
                else None
            ),
            naver_agent_source=(
                naver_source if isinstance(naver_source, NaverAgentSource) else None
            ),
        )
