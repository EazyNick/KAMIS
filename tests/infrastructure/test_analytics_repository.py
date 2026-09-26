from __future__ import annotations

import os

from app.infrastructure.analytics_repository import AnalyticsRepository
from log import app_logger


def test_comparison_cache_is_stale_only_when_source_is_newer(tmp_path) -> None:
    repository = AnalyticsRepository(tmp_path, app_logger)
    repository.save(
        "comparison_series",
        [
            {
                "item_code": "111",
                "kind_code": "01",
                "observed_date": "2026-09-21",
                "mode": "raw",
                "series_id": "sp500",
                "value": 100.0,
            }
        ],
        "analytics-run",
    )
    source = tmp_path / "normalized" / "market_observations.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("market", encoding="utf-8")
    target = tmp_path / "analytics" / "comparison_series.csv"

    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(target, ns=(2_000_000_000, 2_000_000_000))
    assert repository.comparison_is_stale((source,)) is False

    os.utime(source, ns=(3_000_000_000, 3_000_000_000))
    assert repository.comparison_is_stale((source,)) is True


def test_missing_comparison_cache_is_stale(tmp_path) -> None:
    repository = AnalyticsRepository(tmp_path, app_logger)
    source = tmp_path / "normalized" / "market_observations.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("market", encoding="utf-8")

    assert repository.comparison_is_stale((source,)) is True
