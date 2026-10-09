from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from holidays import country_holidays

from app.domain.models import ProductCatalogEntry
from log.logger import StructuredLogger


class PriceHistoryRepositoryProtocol(Protocol):
    def observed_date_range(
        self, *, requested_convert_kg: bool | None = None
    ) -> tuple[date, date] | None: ...

    def observed_dates(
        self,
        start_date: date,
        end_date: date,
        *,
        requested_convert_kg: bool | None = None,
    ) -> set[date]: ...

    def covered_dates(
        self,
        start_date: date,
        end_date: date,
        required_scopes: set[tuple[str, str, str, str]]
        | frozenset[tuple[str, str, str, str]],
        *,
        requested_convert_kg: bool | None = None,
    ) -> set[date]: ...


class KamisCollectorProtocol(Protocol):
    def collect(self, start_date: date, end_date: date) -> Any: ...


class KamisHistoryService:
    """Backfill the recent KAMIS window without replacing stored observations."""

    def __init__(
        self,
        prices: PriceHistoryRepositoryProtocol,
        collector: KamisCollectorProtocol,
        logger: StructuredLogger,
        *,
        timezone: str = "Asia/Seoul",
        window_days: int = 90,
        today_provider: Callable[[], date] | None = None,
        catalog_provider: Callable[[], list[ProductCatalogEntry]] | None = None,
        required_keys: set[tuple[str, str]]
        | frozenset[tuple[str, str]] = frozenset(),
        successful_dates_provider: Callable[[date, date], set[date]] | None = None,
    ) -> None:
        if window_days < 2:
            raise ValueError("window_days must be at least 2")
        self._prices = prices
        self._collector = collector
        self._logger = logger
        self._window_days = window_days
        self._catalog_provider = catalog_provider
        self._required_keys = frozenset(required_keys)
        self._successful_dates_provider = successful_dates_provider
        self._today_provider = today_provider or (
            lambda: datetime.now(ZoneInfo(timezone)).date()
        )

    def collect(self) -> int:
        today = self._today_provider()
        target_start = today - timedelta(days=self._window_days - 1)
        target_end = today - timedelta(days=1)
        period = self._prices.observed_date_range(requested_convert_kg=False)

        ranges: list[tuple[date, date]] = []
        if period is None:
            ranges.append((target_start, target_end))
        else:
            earliest, latest = period
            if earliest > target_start:
                ranges.append((target_start, min(earliest - timedelta(days=1), target_end)))
            if latest < target_end:
                ranges.append((max(latest + timedelta(days=1), target_start), target_end))

            overlap_start = max(earliest, target_start)
            overlap_end = min(latest, target_end)
            if overlap_start <= overlap_end:
                required_scopes = self._required_scopes()
                if required_scopes:
                    stored_dates = self._prices.covered_dates(
                        overlap_start,
                        overlap_end,
                        required_scopes,
                        requested_convert_kg=False,
                    )
                else:
                    stored_dates = self._prices.observed_dates(
                        overlap_start,
                        overlap_end,
                        requested_convert_kg=False,
                    )
                if self._successful_dates_provider is not None:
                    stored_dates |= self._successful_dates_provider(
                        overlap_start,
                        overlap_end,
                    )
                expected_dates = self._expected_dates(overlap_start, overlap_end)
                ranges.extend(self._missing_ranges(expected_dates, stored_dates))

        ranges = [(start, end) for start, end in ranges if start <= end]
        if not ranges:
            self._logger.info(
                "kamis.history.skipped",
                "최근 KAMIS 가격 이력이 이미 저장되어 있습니다.",
                start_date=target_start,
                end_date=target_end,
                reason="history_window_covered",
            )
            return 0

        total = 0
        for start, end in ranges:
            self._logger.info(
                "kamis.history.started",
                "누락된 최근 KAMIS 가격 이력을 조회합니다.",
                start_date=start,
                end_date=end,
            )
            run = self._collector.collect(start, end)
            count = int(getattr(run, "record_count", 0))
            total += count
            self._logger.info(
                "kamis.history.completed",
                "KAMIS 가격 이력 백필을 완료했습니다.",
                start_date=start,
                end_date=end,
                record_count=count,
                status=getattr(run, "status", None),
            )
        return total

    def _required_scopes(self) -> frozenset[tuple[str, str, str, str]]:
        if self._catalog_provider is None:
            return frozenset()

        scopes: set[tuple[str, str, str, str]] = set()
        for entry in self._catalog_provider():
            if (
                self._required_keys
                and (entry.item_code, entry.kind_code) not in self._required_keys
            ):
                continue
            scopes.update(
                (entry.item_code, entry.kind_code, "wholesale", rank_code)
                for rank_code in entry.wholesale_rank_codes
            )
            scopes.update(
                (entry.item_code, entry.kind_code, "retail", rank_code)
                for rank_code in entry.retail_rank_codes
            )
        return frozenset(scopes)

    @staticmethod
    def _expected_dates(start: date, end: date) -> list[date]:
        holidays = country_holidays(
            "KR",
            years=range(start.year, end.year + 1),
        )
        return [
            observed
            for offset in range((end - start).days + 1)
            if (observed := start + timedelta(days=offset)).weekday() < 5
            and observed not in holidays
        ]

    @staticmethod
    def _missing_ranges(
        expected_dates: list[date],
        stored_dates: set[date],
    ) -> list[tuple[date, date]]:
        ranges: list[tuple[date, date]] = []
        range_start: date | None = None
        range_end: date | None = None

        for observed in expected_dates:
            if observed in stored_dates:
                if range_start is not None and range_end is not None:
                    ranges.append((range_start, range_end))
                    range_start = None
                    range_end = None
                continue
            if range_start is None:
                range_start = observed
            range_end = observed

        if range_start is not None and range_end is not None:
            ranges.append((range_start, range_end))
        return ranges
