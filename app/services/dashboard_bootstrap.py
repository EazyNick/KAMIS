from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from app.infrastructure.analytics_repository import AnalyticsRepository
from app.services.comparison import (
    ComparisonService,
    chart_from_frame,
    fill_exchange_holidays,
)


class DashboardBootstrapService:
    """Build the first dashboard chart from precomputed analysis rows."""

    def __init__(
        self,
        analytics_repository: AnalyticsRepository,
        comparison_service: ComparisonService,
        preferred_item_codes: tuple[str, ...],
    ) -> None:
        self._analytics = analytics_repository
        self._comparison = comparison_service
        self._preferred_item_codes = preferred_item_codes

    def load(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        item_code = None
        for candidate in self._preferred_item_codes:
            rows = self._analytics.read_comparison_series((candidate,))
            if rows:
                item_code = candidate
                break
        if item_code is None:
            defaults = self._comparison.dashboard_defaults()
            fallback_item = defaults.get("item_code")
            chart = (
                self._comparison.chart(
                    fallback_item,
                    self._parse_date(defaults.get("start_date")),
                    self._parse_date(defaults.get("end_date")),
                    "base100",
                )
                if fallback_item
                else chart_from_frame(
                    "", "base100", pd.DataFrame(), self._comparison.core_series
                )
            )
            return {"defaults": defaults, "chart": chart}

        selected = pd.DataFrame(
            row for row in rows if row.get("item_code") == item_code
        )
        selected["observed_date"] = pd.to_datetime(selected["observed_date"])
        selected["value"] = pd.to_numeric(selected["value"], errors="coerce")
        frame = selected.pivot_table(
            index="observed_date",
            columns="series_id",
            values="value",
            aggfunc="mean",
        ).sort_index()
        end_date = frame.index.max().date()
        start_date = max(frame.index.min().date(), end_date - timedelta(days=89))
        frame = frame.loc[pd.Timestamp(start_date) : pd.Timestamp(end_date)]
        frame = fill_exchange_holidays(frame)
        raw_rows = self._analytics.read_comparison_series((item_code,), mode="raw")
        raw_selected = pd.DataFrame(
            row for row in raw_rows if row.get("item_code") == item_code
        )
        raw_frame = pd.DataFrame(index=frame.index)
        if not raw_selected.empty:
            raw_selected["observed_date"] = pd.to_datetime(
                raw_selected["observed_date"]
            )
            raw_selected["value"] = pd.to_numeric(
                raw_selected["value"], errors="coerce"
            )
            raw_frame = raw_selected.pivot_table(
                index="observed_date",
                columns="series_id",
                values="value",
                aggfunc="mean",
            ).reindex(frame.index)
            raw_frame = fill_exchange_holidays(raw_frame)
        defaults = {
            "item_code": item_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "mode": "base100",
        }
        return {
            "defaults": defaults,
            "chart": chart_from_frame(
                item_code,
                "base100",
                frame,
                self._comparison.core_series,
                raw_frame=raw_frame,
            ),
        }

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        return pd.Timestamp(value).date() if value else None
