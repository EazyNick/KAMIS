from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.services.scheduler import DailyScheduler
from config.server_config import Settings
from log import app_logger


@dataclass
class FakeJob:
    id: str
    max_instances: int
    trigger: str


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, FakeJob] = {}
        self.started_paused: bool | None = None
        self.stopped = False

    def add_job(self, function: Any, trigger: str, **kwargs: Any) -> FakeJob:
        job = FakeJob(kwargs["id"], kwargs["max_instances"], trigger)
        self.jobs[job.id] = job
        return job

    def start(self, paused: bool = False) -> None:
        self.started_paused = paused

    def shutdown(self, wait: bool = True) -> None:
        self.stopped = wait

    def get_job(self, job_id: str) -> FakeJob | None:
        return self.jobs.get(job_id)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []

    def collect(self, start_date: date, end_date: date) -> None:
        self.calls.append((start_date, end_date))


def test_scheduler_registers_single_daily_job() -> None:
    backend = FakeScheduler()
    service = FakeService()
    scheduler = DailyScheduler(backend, service, Settings.from_env(), app_logger)

    scheduler.start(paused=True)

    job = backend.get_job("kamis-daily-collection")
    assert job is not None
    assert job.max_instances == 1
    assert job.trigger == "cron"
    assert backend.started_paused is True


def test_scheduler_shutdown_waits_for_collection() -> None:
    backend = FakeScheduler()
    scheduler = DailyScheduler(backend, FakeService(), Settings.from_env(), app_logger)
    scheduler.shutdown()
    assert backend.stopped is True
