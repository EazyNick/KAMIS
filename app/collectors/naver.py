from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections.abc import Sequence
from datetime import date

from app.collectors.shopping import (
    build_browser_session,
    collect_platform,
    local_today,
    parse_target,
)
from app.infrastructure.shopping_sources import (
    NaverShoppingSource,
    PlaywrightShoppingSession,
)
from app.services.online_collection import OnlineCollectionResult
from config.server_config import Settings
from log import app_logger
from log.logger import StructuredLogger


def build_naver_source(
    session: PlaywrightShoppingSession, logger: StructuredLogger = app_logger
) -> NaverShoppingSource:
    return NaverShoppingSource(session, logger)


def run_naver(
    observed_date: date,
    *,
    target: tuple[str, str] | None = None,
    headful: bool = False,
) -> OnlineCollectionResult:
    settings = Settings.from_env()
    session = build_browser_session(settings, headful=headful)
    return collect_platform(
        build_naver_source(session),
        session,
        settings,
        observed_date,
        target=target,
    )


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Collect Naver shopping prices")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--item", type=parse_target)
    parser.add_argument("--headful", action="store_true")
    arguments = parser.parse_args(argv)
    observed_date = arguments.date or local_today(settings.timezone)
    result = run_naver(observed_date, target=arguments.item, headful=arguments.headful)
    return 1 if result.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
