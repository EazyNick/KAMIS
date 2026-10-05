from dataclasses import dataclass
from datetime import date

import pytest

from scripts.backfill.backfill_kamis_20y import parse_args


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
