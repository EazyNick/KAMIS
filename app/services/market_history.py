from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from uuid import uuid4

from holidays import financial_holidays

from app.domain.models import CollectionError, CollectionRun, RunStatus
from app.infrastructure.csv_repository import PriceRepository, RunRepository
from app.infrastructure.market_data import MarketDataClient, MarketRepository
from log.logger import StructuredLogger


class MarketHistoryService:
    """Fill missing market observations over the stored KAMIS date range."""

    def __init__(
        self,
        prices: PriceRepository,
        market: MarketRepository,
        client: MarketDataClient,
        runs: RunRepository,
        logger: StructuredLogger,
        *,
        on_collected: Callable[[str], object] | None = None,
    ) -> None:
        self._prices = prices
        self._market = market
        self._client = client
        self._runs = runs
        self._logger = logger
        self._on_collected = on_collected

    def collect(self) -> int:
        period = self._prices.observed_date_range()
        if period is None:
            self._logger.info(  # noqa: PLE1205 - structured logger
                "market.history.skipped",
                "KAMIS 저장 데이터가 없어 과거 시장 수집을 건너뜁니다.",
                reason="no_kamis_history",
            )
            return 0
        start, end = period
        existing: dict[str, set[date]] = {}
        for row in self._market.search(start_date=start, end_date=end):
            if row.get("ticker") == self._client.symbols.get(row["series_id"]):
                existing.setdefault(row["series_id"], set()).add(
                    date.fromisoformat(row["observed_date"])
                )
        missing = {
            series: self._expected_dates(ticker, start, end)
            - existing.get(series, set())
            for series, ticker in self._client.symbols.items()
        }
        missing = {series: dates for series, dates in missing.items() if dates}
        if not missing:
            self._logger.info(  # noqa: PLE1205 - structured logger
                "market.history.skipped",
                "KAMIS 기간의 시장 데이터가 이미 저장되어 있습니다.",
                start_date=start,
                end_date=end,
                reason="already_collected",
            )
            self._refresh_analytics(
                f"market-history-check-{uuid4().hex}",
                reason="market_already_collected",
            )
            return 0

        run = CollectionRun.start("market_history", start, end)
        self._runs.save(run)
        self._logger.info(  # noqa: PLE1205 - structured logger
            "market.history.started",
            "KAMIS 기간에 맞춰 누락된 과거 시장 데이터를 수집합니다.",
            run_id=run.run_id,
            start_date=start,
            end_date=end,
            series_count=len(missing),
        )
        count = 0
        errors: list[CollectionError] = []
        for series, dates in missing.items():
            self._logger.debug(  # noqa: PLE1205 - structured logger
                "market.history.series.started",
                "Collecting missing market series",
                run_id=run.run_id,
                series_id=series,
                start_date=min(dates),
                end_date=max(dates),
                missing_date_count=len(dates),
            )
            try:
                rows = self._client.fetch(min(dates), max(dates), series_ids={series})
                self._market.upsert(rows, run.run_id)
                count += len(rows)
                self._logger.debug(  # noqa: PLE1205 - structured logger
                    "market.history.series.completed",
                    "Missing market series collection completed",
                    run_id=run.run_id,
                    series_id=series,
                    record_count=len(rows),
                )
                remaining = dates - {row.observed_date for row in rows}
                if remaining:
                    errors.append(
                        CollectionError(
                            series,
                            "MissingMarketData",
                            f"{len(remaining)} dates still missing",
                        )
                    )
                    self._logger.warning(  # noqa: PLE1205 - structured logger
                        "market.history.incomplete",
                        "조회 후에도 없는 시장 데이터는 다음 시작 시 다시 확인합니다.",
                        run_id=run.run_id,
                        series_id=series,
                        missing_count=len(remaining),
                    )
            except Exception as error:
                errors.append(CollectionError(series, type(error).__name__, str(error)))
                self._logger.exception(  # noqa: PLE1205 - structured logger
                    "market.history.series.failed",
                    "과거 시장 데이터 조회 실패; 다른 지수는 계속 수집합니다.",
                    error,  # noqa: TRY401 - structured error metadata
                    run_id=run.run_id,
                    series_id=series,
                )
        status = RunStatus.SUCCESS
        if errors:
            status = RunStatus.PARTIAL_FAILURE if count else RunStatus.FAILED
        self._runs.save(
            run.finish(
                status,
                record_count=count,
                error_count=len(errors),
                errors=tuple(errors),
            )
        )
        self._logger.info(  # noqa: PLE1205 - structured logger
            "market.history.completed",
            "과거 시장 데이터 수집을 마쳤습니다.",
            run_id=run.run_id,
            status=status,
            record_count=count,
            error_count=len(errors),
        )
        self._refresh_analytics(run.run_id, reason="market_history_collected")
        return count

    def _refresh_analytics(self, run_id: str, *, reason: str) -> None:
        if self._on_collected is None:
            return
        self._logger.info(  # noqa: PLE1205 - structured logger
            "market.history.analytics_check.started",
            "Checking whether analytics must be refreshed after market history",
            run_id=run_id,
            reason=reason,
        )
        try:
            refreshed_rows = self._on_collected(run_id)
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205 - structured logger
                "market.history.analytics_check.failed",
                "Analytics refresh after market history failed",
                error,  # noqa: TRY401 - structured error metadata
                run_id=run_id,
                reason=reason,
            )
            raise
        self._logger.info(  # noqa: PLE1205 - structured logger
            "market.history.analytics_check.completed",
            "Analytics freshness check after market history completed",
            run_id=run_id,
            reason=reason,
            record_count=refreshed_rows if isinstance(refreshed_rows, int) else 0,
        )

    @staticmethod
    def _expected_dates(ticker: str, start: date, end: date) -> set[date]:
        exchange = None
        if ticker in {"^KS11", "^KQ11"}:
            exchange = "XKRX"
        elif ticker in {"^GSPC", "^IXIC", "^DJI"}:
            exchange = "XNYS"
        calendar = financial_holidays(exchange) if exchange else {}
        # FX/futures have distinct sessions. Keep missing weekdays retryable rather
        # than declaring their missing quotes successful based on a stock calendar.
        return {
            observed
            for offset in range((end - start).days + 1)
            if (observed := start + timedelta(days=offset)).weekday() < 5
            and observed not in calendar
        }
