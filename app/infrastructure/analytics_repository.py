from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

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

    def save(self, table: str, rows: list[dict[str, Any]], run_id: str) -> Path:
        if table not in self._allowed_tables:
            raise ValueError(f"unsupported analytics table: {table}")
        storage = _AtomicCsvRepository(self._data_dir / f"{table}.csv", self._logger)
        storage._atomic_write(rows, run_id)
        return storage.path

    def read(self, table: str) -> list[dict[str, str]]:
        if table not in self._allowed_tables:
            raise ValueError(f"unsupported analytics table: {table}")
        return _AtomicCsvRepository(
            self._data_dir / f"{table}.csv", self._logger
        )._read()
