from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Protocol

import numpy as np
import pandas as pd
from holidays import country_holidays, financial_holidays

from app.infrastructure.csv_repository import PriceFilters
from app.services.analytics import AnalysisMode, AnalyticsService
from app.services.comparison_units import comparable_kamis_rows


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
    # publish values on partial-session days. Only use full US market closures
    # as a conservative proxy so genuine provider gaps stay empty.
    "corn_futures": "XNYS",
    "wheat_futures": "XNYS",
    "soybean_futures": "XNYS",
    "rough_rice_futures": "XNYS",
    "coffee_futures": "XNYS",
    "sugar_futures": "XNYS",
    "cotton_futures": "XNYS",
    "orange_juice_futures": "XNYS",
}

# Dashboard-only visual estimates for melon (item 257). These values are never
# used by the correlation endpoint. The current KAMIS reference is the
# 2026-09-30 retail average stored in this repository. Coupang's anchor uses a
# current 1.5 kg listing found during the 2026-09-30 web check. A directly
# comparable Naver listing was not reliably obtainable, so the Naver anchor is
# an explicit modelling baseline within the current online 1.5 kg market range.
MELON_ITEM_CODE = "257"
MELON_KAMIS_REFERENCE_PRICE = 9169.85
MELON_DASHBOARD_ESTIMATES = {
    "online_naver": {"anchor": 8900.0, "lag": 1, "elasticity": 0.90},
    "online_coupang": {"anchor": 6600.0, "lag": 2, "elasticity": 0.90},
}
MELON_ESTIMATE_NOTE = (
    "멜론 네이버·쿠팡 가격은 실측 온라인 이력이 없는 구간에 한해 표시하는 "
    "대시보드용 추정치입니다. KAMIS 소매가격 흐름을 기준으로 네이버 1관측일, "
    "쿠팡 2관측일 시차를 적용했으며 상관관계 통계에는 포함하지 않습니다."
)


def fill_exchange_holidays(frame: pd.DataFrame) -> pd.DataFrame:
    """Carry prices over normal closures without inventing open-day observations."""
    result = frame.copy()
    calendar = country_holidays("KR")
    closed = pd.Series(
        [timestamp.weekday() >= 5 or timestamp.date() in calendar for timestamp in result.index],
        index=result.index,
        dtype=bool,
    )
    for column in ("kamis_wholesale", "kamis_retail"):
        if column in result:
            fillable = result[column].isna() & closed
            result.loc[fillable, column] = result[column].ffill().loc[fillable]
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
        *,
        target_keys: set[tuple[str, str]] | frozenset[tuple[str, str]] = frozenset(),
        catalog_repository=None,
    ) -> None:
        self._prices = price_repository
        self._online = online_repository
        self._market = market_repository
        self._analytics = analytics
        self.comparison_kinds = dict(sorted(target_keys))
        self._catalog = catalog_repository

    def build_frame(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
        *,
        include_dashboard_estimates: bool = False,
    ) -> pd.DataFrame:
        price_rows = self._prices.search(
            PriceFilters(item_code=item_code, start_date=start_date, end_date=end_date)
        )
        kind = self.comparison_kinds.get(item_code)
        notes: list[str] = []
        if kind is not None and self._catalog is not None:
            price_rows, notes = comparable_kamis_rows(
                price_rows,
                item_code,
                kind,
                [entry.to_dict() for entry in self._catalog.entries()],
            )
        elif kind is not None:
            price_rows = [row for row in price_rows if row.get("kind_code") == kind]
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

        online = self.online_frame(item_code, start_date, end_date)
        frame = frame.reindex(frame.index.union(online.index))
        for column in online:
            frame[column] = online[column]

        estimated_series: list[str] = []
        if include_dashboard_estimates:
            frame, estimate_notes, estimated_series = self._add_dashboard_estimates(
                item_code, frame
            )
            notes.extend(estimate_notes)

        market_rows = self._market.search(start_date=start_date, end_date=end_date)
        if market_rows:
            market = pd.DataFrame(market_rows)
            market["observed_date"] = pd.to_datetime(market["observed_date"])
            market["close"] = pd.to_numeric(market["close"], errors="coerce")
            market_dates = pd.DatetimeIndex(sorted(market["observed_date"].unique()))
            frame = frame.reindex(frame.index.union(market_dates))
            for series_id, values in market.groupby("series_id"):
                frame[str(series_id)] = values.groupby("observed_date")["close"].mean()

        result = fill_exchange_holidays(frame.sort_index())
        result.attrs["comparison_notes"] = notes
        result.attrs["estimated_series"] = estimated_series
        return result

    def _add_dashboard_estimates(
        self, item_code: str, frame: pd.DataFrame
    ) -> tuple[pd.DataFrame, list[str], list[str]]:
        if item_code != MELON_ITEM_CODE or "kamis_retail" not in frame:
            return frame, [], []

        kamis = frame["kamis_retail"].dropna()
        if len(kamis) < 3:
            return frame, [], []

        result = frame.copy()
        estimated_series: list[str] = []
        for column, config in MELON_DASHBOARD_ESTIMATES.items():
            if column in result and result[column].notna().any():
                continue

            driver = kamis.shift(int(config["lag"]))
            modeled = (
                float(config["anchor"])
                * (driver / MELON_KAMIS_REFERENCE_PRICE)
                ** float(config["elasticity"])
            )
            result[column] = modeled.reindex(result.index).map(
                lambda value: (
                    np.nan
                    if pd.isna(value)
                    else float(round(float(value) / 10.0) * 10)
                )
            )
            estimated_series.append(column)

        if estimated_series:
            platforms = [
                column
                for column in ("online_naver", "online_coupang")
                if column in result and result[column].notna().any()
            ]
            if platforms:
                result["online_combined"] = result[platforms].mean(axis=1)
                estimated_series.append("online_combined")
            return result, [MELON_ESTIMATE_NOTE], estimated_series

        return result, [], []

    def online_frame(
        self, item_code: str, start_date: date | None = None, end_date: date | None = None
    ) -> pd.DataFrame:
        rows = self._online.search_summaries(item_code=item_code)
        kind = self.comparison_kinds.get(item_code)
        if kind is not None:
            rows = [row for row in rows if row.get("kind_code") == kind]
        if not rows:
            return pd.DataFrame(index=pd.DatetimeIndex([]))
        online = pd.DataFrame(rows)
        online["observed_date"] = pd.to_datetime(online["observed_date"])
        online["average_unit_price"] = pd.to_numeric(
            online["average_unit_price"], errors="coerce"
        )
        online = online.dropna(subset=["average_unit_price"])
        if start_date:
            online = online[online["observed_date"] >= pd.Timestamp(start_date)]
        if end_date:
            online = online[online["observed_date"] <= pd.Timestamp(end_date)]
        frame = online.pivot_table(
            index="observed_date",
            columns="platform",
            values="average_unit_price",
            aggfunc="mean",
        )
        # Agent-only collection updates platform summaries before the combined cache.
        platforms = [column for column in ("naver", "coupang") if column in frame]
        if platforms:
            frame["combined"] = frame[platforms].mean(axis=1)
        return frame.rename(
            columns=lambda column: f"online_{column}"
        ).sort_index()

    def chart(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
        mode: AnalysisMode = "base100",
    ) -> dict[str, Any]:
        raw_frame = self.build_frame(
            item_code,
            start_date,
            end_date,
            include_dashboard_estimates=True,
        )
        frame = self._analytics.transform(raw_frame, mode)
        result = chart_from_frame(
            item_code, mode, frame, self.core_series, raw_frame=raw_frame
        )
        result["comparison_kinds"] = self.comparison_kinds
        result["comparison_notes"] = raw_frame.attrs.get("comparison_notes", [])
        result["estimated_series"] = raw_frame.attrs.get("estimated_series", [])
        if any(column.startswith("kamis_") for column in raw_frame):
            result["comparison_notes"] = [
                *result["comparison_notes"],
                "KAMIS 주말·공휴일은 직전 관측 가격을 이어 표시합니다. 해당 날짜의 실측 가격은 아닙니다.",
            ]
        return result

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

        online_rows = self._online.search_summaries()
        for row in online_rows:
            if (
                row.get("item_code")
                and row.get("observed_date")
                and row.get("average_unit_price") not in {None, ""}
            ):
                dates_by_item.setdefault(str(row["item_code"]), []).append(
                    date.fromisoformat(str(row["observed_date"]))
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
            for row in online_rows
            if row.get("item_code")
            and row.get("average_unit_price") not in {None, ""}
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
