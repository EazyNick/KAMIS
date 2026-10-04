from datetime import date
from types import SimpleNamespace

from app.services.kamis_history import KamisHistoryService
from log import app_logger


TODAY = date(2026, 9, 28)


class PriceRepo:
    def __init__(self, period, stored_dates=None):
        self.period = period
        self.stored_dates = stored_dates

    def observed_date_range(self):
        return self.period

    def observed_dates(self, start_date, end_date):
        if self.stored_dates is not None:
            return {
                observed
                for observed in self.stored_dates
                if start_date <= observed <= end_date
            }
        if self.period is None:
            return set()
        earliest, latest = self.period
        return {
            date.fromordinal(day)
            for day in range(earliest.toordinal(), latest.toordinal() + 1)
            if start_date <= date.fromordinal(day) <= end_date
        }


class Collector:
    def __init__(self):
        self.calls = []

    def collect(self, start_date, end_date):
        self.calls.append((start_date, end_date))
        return SimpleNamespace(record_count=123, status="success")


def build(period, stored_dates=None):
    collector = Collector()
    service = KamisHistoryService(
        PriceRepo(period, stored_dates),
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


def test_backfills_internal_business_day_gap() -> None:
    stored_dates = {
        date(2026, 9, 21),
        date(2026, 9, 22),
        date(2026, 9, 24),
        date(2026, 9, 25),
    }
    collector = Collector()
    service = KamisHistoryService(
        PriceRepo((date(2026, 9, 21), date(2026, 9, 25)), stored_dates),
        collector,
        app_logger,
        window_days=6,
        today_provider=lambda: date(2026, 9, 26),
    )

    assert service.collect() == 123
    assert collector.calls == [(date(2026, 9, 23), date(2026, 9, 23))]


def test_internal_gap_detection_ignores_weekends() -> None:
    stored_dates = {
        date(2026, 9, 25),
        date(2026, 9, 28),
    }
    collector = Collector()
    service = KamisHistoryService(
        PriceRepo((date(2026, 9, 25), date(2026, 9, 28)), stored_dates),
        collector,
        app_logger,
        window_days=5,
        today_provider=lambda: date(2026, 9, 29),
    )

    assert service.collect() == 0
    assert collector.calls == []
