from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

import numpy as np
import pandas as pd
from holidays import financial_holidays

from app.infrastructure.csv_repository import PriceFilters
from app.services.analytics import AnalysisMode, AnalyticsService


class PriceRepositoryProtocol(Protocol):
    def search(self, filters: PriceFilters | None = None) -> list[dict[str, Any]]: ...


class OnlineRepositoryProtocol(Protocol):
    def search_summaries(self, **kwargs: Any) -> list[dict[str, Any]]: ...


class MarketRepositoryProtocol(Protocol):
    def search(self, **kwargs: Any) -> list[dict[str, Any]]: ...


MARKET_EXCHANGES = {
    "kospi": "XKRX",
    "kosdaq": "XKRX",
    "sp500": "XNYS",
    "nasdaq": "XNYS",
    "dow_jones": "XNYS",
    # The commodity feeds follow US futures sessions, but the provider can
    # publish values on partial-session days.  Only use full US market
    # closures as a conservative proxy so genuine provider gaps stay empty.
    "corn_futures": "XNYS",
    "wheat_futures": "XNYS",
    "soybean_futures": "XNYS",
    "rough_rice_futures": "XNYS",
    "coffee_futures": "XNYS",
    "sugar_futures": "XNYS",
    "cotton_futures": "XNYS",
    "orange_juice_futures": "XNYS",
}


def fill_exchange_holidays(frame: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill market values only on dates their exchange was closed."""
    result = frame.copy()
    for series_id, exchange in MARKET_EXCHANGES.items():
        if series_id not in result:
            continue
        calendar = financial_holidays(exchange)
        holiday_mask = pd.Series(
            [timestamp.date() in calendar for timestamp in result.index],
            index=result.index,
        )
        fillable = result[series_id].isna() & holiday_mask
        if fillable.any():
            previous = result[series_id].ffill()
            result.loc[fillable, series_id] = previous.loc[fillable]
    return result


def chart_from_frame(
    item_code: str,
    mode: AnalysisMode,
    frame: pd.DataFrame,
    core_series: tuple[str, ...],
    raw_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    all_columns = list(dict.fromkeys([*core_series, *frame.columns]))
    raw_source = frame if mode == "raw" and raw_frame is None else raw_frame

    def serialize(source: pd.DataFrame | None) -> dict[str, list[float | None]]:
        aligned = (
            source.reindex(frame.index)
            if source is not None
            else pd.DataFrame(index=frame.index)
        )
        result: dict[str, list[float | None]] = {}
        for column in all_columns:
            values = (
                aligned[column]
                if column in aligned
                else pd.Series(np.nan, index=frame.index)
            )
            result[column] = [
                None if pd.isna(value) else float(value)
                for value in values.tolist()
            ]
        return result

    return {
        "item_code": item_code,
        "mode": mode,
        "dates": [timestamp.date().isoformat() for timestamp in frame.index],
        "series": serialize(frame),
        "raw_series": serialize(raw_source),
    }


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
        return fill_exchange_holidays(frame.sort_index())

    def chart(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
        mode: AnalysisMode = "base100",
    ) -> dict[str, Any]:
        raw_frame = self.build_frame(item_code, start_date, end_date)
        frame = self._analytics.transform(raw_frame, mode)
        return chart_from_frame(
            item_code, mode, frame, self.core_series, raw_frame=raw_frame
        )

    def dashboard_defaults(self) -> dict[str, str | None]:
        price_rows = self._prices.search(PriceFilters())
        dates_by_item: dict[str, list[date]] = {}
        for row in price_rows:
            item_code = str(row.get("item_code", ""))
            observed_date = row.get("observed_date")
            if not item_code or not observed_date:
                continue
            dates_by_item.setdefault(item_code, []).append(
                date.fromisoformat(str(observed_date))
            )

        if not dates_by_item:
            return {
                "item_code": None,
                "start_date": None,
                "end_date": None,
                "mode": "base100",
            }

        online_item_codes = {
            str(row.get("item_code"))
            for row in self._online.search_summaries()
            if row.get("item_code") and row.get("average_unit_price") not in {None, ""}
        }
        item_code = max(
            dates_by_item,
            key=lambda code: (
                code in online_item_codes,
                max(dates_by_item[code]),
                len(dates_by_item[code]),
            ),
        )
        available_dates = dates_by_item[item_code]
        end_date = max(available_dates)
        start_date = max(min(available_dates), end_date - timedelta(days=89))
        return {
            "item_code": item_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "mode": "base100",
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
