from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from holidays import financial_holidays

from app.infrastructure.csv_repository import _AtomicCsvRepository
from log.logger import StructuredLogger

DEFAULT_MARKET_SYMBOLS = {
    "kospi": "^KS11",
    "kosdaq": "^KQ11",
    "sp500": "^GSPC",
    "nasdaq": "^IXIC",
    "dow_jones": "^DJI",
    "usd_krw": "KRW=X",
    "corn_futures": "ZC=F",
    "wheat_futures": "ZW=F",
    "soybean_futures": "ZS=F",
    "rough_rice_futures": "ZR=F",
    "coffee_futures": "KC=F",
    "sugar_futures": "SB=F",
    "cotton_futures": "CT=F",
    "orange_juice_futures": "OJ=F",
}


@dataclass(frozen=True, slots=True)
class MarketObservation:
    series_id: str
    ticker: str
    observed_date: date
    close: float
    currency: str
    unit: str
    collected_at: datetime

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["observed_date"] = self.observed_date.isoformat()
        row["collected_at"] = self.collected_at.isoformat()
        return row


class MarketDataClient:
    def __init__(
        self,
        downloader: Callable[..., pd.DataFrame] | None,
        logger: StructuredLogger,
        *,
        symbols: dict[str, str] | None = None,
    ) -> None:
        self._download = downloader or yf.download
        self._logger = logger
        self.symbols = symbols or dict(DEFAULT_MARKET_SYMBOLS)

    def fetch(
        self, start_date: date, end_date: date, *, series_ids: set[str] | None = None
    ) -> list[MarketObservation]:
        started = perf_counter()
        selected = {
            series_id: ticker
            for series_id, ticker in self.symbols.items()
            if series_ids is None or series_id in series_ids
        }
        tickers = list(selected.values())
        self._logger.info(  # noqa: PLE1205 - structured logger
            "market.collection.started",
            "Market data collection started",
            source="yfinance",
            series_count=len(selected),
            series_ids=",".join(sorted(selected)),
            tickers=",".join(tickers),
            requested_start=start_date,
            requested_end=end_date,
        )
        try:
            korean_tickers = [
                ticker for ticker in tickers if ticker in {"^KS11", "^KQ11"}
            ]
            closed_dates = (
                self._krx_closed_dates(start_date, end_date) if korean_tickers else {}
            )
            if closed_dates:
                tickers = [ticker for ticker in tickers if ticker not in korean_tickers]
                for observed_date, holiday_name in closed_dates.items():
                    self._logger.info(  # noqa: PLE1205 - custom structured logger
                        "market.collection.closed",
                        "국내 증시 휴장일로 가격 데이터가 없는 정상 상황입니다. 조회를 건너뜁니다.",
                        source="yfinance",
                        market="XKRX",
                        observed_date=observed_date,
                        holiday_name=holiday_name,
                        tickers=",".join(korean_tickers),
                        reason="market_closed",
                    )
            rows = []
            if tickers:
                frame = self._download(
                    tickers=tickers,
                    start=start_date.isoformat(),
                    end=(end_date + timedelta(days=1)).isoformat(),
                    auto_adjust=False,
                    progress=False,
                    group_by="ticker",
                )
                rows = [
                    row
                    for row in self._normalize(
                        frame,
                        start_date,
                        end_date,
                        {
                            key: value
                            for key, value in selected.items()
                            if value in tickers
                        },
                    )
                    if row.ticker in tickers
                ]
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "market.collection.succeeded",
                "Market data collection completed",
                source="yfinance",
                series_count=len(selected),
                series_ids=",".join(sorted(selected)),
                requested_start=start_date,
                requested_end=end_date,
                skipped_series_count=len(korean_tickers) if closed_dates else 0,
                record_count=len(rows),
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return rows
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205 - custom structured logger
                "market.collection.failed",
                "Market data collection failed",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                source="yfinance",
                series_count=len(self.symbols),
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise

    @staticmethod
    def _krx_closed_dates(start_date: date, end_date: date) -> dict[date, str]:
        """Return closure reasons only when the entire requested range is closed."""
        calendar = financial_holidays("XKRX", language="ko")
        closed: dict[date, str] = {}
        for offset in range((end_date - start_date).days + 1):
            observed_date = start_date + timedelta(days=offset)
            holiday_name = calendar.get(observed_date)
            if holiday_name:
                closed[observed_date] = holiday_name
            elif observed_date.weekday() >= 5:
                closed[observed_date] = "주말 휴장"
            else:
                return {}
        return closed

    def _normalize(
        self,
        frame: pd.DataFrame,
        start_date: date,
        end_date: date,
        symbols: dict[str, str] | None = None,
    ) -> list[MarketObservation]:
        collected_at = datetime.now(ZoneInfo("Asia/Seoul"))
        result: list[MarketObservation] = []
        selected = self.symbols if symbols is None else symbols
        for series_id, ticker in selected.items():
            values = self._close_series(frame, ticker)
            if (
                values is None
                and len(selected) == 1
                and not isinstance(frame.columns, pd.MultiIndex)
                and "Close" in frame
            ):
                values = frame["Close"]
            if values is None:
                continue
            for timestamp, value in values.dropna().items():
                observed = pd.Timestamp(timestamp).date()
                if observed < start_date or observed > end_date:
                    continue
                currency, unit = self._metadata(series_id)
                result.append(
                    MarketObservation(
                        series_id,
                        ticker,
                        observed,
                        float(value),
                        currency,
                        unit,
                        collected_at,
                    )
                )
        return sorted(result, key=lambda row: (row.observed_date, row.series_id))

    @staticmethod
    def _close_series(frame: pd.DataFrame, ticker: str) -> pd.Series | None:
        if isinstance(frame.columns, pd.MultiIndex):
            for key in ((ticker, "Close"), ("Close", ticker)):
                if key in frame.columns:
                    return frame[key]
        if ticker in frame.columns:
            return frame[ticker]
        return None

    @staticmethod
    def _metadata(series_id: str) -> tuple[str, str]:
        if series_id == "usd_krw":
            return "KRW", "KRW per USD"
        if series_id.endswith("_futures"):
            return "USD", "contract quote"
        return "index", "index points"


class MarketRepository:
    def __init__(self, data_dir: Path, logger: StructuredLogger) -> None:
        self._storage = _AtomicCsvRepository(
            data_dir / "normalized" / "market_observations.csv", logger
        )

    @property
    def path(self) -> Path:
        return self._storage.path

    def upsert(self, rows: list[MarketObservation], run_id: str) -> None:
        with self._storage._lock:
            existing = self._storage._read()
            indexed: dict[tuple[str, str], dict[str, Any]] = {
                (row["series_id"], row["observed_date"]): row for row in existing
            }
            for observation in rows:
                row = observation.to_dict()
                indexed[(row["series_id"], row["observed_date"])] = row
            ordered = sorted(
                indexed.values(),
                key=lambda row: (row["observed_date"], row["series_id"]),
            )
            self._storage._atomic_write(ordered, run_id)

    def has_collected_date(self, observed_date: date) -> bool:
        expected = observed_date.isoformat()
        return any(
            row.get("observed_date") == expected for row in self._storage._read()
        )

    def search(
        self,
        *,
        series_id: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in self._storage._read():
            observed = date.fromisoformat(row["observed_date"])
            if series_id and row["series_id"] != series_id:
                continue
            if start_date and observed < start_date:
                continue
            if end_date and observed > end_date:
                continue
            converted: dict[str, Any] = dict(row)
            converted["close"] = float(row["close"])
            result.append(converted)
        return result
