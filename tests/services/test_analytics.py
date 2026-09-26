import math
import os

import pandas as pd

from app.infrastructure.analytics_repository import AnalyticsRepository
from app.services.analytics import AnalyticsBatchService, AnalyticsService
from log import app_logger


def sample_frame() -> pd.DataFrame:
    index = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"])
    return pd.DataFrame(
        {
            "kamis_retail": [100.0, 110.0, 121.0, 133.1],
            "kospi": [200.0, 220.0, 242.0, 266.2],
        },
        index=index,
    )


def test_base100_and_returns_are_computed_without_filling_missing_values() -> None:
    frame = sample_frame()
    frame.loc[pd.Timestamp("2026-09-22"), "kospi"] = math.nan
    service = AnalyticsService()

    base = service.transform(frame, "base100")
    one_day = service.transform(frame, "return_1d")

    assert base.iloc[0]["kamis_retail"] == 100
    assert base.iloc[-1]["kamis_retail"] == 133.1
    assert pd.isna(base.loc[pd.Timestamp("2026-09-22"), "kospi"])
    assert pd.isna(one_day.loc[pd.Timestamp("2026-09-23"), "kospi"])


def test_correlations_include_pearson_spearman_and_observation_count() -> None:
    results = AnalyticsService().correlations(sample_frame(), "kamis_retail")
    kospi = next(row for row in results if row["comparison_series"] == "kospi")

    assert kospi["observations"] == 4
    assert kospi["pearson"] == 1.0
    assert kospi["spearman"] == 1.0
    assert "pearson_fdr" in kospi


def test_lag_correlation_reports_best_lag_in_requested_range() -> None:
    frame = pd.DataFrame(
        {"target": [1, 2, 3, 4, 5, 6], "leading": [2, 3, 4, 5, 6, 7]},
        index=pd.bdate_range("2026-09-01", periods=6),
    )
    rows = AnalyticsService().lag_correlations(frame, "target", "leading", -2, 2)

    assert {row["lag"] for row in rows} == {-2, -1, 0, 1, 2}
    assert all(row["observations"] >= 4 for row in rows)


def test_batch_refresh_skips_when_comparison_cache_is_current(tmp_path) -> None:
    repository = AnalyticsRepository(tmp_path, app_logger)
    repository.save(
        "comparison_series",
        [{"item_code": "111", "mode": "raw", "value": 100.0}],
        "existing-run",
    )
    source = tmp_path / "normalized" / "market_observations.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("market", encoding="utf-8")
    target = repository.table_path("comparison_series")
    os.utime(source, ns=(1_000_000_000, 1_000_000_000))
    os.utime(target, ns=(2_000_000_000, 2_000_000_000))
    batch = AnalyticsBatchService(None, AnalyticsService(), repository, app_logger)

    assert batch.refresh_if_stale([], "startup-check", (source,)) == 0
    assert repository.read("comparison_series") == [
        {"item_code": "111", "mode": "raw", "value": "100.0"}
    ]
