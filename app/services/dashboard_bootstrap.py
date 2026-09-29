from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.infrastructure.analytics_repository import AnalyticsRepository
from app.services.comparison import ComparisonService, chart_from_frame


class DashboardBootstrapService:
    """Build the first dashboard chart from the latest source CSV contents."""

    def __init__(
        self,
        analytics_repository: AnalyticsRepository,
        comparison_service: ComparisonService,
        preferred_item_codes: tuple[str, ...],
    ) -> None:
        # Keep the constructor contract stable for the container, but do not use
        # precomputed analytics rows for the initial chart. Source repositories
        # read their CSV files on every request, so browser refreshes can show
        # newly collected data without restarting the server.
        self._analytics = analytics_repository
        self._comparison = comparison_service
        self._preferred_item_codes = preferred_item_codes

    def load(self) -> dict[str, Any]:
        defaults = self._comparison.dashboard_defaults()
        item_code = defaults.get("item_code")
        start_date = self._parse_date(defaults.get("start_date"))
        end_date = self._parse_date(defaults.get("end_date"))

        if not item_code:
            return {
                "defaults": defaults,
                "chart": chart_from_frame(
                    "",
                    "base100",
                    pd.DataFrame(),
                    self._comparison.core_series,
                ),
            }

        return {
            "defaults": defaults,
            "chart": self._comparison.chart(
                item_code,
                start_date,
                end_date,
                "base100",
            ),
        }

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        return pd.Timestamp(value).date() if value else None
