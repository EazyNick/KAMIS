from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, ClassVar

import pandas as pd

from app.infrastructure.csv_repository import _AtomicCsvRepository
from log.logger import StructuredLogger


class AnalyticsRepository:
    _allowed_tables: ClassVar[set[str]] = {
        "comparison_series",
        "correlations",
        "lag_correlations",
        "rolling_correlations",
        "spreads_volatility",
    }

    def __init__(self, data_dir: Path, logger: StructuredLogger) -> None:
        self._data_dir = data_dir / "analytics"
        self._logger = logger
        self._cache_lock = RLock()
        self._comparison_cache_key: tuple[object, ...] | None = None
        self._comparison_cache: list[dict[str, Any]] = []

    def table_path(self, table: str) -> Path:
        if table not in self._allowed_tables:
            raise ValueError(f"unsupported analytics table: {table}")
        return self._data_dir / f"{table}.csv"

    def comparison_is_stale(self, source_paths: tuple[Path, ...]) -> bool:
        target = self.table_path("comparison_series")
        if not target.exists() or target.stat().st_size == 0:
            return True
        target_mtime = target.stat().st_mtime_ns
        return any(
            path.exists() and path.stat().st_mtime_ns > target_mtime
            for path in source_paths
        )

    def save(self, table: str, rows: list[dict[str, Any]], run_id: str) -> Path:
        if table not in self._allowed_tables:
            raise ValueError(f"unsupported analytics table: {table}")
        storage = _AtomicCsvRepository(self.table_path(table), self._logger)
        storage._atomic_write(rows, run_id)
        return storage.path

    def read(self, table: str) -> list[dict[str, str]]:
        if table not in self._allowed_tables:
            raise ValueError(f"unsupported analytics table: {table}")
        return _AtomicCsvRepository(
            self._data_dir / f"{table}.csv", self._logger
        )._read()

    def read_comparison_series(
        self, item_codes: tuple[str, ...], mode: str = "base100"
    ) -> list[dict[str, Any]]:
        path = self._data_dir / "comparison_series.csv"
        if not path.exists() or path.stat().st_size == 0:
            return []
        stat = path.stat()
        cache_key = (stat.st_mtime_ns, stat.st_size, item_codes, mode)
        with self._cache_lock:
            if cache_key == self._comparison_cache_key:
                return [dict(row) for row in self._comparison_cache]
            frame = pd.read_csv(
                path,
                usecols=(
                    "item_code",
                    "kind_code",
                    "observed_date",
                    "mode",
                    "series_id",
                    "value",
                ),
                dtype={
                    "item_code": "string",
                    "kind_code": "string",
                    "observed_date": "string",
                    "mode": "string",
                    "series_id": "string",
                },
            )
            rows = frame.loc[
                frame["item_code"].isin(item_codes) & frame["mode"].eq(mode)
            ].to_dict("records")
            self._comparison_cache_key = cache_key
            self._comparison_cache = rows
            return [dict(row) for row in rows]
