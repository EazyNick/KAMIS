from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import StorageError
from app.domain.models import CollectionRun, PriceObservation, PriceType, RunStatus
from app.infrastructure.csv_repository import (
    PriceFilters,
    PriceRepository,
    RunRepository,
)
from log import app_logger


def price_row(price: str = "1000") -> PriceObservation:
    return PriceObservation(
        price_type=PriceType.RETAIL,
        observed_date=date(2026, 9, 24),
        collected_at=datetime(2026, 9, 24, 7, tzinfo=ZoneInfo("Asia/Seoul")),
        category_code="100",
        item_code="111",
        kind_code="01",
        rank_code="04",
        item_name="쌀",
        variety="20kg",
        region="서울",
        market_name="A-유통",
        price_krw=Decimal(price),
        requested_convert_kg=True,
    )


def test_price_repository_upserts_duplicate_observations(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)

    first = repository.upsert([price_row()], "run-1")
    second = repository.upsert([price_row("1010")], "run-2")
    rows = repository.search(PriceFilters(item_code="111"))

    assert first.inserted == 1
    assert second.updated == 1
    assert rows[0]["price_krw"] == 1010.0


def test_repository_preserves_existing_file_when_new_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert([price_row()], "run-1")
    original = repository.path.read_bytes()

    def fail_serialize(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(repository, "_serialize", fail_serialize)

    with pytest.raises(StorageError, match="disk full"):
        repository.upsert([price_row("1020")], "run-2")

    assert repository.path.read_bytes() == original


def test_run_repository_detects_only_successful_daily_run(tmp_path: Path) -> None:
    repository = RunRepository(tmp_path, app_logger)
    observed_date = date(2026, 9, 24)
    failed = CollectionRun.start("daily_pipeline", observed_date, observed_date).finish(
        RunStatus.PARTIAL_FAILURE, record_count=3, error_count=1
    )
    repository.save(failed)

    assert repository.has_successful_run("daily_pipeline", observed_date) is False

    successful = CollectionRun.start(
        "daily_pipeline", observed_date, observed_date
    ).finish(RunStatus.SUCCESS, record_count=10, error_count=0)
    repository.save(successful)

    assert repository.has_successful_run("daily_pipeline", observed_date) is True
