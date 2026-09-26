from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from app.domain.models import ProductCatalogEntry
from app.infrastructure.analytics_repository import AnalyticsRepository
from log.logger import StructuredLogger

AnalysisMode = Literal["raw", "base100", "return_1d", "return_7d"]


class AnalyticsService:
    def transform(self, frame: pd.DataFrame, mode: AnalysisMode) -> pd.DataFrame:
        numeric = frame.astype(float).sort_index()
        if mode == "raw":
            return numeric
        if mode == "base100":
            transformed = numeric.copy()
            for column in transformed.columns:
                valid = transformed[column].dropna()
                if valid.empty or valid.iloc[0] == 0:
                    transformed[column] = np.nan
                else:
                    transformed[column] = transformed[column] / valid.iloc[0] * 100
            return transformed
        periods = 1 if mode == "return_1d" else 7
        return numeric.pct_change(periods=periods, fill_method=None) * 100

    def correlations(
        self, frame: pd.DataFrame, target_series: str
    ) -> list[dict[str, Any]]:
        if target_series not in frame.columns:
            return []
        rows: list[dict[str, Any]] = []
        for column in frame.columns:
            if column == target_series:
                continue
            pair = frame[[target_series, column]].dropna()
            if (
                len(pair) < 3
                or pair[target_series].nunique() < 2
                or pair[column].nunique() < 2
            ):
                pearson_value = spearman_value = pearson_p = spearman_p = float("nan")
            else:
                pearson_result = pearsonr(pair[target_series], pair[column])
                spearman_result = spearmanr(pair[target_series], pair[column])
                pearson_value = float(pearson_result.statistic)
                pearson_p = float(pearson_result.pvalue)
                spearman_value = float(spearman_result.statistic)
                spearman_p = float(spearman_result.pvalue)
            rows.append(
                {
                    "target_series": target_series,
                    "comparison_series": column,
                    "observations": len(pair),
                    "pearson": self._clean_coefficient(pearson_value),
                    "pearson_p": pearson_p,
                    "spearman": self._clean_coefficient(spearman_value),
                    "spearman_p": spearman_p,
                }
            )
        pearson_adjusted = self._fdr([row["pearson_p"] for row in rows])
        spearman_adjusted = self._fdr([row["spearman_p"] for row in rows])
        for row, pearson_fdr, spearman_fdr in zip(
            rows, pearson_adjusted, spearman_adjusted, strict=True
        ):
            row["pearson_fdr"] = pearson_fdr
            row["spearman_fdr"] = spearman_fdr
        return rows

    def lag_correlations(
        self,
        frame: pd.DataFrame,
        target_series: str,
        comparison_series: str,
        minimum_lag: int = -14,
        maximum_lag: int = 14,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for lag in range(minimum_lag, maximum_lag + 1):
            pair = pd.concat(
                [
                    frame[target_series].rename("target"),
                    frame[comparison_series].shift(lag).rename("comparison"),
                ],
                axis=1,
            ).dropna()
            if (
                len(pair) < 3
                or pair["target"].nunique() < 2
                or pair["comparison"].nunique() < 2
            ):
                coefficient = p_value = float("nan")
            else:
                result = pearsonr(pair["target"], pair["comparison"])
                coefficient = self._clean_coefficient(float(result.statistic))
                p_value = float(result.pvalue)
            rows.append(
                {
                    "target_series": target_series,
                    "comparison_series": comparison_series,
                    "lag": lag,
                    "observations": len(pair),
                    "pearson": coefficient,
                    "p_value": p_value,
                }
            )
        adjusted = self._fdr([row["p_value"] for row in rows])
        for row, value in zip(rows, adjusted, strict=True):
            row["fdr"] = value
        return rows

    @staticmethod
    def rolling_correlations(
        frame: pd.DataFrame,
        target_series: str,
        comparison_series: str,
        windows: tuple[int, ...] = (30, 90),
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for window in windows:
            values = frame[target_series].rolling(window).corr(frame[comparison_series])
            result.extend(
                {
                    "observed_date": timestamp.date().isoformat(),
                    "target_series": target_series,
                    "comparison_series": comparison_series,
                    "window": window,
                    "correlation": float(value),
                }
                for timestamp, value in values.dropna().items()
            )
        return result

    @staticmethod
    def spreads_and_volatility(frame: pd.DataFrame) -> pd.DataFrame:
        output = pd.DataFrame(index=frame.index)
        if {"online_combined", "kamis_retail"}.issubset(frame.columns):
            output["online_minus_kamis_retail"] = (
                frame["online_combined"] - frame["kamis_retail"]
            )
        if {"kamis_retail", "kamis_wholesale"}.issubset(frame.columns):
            output["retail_minus_wholesale"] = (
                frame["kamis_retail"] - frame["kamis_wholesale"]
            )
        returns = frame.pct_change(fill_method=None)
        for window in (7, 30):
            for column in frame.columns:
                output[f"{column}_volatility_{window}"] = (
                    returns[column].rolling(window).std()
                )
        return output

    @staticmethod
    def _clean_coefficient(value: float) -> float:
        if np.isnan(value):
            return value
        if abs(value - 1) < 1e-12:
            return 1.0
        if abs(value + 1) < 1e-12:
            return -1.0
        return value

    @staticmethod
    def _fdr(values: list[float]) -> list[float]:
        result = [float("nan")] * len(values)
        valid = [
            (index, value) for index, value in enumerate(values) if not np.isnan(value)
        ]
        if not valid:
            return result
        ordered = sorted(valid, key=lambda pair: pair[1])
        total = len(ordered)
        running = 1.0
        for reverse_index in range(total - 1, -1, -1):
            original_index, p_value = ordered[reverse_index]
            rank = reverse_index + 1
            running = min(running, p_value * total / rank)
            result[original_index] = min(running, 1.0)
        return result


class AnalyticsBatchService:
    def __init__(
        self,
        comparison_service: Any,
        analytics: AnalyticsService,
        repository: AnalyticsRepository,
        logger: StructuredLogger,
    ) -> None:
        self._comparison = comparison_service
        self._analytics = analytics
        self._repository = repository
        self._logger = logger

    def refresh_if_stale(
        self,
        catalog: list[ProductCatalogEntry],
        run_id: str,
        source_paths: tuple[Path, ...],
    ) -> int:
        if not self._repository.comparison_is_stale(source_paths):
            self._logger.info(  # noqa: PLE1205 - structured logger
                "analytics.refresh.skipped",
                "Analytics cache is current",
                run_id=run_id,
                reason="source_not_newer",
                source_count=len(source_paths),
            )
            return 0
        return self.refresh(catalog, run_id)

    def refresh(self, catalog: list[ProductCatalogEntry], run_id: str) -> int:
        started = perf_counter()
        self._logger.info(  # noqa: PLE1205 - structured logger
            "analytics.refresh.started",
            "Analytics cache refresh started",
            run_id=run_id,
            catalog_count=len(catalog),
        )
        comparison_rows: list[dict[str, Any]] = []
        correlation_rows: list[dict[str, Any]] = []
        lag_rows: list[dict[str, Any]] = []
        rolling_rows: list[dict[str, Any]] = []
        spread_rows: list[dict[str, Any]] = []
        for entry in catalog:
            self._logger.debug(  # noqa: PLE1205 - structured logger
                "analytics.refresh.item.started",
                "Building analytics for catalog item",
                run_id=run_id,
                item_code=entry.item_code,
                kind_code=entry.kind_code,
                item_name=entry.item_name,
            )
            frame = self._comparison.build_frame(entry.item_code, None, None)
            if frame.empty:
                self._logger.debug(  # noqa: PLE1205 - structured logger
                    "analytics.refresh.item.skipped",
                    "Catalog item has no comparison data",
                    run_id=run_id,
                    item_code=entry.item_code,
                    kind_code=entry.kind_code,
                    reason="empty_frame",
                )
                continue
            for mode in ("raw", "base100", "return_1d", "return_7d"):
                transformed = self._analytics.transform(frame, mode)
                for observed_date, values in transformed.iterrows():
                    for series_id, value in values.items():
                        if pd.notna(value):
                            comparison_rows.append(
                                {
                                    "item_code": entry.item_code,
                                    "kind_code": entry.kind_code,
                                    "observed_date": observed_date.date().isoformat(),
                                    "mode": mode,
                                    "series_id": series_id,
                                    "value": float(value),
                                }
                            )
            target = "kamis_retail" if "kamis_retail" in frame else None
            if target:
                for row in self._analytics.correlations(frame, target):
                    correlation_rows.append(
                        {
                            "item_code": entry.item_code,
                            "kind_code": entry.kind_code,
                            **row,
                        }
                    )
                for comparison in frame.columns:
                    if comparison == target:
                        continue
                    lag_rows.extend(
                        {
                            "item_code": entry.item_code,
                            "kind_code": entry.kind_code,
                            **row,
                        }
                        for row in self._analytics.lag_correlations(
                            frame, target, comparison
                        )
                    )
                    rolling_rows.extend(
                        {
                            "item_code": entry.item_code,
                            "kind_code": entry.kind_code,
                            **row,
                        }
                        for row in self._analytics.rolling_correlations(
                            frame, target, comparison
                        )
                    )
            spread_frame = self._analytics.spreads_and_volatility(frame)
            for observed_date, values in spread_frame.iterrows():
                for metric, value in values.items():
                    if pd.notna(value):
                        spread_rows.append(
                            {
                                "item_code": entry.item_code,
                                "kind_code": entry.kind_code,
                                "observed_date": observed_date.date().isoformat(),
                                "metric": metric,
                                "value": float(value),
                            }
                        )
        tables = {
            "comparison_series": comparison_rows,
            "correlations": correlation_rows,
            "lag_correlations": lag_rows,
            "rolling_correlations": rolling_rows,
            "spreads_volatility": spread_rows,
        }
        for table, rows in tables.items():
            self._logger.info(  # noqa: PLE1205 - structured logger
                "analytics.refresh.table.writing",
                "Writing analytics table",
                run_id=run_id,
                table=table,
                record_count=len(rows),
            )
            self._repository.save(table, rows, run_id)
        total = sum(len(rows) for rows in tables.values())
        self._logger.info(  # noqa: PLE1205 - structured logger
            "analytics.refresh.completed",
            "Analytics cache refresh completed",
            run_id=run_id,
            catalog_count=len(catalog),
            record_count=total,
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return total
