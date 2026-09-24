from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from time import perf_counter
from zoneinfo import ZoneInfo

import uvicorn
from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.container import ApplicationContainer
from app.domain.models import RunStatus
from app.services.scheduler import DailyScheduler
from config.server_config import Settings
from log import app_logger


def local_today(timezone: str) -> date:
    return datetime.now(ZoneInfo(timezone)).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kamis-dashboard")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    collect = commands.add_parser("collect-kamis")
    collect.add_argument("--start", type=date.fromisoformat, required=True)
    collect.add_argument("--end", type=date.fromisoformat, required=True)
    backfill = commands.add_parser("backfill-kamis")
    backfill.add_argument("--years", type=int, default=3)
    commands.add_parser("schedule")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    settings = Settings.from_env()
    started = perf_counter()
    app_logger.info(
        "cli.command.started",
        "CLI command started",
        command=arguments.command,
    )
    try:
        if arguments.command == "serve":
            uvicorn.run(
                "app.main:app", host=arguments.host, port=arguments.port, reload=False
            )
            result = 0
        else:
            container = ApplicationContainer.build(settings)
            if arguments.command == "collect-kamis":
                if arguments.start > arguments.end:
                    raise ValueError("start date must not exceed end date")
                run = container.collection_service.collect(
                    arguments.start, arguments.end
                )
                result = 1 if run.status is RunStatus.FAILED else 0
            elif arguments.command == "backfill-kamis":
                if arguments.years < 1:
                    raise ValueError("years must be positive")
                end_date = local_today(settings.timezone)
                start_date = end_date - timedelta(days=arguments.years * 365)
                run = container.collection_service.collect(start_date, end_date)
                result = 1 if run.status is RunStatus.FAILED else 0
            else:
                backend = BlockingScheduler(timezone=settings.timezone)
                DailyScheduler(
                    backend, container.collection_service, settings, app_logger
                ).start()
                result = 0
        app_logger.info(
            "cli.command.completed",
            "CLI command completed",
            command=arguments.command,
            exit_code=result,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return result
    except Exception as error:  # noqa: BLE001 - CLI is the process error boundary
        app_logger.exception(
            "cli.command.failed",
            "CLI command failed",
            error,
            command=arguments.command,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
