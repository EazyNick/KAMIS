from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import argparse
from collections.abc import Sequence
from datetime import date

from app.collectors.shopping import local_today, parse_target
from app.core.container import ApplicationContainer
from app.domain.models import CollectionError, CollectionRun, RunStatus
from app.services.online_collection import (
    OnlineCollectionResult,
    OnlineCollectionService,
)
from app.services.online_pricing import OnlinePriceCalculator
from config.server_config import Settings
from log import app_logger


def collect_coupang_agent(
    container: ApplicationContainer,
    observed_date: date,
    *,
    target: tuple[str, str] | None = None,
) -> OnlineCollectionResult:
    source = container.coupang_agent_source
    repository = container.online_repository
    if source is None or repository is None or not container.settings.coupang_agent_enabled:
        raise RuntimeError("Coupang agent collection is unavailable")
    target_keys = {target} if target else set(container.settings.online_target_keys)
    service = OnlineCollectionService(
        [source],
        repository,
        OnlinePriceCalculator(),
        app_logger,
        target_keys=target_keys,
    )
    run = CollectionRun.start("coupang_agent", observed_date, observed_date)
    container.run_repository.save(run)
    try:
        result = service.collect(
            container.catalog_repository.entries(),
            observed_date,
            run.run_id,
            include_combined=False,
        )
        errors = tuple(
            CollectionError("coupang_agent", "SourceFailure", message)
            for message in result.errors
        )
        status = RunStatus.PARTIAL_FAILURE if errors else RunStatus.SUCCESS
        container.run_repository.save(
            run.finish(
                status,
                record_count=result.offer_count,
                error_count=len(errors),
                errors=errors,
            )
        )
        return result
    except Exception as error:
        container.run_repository.save(
            run.finish(
                RunStatus.FAILED,
                record_count=0,
                error_count=1,
                errors=(
                    CollectionError(
                        "coupang_agent", type(error).__name__, str(error)
                    ),
                ),
            )
        )
        raise


def run_coupang_agent(
    observed_date: date,
    *,
    target: tuple[str, str] | None = None,
) -> OnlineCollectionResult:
    settings = Settings.from_env()
    return collect_coupang_agent(
        ApplicationContainer.build(settings), observed_date, target=target
    )


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(description="Collect Coupang through Codex agent")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--item", type=parse_target)
    arguments = parser.parse_args(argv)
    observed_date = arguments.date or local_today(settings.timezone)
    result = run_coupang_agent(observed_date, target=arguments.item)
    return 1 if result.error_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
