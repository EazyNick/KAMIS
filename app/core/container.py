from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.collectors.kamis import build_kamis_collector
from app.collectors.market import build_market_collector
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
from app.services.analytics import AnalyticsBatchService, AnalyticsService
from app.services.collection_service import KamisCollectionService
from app.services.comparison import ComparisonService
from app.services.daily_pipeline import DailyPipeline
from app.services.dashboard_bootstrap import DashboardBootstrapService
from app.services.kamis_history import KamisHistoryService
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
                app_logger,
                timeout_seconds=settings.coupang_agent_timeout_seconds,
                minimum_delay_ms=round(
                    settings.shopping_request_interval_seconds * 1000
                ),
            )
            if settings.coupang_agent_enabled
            else None
        )
        naver_source = (
            NaverAgentSource(
                settings.project_root,
                settings.naver_agent_run_dir,
                codex_runner,
                NaverAgentCsvParser(),
                app_logger,
                timeout_seconds=settings.coupang_agent_timeout_seconds,
                minimum_delay_ms=round(
                    settings.shopping_request_interval_seconds * 1000
                ),
            )
            if settings.naver_agent_enabled
            else None
        )
        sources = [
            source for source in (naver_source, coupang_source) if source is not None
        ]
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
            prices,
            online_repository,
            market_repository,
            analytics,
            target_keys=settings.online_target_keys,
            catalog_repository=catalog,
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
        kamis_history = KamisHistoryService(
            prices,
            service,
            app_logger,
            timezone=settings.timezone,
            window_days=90,
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
                    "KAMIS history backfill failed; market history will continue",
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
            analytics_batch.refresh_if_stale(
                catalog.entries(),
                f"startup-history-{uuid4().hex}",
                (prices.path, market_repository.path),
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
