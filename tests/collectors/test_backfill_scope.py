from dataclasses import dataclass
from datetime import date

import pytest

from scripts.backfill.backfill_kamis_20y import parse_args, should_skip_query


def test_chunked_fetch_covers_leap_month_without_overlap_or_missing_days():
    from scripts.backfill.backfill_kamis_20y import fetch_in_chunks

    @dataclass
    class Query:
        start_date: date
        end_date: date

    class Client:
        def fetch_prices(self, query):
            return [(query.start_date.isoformat(), query.end_date.isoformat())]

    assert fetch_in_chunks(Client(), Query(date(2020, 2, 1), date(2020, 3, 3)), 15) == [
        ("2020-02-01", "2020-02-15"),
        ("2020-02-16", "2020-03-01"),
        ("2020-03-02", "2020-03-03"),
    ]


def test_backfill_can_scope_grain_history_and_resume_a_single_year():
    args = parse_args(
        ["--category-code", "100", "--start-year", "2006", "--end-year", "2006"]
    )
    assert args.category_code == "100"
    assert args.start_year == args.end_year == 2006


def test_backfill_parallelism_is_bounded():
    assert parse_args(["--workers", "4"]).workers == 4
    with pytest.raises(SystemExit):
        parse_args(["--workers", "5"])


def test_missing_dashboard_item_is_never_skipped_even_with_completed_checkpoint():
    assert (
        should_skip_query(
            force=False,
            item_missing_from_dashboard=True,
            key_completed=True,
            expected_count=0,
            stored_count=0,
        )
        is False
    )


def test_existing_item_skips_only_when_persisted_count_covers_checkpoint():
    assert (
        should_skip_query(
            force=False,
            item_missing_from_dashboard=False,
            key_completed=True,
            expected_count=10,
            stored_count=10,
        )
        is True
    )
    assert (
        should_skip_query(
            force=False,
            item_missing_from_dashboard=False,
            key_completed=True,
            expected_count=10,
            stored_count=9,
        )
        is False
    )
