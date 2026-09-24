from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.cli import main
from app.domain.models import CollectionRun, RunStatus


class FakeCollectionService:
    def __init__(self, status: RunStatus) -> None:
        self.status = status
        self.calls: list[tuple[date, date]] = []

    def collect(self, start_date: date, end_date: date) -> CollectionRun:
        self.calls.append((start_date, end_date))
        running = CollectionRun.start("kamis", start_date, end_date)
        return running.finish(
            self.status,
            record_count=0,
            error_count=1 if self.status is RunStatus.FAILED else 0,
        )


def test_collect_command_returns_nonzero_on_failed_run(monkeypatch) -> None:
    service = FakeCollectionService(RunStatus.FAILED)
    monkeypatch.setattr(
        "app.cli.ApplicationContainer.build",
        lambda settings: SimpleNamespace(collection_service=service),
    )

    result = main(["collect-kamis", "--start", "2026-09-24", "--end", "2026-09-24"])

    assert result == 1


def test_backfill_command_uses_requested_years(monkeypatch) -> None:
    service = FakeCollectionService(RunStatus.SUCCESS)
    monkeypatch.setattr(
        "app.cli.ApplicationContainer.build",
        lambda settings: SimpleNamespace(collection_service=service),
    )
    monkeypatch.setattr("app.cli.local_today", lambda timezone: date(2026, 9, 24))

    assert main(["backfill-kamis", "--years", "3"]) == 0
    assert service.calls == [(date(2023, 9, 25), date(2026, 9, 24))]
