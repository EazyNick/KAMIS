from datetime import date
from types import SimpleNamespace

from app.services.kamis_history import KamisHistoryService
from log import app_logger


TODAY = date(2026, 9, 28)


class PriceRepo:
    def __init__(self, period):
        self.period = period

    def observed_date_range(self):
        return self.period


class Collector:
    def __init__(self):
        self.calls = []

    def collect(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return SimpleNamespace(record_count=123, status="success")


def build(period):
    collector = Collector()
    service = KamisHistoryService(
        PriceRepo(period),
        collector,
        app_logger,
        window_days=90,
        today_provider=lambda: TODAY,
    )
    return service, collector


def test_backfills_previous_89_days_when_only_today_is_stored() -> None:
    service, collector = build((TODAY, TODAY))

    assert service.collect() == 123
    assert collector.calls == [(date(2026, 7, 1), date(2026, 9, 27))]


def test_backfills_leading_and_trailing_gaps_around_existing_range() -> None:
    service, collector = build((date(2026, 7, 10), date(2026, 9, 20)))

    assert service.collect() == 246
    assert collector.calls == [
        (date(2026, 7, 1), date(2026, 7, 9)),
        (date(2026, 9, 21), date(2026, 9, 27)),
    ]


def test_skips_when_recent_history_window_is_already_covered() -> None:
    service, collector = build((date(2026, 6, 1), TODAY))

    assert service.collect() == 0
    assert collector.calls == []
