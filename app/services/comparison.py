from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd

from app.infrastructure.csv_repository import PriceFilters
from app.services.analytics import AnalysisMode, AnalyticsService


class PriceRepositoryProtocol(Protocol):
    def search(self, filters: PriceFilters | None = None) -> list[dict[str, Any]]: ...


class OnlineRepositoryProtocol(Protocol):
    def search_summaries(self, **kwargs: Any) -> list[dict[str, Any]]: ...


class MarketRepositoryProtocol(Protocol):
    def search(self, **kwargs: Any) -> list[dict[str, Any]]: ...


class ComparisonService:
    core_series = (
        "kamis_wholesale",
        "kamis_retail",
        "online_naver",
        "online_coupang",
        "online_combined",
        "kospi",
        "kosdaq",
        "sp500",
        "nasdaq",
        "dow_jones",
    )

    def __init__(
        self,
        price_repository: PriceRepositoryProtocol,
        online_repository: OnlineRepositoryProtocol,
        market_repository: MarketRepositoryProtocol,
        analytics: AnalyticsService,
    ) -> None:
        self._prices = price_repository
        self._online = online_repository
        self._market = market_repository
        self._analytics = analytics

    def build_frame(
        self, item_code: str, start_date: date | None, end_date: date | None
    ) -> pd.DataFrame:
        price_rows = self._prices.search(
            PriceFilters(item_code=item_code, start_date=start_date, end_date=end_date)
        )
        kamis_dates = sorted(
            {
                pd.Timestamp(row["observed_date"])
                for row in price_rows
                if pd.Timestamp(row["observed_date"]).weekday() < 5
            }
        )
        frame = pd.DataFrame(index=pd.DatetimeIndex(kamis_dates))
        if price_rows:
            prices = pd.DataFrame(price_rows)
            prices["observed_date"] = pd.to_datetime(prices["observed_date"])
            prices["price_krw"] = pd.to_numeric(prices["price_krw"], errors="coerce")
            grouped = prices.groupby(["observed_date", "price_type"])[
                "price_krw"
            ].mean()
            for price_type in ("wholesale", "retail"):
                if price_type in grouped.index.get_level_values("price_type"):
                    frame[f"kamis_{price_type}"] = grouped.xs(
                        price_type, level="price_type"
                    )
        online_rows = self._online.search_summaries(item_code=item_code)
        if online_rows:
            online = pd.DataFrame(online_rows)
            online["observed_date"] = pd.to_datetime(online["observed_date"])
            online["average_unit_price"] = pd.to_numeric(
                online["average_unit_price"], errors="coerce"
            )
            for platform, values in online.groupby("platform"):
                series = values.groupby("observed_date")["average_unit_price"].mean()
                frame[f"online_{platform}"] = series
        market_rows = self._market.search(start_date=start_date, end_date=end_date)
        if market_rows:
            market = pd.DataFrame(market_rows)
            market["observed_date"] = pd.to_datetime(market["observed_date"])
            market["close"] = pd.to_numeric(market["close"], errors="coerce")
            for series_id, values in market.groupby("series_id"):
                frame[str(series_id)] = values.groupby("observed_date")["close"].mean()
        return frame.sort_index()

    def chart(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
        mode: AnalysisMode = "base100",
    ) -> dict[str, Any]:
        frame = self._analytics.transform(
            self.build_frame(item_code, start_date, end_date), mode
        )
        all_columns = list(dict.fromkeys([*self.core_series, *frame.columns]))
        series: dict[str, list[float | None]] = {}
        for column in all_columns:
            values = (
                frame[column]
                if column in frame
                else pd.Series(np.nan, index=frame.index)
            )
            series[column] = [
                None if pd.isna(value) else float(value) for value in values.tolist()
            ]
        return {
            "item_code": item_code,
            "mode": mode,
            "dates": [timestamp.date().isoformat() for timestamp in frame.index],
            "series": series,
        }

    def correlations(
        self,
        item_code: str,
        target_series: str,
        start_date: date | None,
        end_date: date | None,
        mode: AnalysisMode = "return_1d",
    ) -> list[dict[str, Any]]:
        frame = self._analytics.transform(
            self.build_frame(item_code, start_date, end_date), mode
        )
        return self._analytics.correlations(frame, target_series)
