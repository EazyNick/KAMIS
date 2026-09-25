from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.domain.models import CollectionError, CollectionRun, RunStatus
from app.infrastructure.csv_repository import CatalogRepository, RunRepository
from app.infrastructure.online_repository import OnlinePriceRepository
from app.infrastructure.shopping_sources import (
    HtmlShoppingSource,
    PlaywrightShoppingSession,
)
from app.services.online_collection import (
    OnlineCollectionResult,
    OnlineCollectionService,
)
from app.services.online_pricing import OnlinePriceCalculator
from config.server_config import Settings
from log import app_logger


def parse_target(value: str) -> tuple[str, str]:
    parts = tuple(part.strip() for part in value.split(":"))
    if len(parts) != 2 or any(not part.isdigit() for part in parts):
        raise ValueError("target must use numeric item_code:kind_code format")
    return parts[0], parts[1]


def build_browser_session(
    settings: Settings, *, headful: bool = False
) -> PlaywrightShoppingSession:
    return PlaywrightShoppingSession(
        user_data_dir=(
            str(settings.shopping_user_data_dir)
            if settings.shopping_user_data_dir
            else None
        ),
        headless=False if headful else settings.shopping_headless,
        browser_channel=settings.shopping_browser_channel,
        minimum_interval_seconds=settings.shopping_request_interval_seconds,
    )


def collect_platform(
    source: HtmlShoppingSource,
    session: PlaywrightShoppingSession,
    settings: Settings,
    observed_date: date,
    *,
    target: tuple[str, str] | None = None,
) -> OnlineCollectionResult:
    catalog_repository = CatalogRepository(settings.data_dir, app_logger)
    online_repository = OnlinePriceRepository(settings.data_dir, app_logger)
    run_repository = RunRepository(settings.data_dir, app_logger)
    target_keys = {target} if target else set(settings.online_target_keys)
    service = OnlineCollectionService(
        [source],
        online_repository,
        OnlinePriceCalculator(),
        app_logger,
        target_keys=target_keys,
    )
    run = CollectionRun.start(source.platform, observed_date, observed_date)
    run_repository.save(run)
    try:
        result = service.collect(
            catalog_repository.entries(),
            observed_date,
            run.run_id,
            include_combined=False,
        )
        errors = tuple(
            CollectionError(source.platform, "SourceFailure", message)
            for message in result.errors
        )
        status = RunStatus.PARTIAL_FAILURE if errors else RunStatus.SUCCESS
        run_repository.save(
            run.finish(
                status,
                record_count=result.offer_count,
                error_count=len(errors),
                errors=errors,
            )
        )
        return result
    except Exception as error:
        run_repository.save(
            run.finish(
                RunStatus.FAILED,
                record_count=0,
                error_count=1,
                errors=(
                    CollectionError(source.platform, type(error).__name__, str(error)),
                ),
            )
        )
        raise
    finally:
        session.close()


def local_today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()
