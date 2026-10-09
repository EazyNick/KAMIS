from dataclasses import replace
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


def test_price_date_range_uses_actual_observations(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    assert repository.observed_date_range() is None
    repository.upsert(
        [
            replace(price_row(), observed_date=date(2024, 1, 3)),
            replace(price_row(), observed_date=date(2026, 9, 23)),
        ],
        "seed",
    )
    assert repository.observed_date_range() == (date(2024, 1, 3), date(2026, 9, 23))


def test_price_repository_detects_existing_observed_date(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert([price_row()], "seed")

    assert repository.has_collected_date(date(2026, 9, 24)) is True
    assert repository.has_collected_date(date(2026, 9, 25)) is False


def test_price_repository_requires_configured_item_coverage(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert(
        [
            price_row(),
            replace(price_row(), item_code="222", kind_code="01", item_name="감자"),
        ],
        "seed",
    )

    observed_date = date(2026, 9, 24)
    assert (
        repository.has_collected_date(
            observed_date,
            {
                ("111", "01", "retail", "04"),
                ("222", "01", "retail", "04"),
            },
        )
        is True
    )
    assert (
        repository.has_collected_date(
            observed_date,
            {
                ("111", "01", "retail", "04"),
                ("222", "01", "retail", "04"),
                ("111", "01", "wholesale", "04"),
            },
        )
        is False
    )


def test_price_repository_reports_only_dates_with_complete_scope_coverage(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    first = replace(price_row(), observed_date=date(2026, 10, 7))
    second = replace(price_row(), observed_date=date(2026, 10, 8))
    repository.upsert(
        [
            first,
            replace(
                first,
                price_type=PriceType.WHOLESALE,
                rank_code="03",
                market_name="B-유통",
            ),
            second,
        ],
        "seed",
    )

    required = {
        ("111", "01", "retail", "04"),
        ("111", "01", "wholesale", "03"),
    }

    assert repository.covered_dates(
        date(2026, 10, 7),
        date(2026, 10, 8),
        required,
    ) == {date(2026, 10, 7)}


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
        requested_convert_kg=False,
    )


def test_price_repository_can_select_only_original_kamis_prices(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    raw = price_row("28980.57")
    converted = replace(
        raw,
        price_krw=Decimal("8800"),
        requested_convert_kg=True,
        market_name="legacy-converted",
    )
    repository.upsert([raw, converted], "seed")

    rows = repository.search(PriceFilters(requested_convert_kg=False))

    assert len(rows) == 1
    assert rows[0]["price_krw"] == 28980.57
    assert repository.item_date_stats(requested_convert_kg=False)["111"][2] == 1


def test_scope_year_counts_separates_raw_from_legacy_converted_rows(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    raw_2025 = replace(price_row(), observed_date=date(2025, 1, 3))
    raw_2026 = replace(price_row(), observed_date=date(2026, 1, 3))
    converted_2026 = replace(
        raw_2026,
        requested_convert_kg=True,
        market_name="legacy-converted",
    )
    repository.upsert([raw_2025, raw_2026, converted_2026], "seed")

    counts = repository.scope_year_counts(
        2025,
        2026,
        requested_convert_kg=False,
    )

    assert counts[("111", "01", "retail", "04", 2025)] == 1
    assert counts[("111", "01", "retail", "04", 2026)] == 1


def test_scope_month_counts_separates_months_and_raw_rows(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    jan = replace(price_row(), observed_date=date(2026, 1, 3))
    feb = replace(price_row(), observed_date=date(2026, 2, 3))
    converted = replace(
        feb,
        requested_convert_kg=True,
        market_name="legacy-converted",
    )
    repository.upsert([jan, feb, converted], "seed")

    counts = repository.scope_month_counts(
        2026,
        requested_convert_kg=False,
    )

    assert counts[("111", "01", "retail", "04", 1)] == 1
    assert counts[("111", "01", "retail", "04", 2)] == 1


def test_price_repository_item_date_stats_stream_long_history(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert(
        [
            replace(price_row(), observed_date=date(2006, 1, 3)),
            replace(price_row(), observed_date=date(2026, 9, 24)),
            replace(
                price_row(),
                observed_date=date(2025, 5, 1),
                item_code="222",
                kind_code="01",
                item_name="감자",
            ),
        ],
        "seed",
    )

    assert repository.item_date_stats() == {
        "111": (date(2006, 1, 3), date(2026, 9, 24), 2),
        "222": (date(2025, 5, 1), date(2025, 5, 1), 1),
    }


def test_price_repository_bounded_search_keeps_requested_history(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert(
        [
            replace(price_row(), observed_date=date(2006, 1, 3)),
            replace(price_row(), observed_date=date(2016, 1, 4)),
            replace(price_row(), observed_date=date(2026, 9, 24)),
        ],
        "seed",
    )

    rows = repository.search(
        PriceFilters(
            item_code="111",
            start_date=date(2010, 1, 1),
            end_date=date(2020, 12, 31),
        )
    )

    assert [row["observed_date"] for row in rows] == ["2016-01-04"]


def test_price_search_does_not_drop_history_in_unsorted_import(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository._atomic_write(
        [
            replace(price_row(), observed_date=date(2026, 9, 24)).to_dict(),
            replace(price_row(), observed_date=date(2016, 1, 4)).to_dict(),
        ],
        "import",
    )
    rows = repository.search(PriceFilters(item_code="111", end_date=date(2020, 1, 1)))
    assert [r["observed_date"] for r in rows] == ["2016-01-04"]


def test_price_repository_upserts_duplicate_observations(tmp_path: Path) -> None:
    repository = PriceRepository(tmp_path, app_logger)

    first = repository.upsert([price_row()], "run-1")
    second = repository.upsert([price_row("1010")], "run-2")
    rows = repository.search(PriceFilters(item_code="111"))

    assert first.inserted == 1
    assert second.updated == 1
    assert rows[0]["price_krw"] == 1010.0


def test_backfill_repeated_observation_with_missing_market_is_updated(
    tmp_path: Path,
) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    observation = replace(
        price_row(), region=None, market_name=None, requested_convert_kg=False
    )
    repository.upsert([observation], "first")
    result = repository.upsert(
        [replace(observation, price_krw=Decimal("1100"))], "repeat"
    )
    assert result.inserted == 0
    assert result.updated == 1
    assert len(repository.search()) == 1
    assert repository.search()[0]["price_krw"] == 1100.0


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


def test_run_repository_returns_dates_covered_by_successful_ranges(
    tmp_path: Path,
) -> None:
    repository = RunRepository(tmp_path, app_logger)
    successful = CollectionRun.start(
        "kamis",
        date(2026, 10, 7),
        date(2026, 10, 8),
    ).finish(RunStatus.SUCCESS, record_count=10, error_count=0)
    partial = CollectionRun.start(
        "kamis",
        date(2026, 10, 5),
        date(2026, 10, 6),
    ).finish(RunStatus.PARTIAL_FAILURE, record_count=3, error_count=1)
    repository.save(successful)
    repository.save(partial)

    assert repository.successful_covered_dates(
        "kamis",
        date(2026, 10, 5),
        date(2026, 10, 9),
    ) == {date(2026, 10, 7), date(2026, 10, 8)}


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
