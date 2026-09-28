from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from log.logger import StructuredLogger


class PriceHistoryRepositoryProtocol(Protocol):
    def observed_date_range(self) -> tuple[date, date] | None: ...


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
    ) -> None:
        if window_days < 2:
            raise ValueError("window_days must be at least 2")
        self._prices = prices
        self._collector = collector
        self._logger = logger
        self._window_days = window_days
        self._today_provider = today_provider or (
            lambda: datetime.now(ZoneInfo(timezone)).date()
        )

    def collect(self) -> int:
        today = self._today_provider()
        target_start = today - timedelta(days=self._window_days - 1)
        target_end = today - timedelta(days=1)
        period = self._prices.observed_date_range()

        ranges: list[tuple[date, date]] = []
        if period is None:
            ranges.append((target_start, target_end))
        else:
            earliest, latest = period
            if earliest > target_start:
                ranges.append((target_start, min(earliest - timedelta(days=1), target_end)))
            if latest < target_end:
                ranges.append((max(latest + timedelta(days=1), target_start), target_end))

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
