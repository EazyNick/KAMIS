from __future__ import annotations

from datetime import date
from typing import Any, Protocol

import numpy as np
import pandas as pd
from holidays import country_holidays, financial_holidays

from app.infrastructure.csv_repository import PriceFilters
from app.services.analytics import AnalysisMode, AnalyticsService


class PriceRepositoryProtocol(Protocol):
    def search(self, filters: PriceFilters | None = None) -> list[dict[str, Any]]: ...


class MarketRepositoryProtocol(Protocol):
    def search(self, **kwargs: Any) -> list[dict[str, Any]]: ...


MARKET_EXCHANGES: dict[str, str | None] = {
    "kospi": "XKRX",
    "kosdaq": "XKRX",
    "sp500": "XNYS",
    "nasdaq": "XNYS",
    "dow_jones": "XNYS",
    # USD/KRW trades on weekdays but does not share a stock-exchange holiday
    # calendar. Treat weekends as normal closures and leave weekday gaps visible.
    "usd_krw": None,
    # The commodity feeds follow US futures sessions, but the provider can
    # publish values on partial-session days. Use weekends plus full US market
    # closures as a conservative proxy so genuine weekday provider gaps stay empty.
    "corn_futures": "XNYS",
    "wheat_futures": "XNYS",
    "soybean_futures": "XNYS",
    "rough_rice_futures": "XNYS",
    "coffee_futures": "XNYS",
    "sugar_futures": "XNYS",
    "cotton_futures": "XNYS",
    "orange_juice_futures": "XNYS",
}

MELON_ITEM_CODE = "257"


def fill_exchange_holidays(frame: pd.DataFrame) -> pd.DataFrame:
    """Carry prices over normal closures without inventing open-day observations."""
    result = frame.copy()
    calendar = country_holidays("KR")
    closed = pd.Series(
        [
            timestamp.weekday() >= 5 or timestamp.date() in calendar
            for timestamp in result.index
        ],
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
        calendar = financial_holidays(exchange) if exchange else frozenset()
        closed = pd.Series(
            [
                timestamp.weekday() >= 5 or timestamp.date() in calendar
                for timestamp in result.index
            ],
            index=result.index,
            dtype=bool,
        )
        fillable = result[series_id].isna() & closed
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
                None if pd.isna(value) else float(value) for value in values.tolist()
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
        "kospi",
        "kosdaq",
        "sp500",
        "nasdaq",
        "dow_jones",
        "usd_krw",
        "corn_futures",
        "wheat_futures",
        "soybean_futures",
        "rough_rice_futures",
        "coffee_futures",
        "sugar_futures",
        "cotton_futures",
        "orange_juice_futures",
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
        self._market = market_repository
        self._analytics = analytics
        self._catalog = catalog_repository
        self.comparison_kinds: dict[str, str] = {}
        if catalog_repository is not None:
            for entry in catalog_repository.entries():
                if not (
                    entry.wholesale_rank_codes or entry.retail_rank_codes
                ):
                    continue
                self.comparison_kinds.setdefault(entry.item_code, entry.kind_code)
        self.comparison_kinds.update(dict(sorted(target_keys)))

    def build_frame(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
    ) -> pd.DataFrame:
        price_rows = self._prices.search(
            PriceFilters(
                item_code=item_code,
                start_date=start_date,
                end_date=end_date,
                requested_convert_kg=False,
            )
        )
        kind = self.comparison_kinds.get(item_code)
        notes: list[str] = [
            "KAMIS 가격은 p_convert_kg_yn=N으로 수집한 원 조사단위 KRW를 사용합니다."
        ]
        if kind is not None:
            price_rows = [row for row in price_rows if row.get("kind_code") == kind]
        price_rows = [row for row in price_rows if row.get("region") != "평년"]
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

        market_rows = self._market.search(start_date=start_date, end_date=end_date)
        if market_rows:
            market = pd.DataFrame(market_rows)
            market["observed_date"] = pd.to_datetime(market["observed_date"])
            market["close"] = pd.to_numeric(market["close"], errors="coerce")
            market_dates = pd.DatetimeIndex(sorted(market["observed_date"].unique()))
            frame = frame.reindex(frame.index.union(market_dates))
            for series_id, values in market.groupby("series_id"):
                frame[str(series_id)] = values.groupby("observed_date")["close"].mean()

        observed_coverage = {}
        for key in ("kamis_wholesale", "kamis_retail"):
            observed = frame[key].dropna() if key in frame else pd.Series(dtype=float)
            observed_coverage[key] = {
                "first_date": observed.index.min().date().isoformat()
                if len(observed)
                else None,
                "last_date": observed.index.max().date().isoformat()
                if len(observed)
                else None,
                "observations": len(observed),
            }
        result = fill_exchange_holidays(frame.sort_index())
        result.attrs["kamis_observed_coverage"] = observed_coverage
        result.attrs["comparison_notes"] = notes
        return result

    def chart(
        self,
        item_code: str,
        start_date: date | None,
        end_date: date | None,
        mode: AnalysisMode = "base100",
    ) -> dict[str, Any]:
        raw_frame = self.build_frame(item_code, start_date, end_date)
        frame = self._analytics.transform(raw_frame, mode)
        result = chart_from_frame(
            item_code, mode, frame, self.core_series, raw_frame=raw_frame
        )
        result["comparison_kinds"] = self.comparison_kinds
        result["comparison_notes"] = raw_frame.attrs.get("comparison_notes", [])
        coverage = raw_frame.attrs["kamis_observed_coverage"]
        for key, label in (("kamis_wholesale", "도매"), ("kamis_retail", "소매")):
            first = coverage[key]["first_date"]
            last = coverage[key]["last_date"]
            if first:
                result["comparison_notes"].append(
                    f"KAMIS {label} 실측 범위: {first} ~ {last}. 관측이 없는 영업일의 가격은 채우지 않습니다."
                )
        result["kamis_coverage"] = coverage
        if not any(entry["observations"] for entry in coverage.values()):
            result["comparison_notes"].append(
                "이 조회 조건에 맞는 KAMIS 관측 가격이 없습니다. 시장 지수만 표시될 수 있습니다."
            )
        if any(column.startswith("kamis_") for column in raw_frame):
            result["comparison_notes"] = [
                *result["comparison_notes"],
                "KAMIS 주말·공휴일은 직전 관측 가격을 이어 표시합니다. 해당 날짜의 실측 가격은 아닙니다.",
            ]
        return result

    def dashboard_defaults(self) -> dict[str, str | None]:
        item_stats: dict[str, tuple[date, date, int]] = {}
        stats_reader = getattr(self._prices, "item_date_stats", None)
        if callable(stats_reader):
            item_stats.update(stats_reader())
        else:
            # Compatibility path for lightweight test doubles and alternate stores.
            for row in self._prices.search(PriceFilters()):
                item_code = str(row.get("item_code", ""))
                observed_value = row.get("observed_date")
                if not item_code or not observed_value:
                    continue
                observed = date.fromisoformat(str(observed_value))
                current = item_stats.get(item_code)
                if current is None:
                    item_stats[item_code] = (observed, observed, 1)
                else:
                    earliest, latest, count = current
                    item_stats[item_code] = (
                        min(earliest, observed),
                        max(latest, observed),
                        count + 1,
                    )

        if not item_stats:
            return {
                "item_code": None,
                "start_date": None,
                "end_date": None,
                "mode": "base100",
            }

        item_code = (
            MELON_ITEM_CODE
            if MELON_ITEM_CODE in item_stats
            else max(
                item_stats,
                key=lambda code: (item_stats[code][1], item_stats[code][2]),
            )
        )
        earliest, end_date, _ = item_stats[item_code]
        try:
            twenty_year_start = end_date.replace(year=end_date.year - 20)
        except ValueError:
            twenty_year_start = end_date.replace(year=end_date.year - 20, day=28)
        start_date = max(earliest, twenty_year_start)
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
