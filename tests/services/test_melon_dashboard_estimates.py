import csv
from datetime import date, timedelta
from pathlib import Path

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


class MelonPriceRepo:
    def search(self, filters):
        return [
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-23", "price_type": "retail", "price_krw": 9200},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-24", "price_type": "retail", "price_krw": 9350},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-25", "price_type": "retail", "price_krw": 9400},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-28", "price_type": "retail", "price_krw": 9569},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-29", "price_type": "retail", "price_krw": 9400},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-30", "price_type": "retail", "price_krw": 9169.85},
        ]


class EmptyOnlineRepo:
    def search_summaries(self, **kwargs):
        return []


class PartialMelonOnlineRepo:
    def search_summaries(self, **kwargs):
        if kwargs.get("item_code") not in {None, "257"}:
            return []
        return [
            {
                "item_code": "257",
                "kind_code": "00",
                "platform": "naver",
                "average_unit_price": "9050",
                "observed_date": "2026-09-29",
            },
            {
                "item_code": "257",
                "kind_code": "00",
                "platform": "coupang",
                "average_unit_price": "6650",
                "observed_date": "2026-09-30",
            },
        ]


class EmptyMarketRepo:
    def search(self, **kwargs):
        return []


def test_melon_chart_fills_all_online_gaps_and_preserves_existing_values() -> None:
    service = ComparisonService(
        MelonPriceRepo(), PartialMelonOnlineRepo(), EmptyMarketRepo(), AnalyticsService()
    )

    result = service.chart("257", date(2026, 9, 23), date(2026, 9, 30), "raw")

    assert result["dates"] == [
        "2026-09-23",
        "2026-09-24",
        "2026-09-25",
        "2026-09-26",
        "2026-09-27",
        "2026-09-28",
        "2026-09-29",
        "2026-09-30",
    ]
    assert result["estimated_series"] == [
        "online_naver",
        "online_coupang",
        "online_combined",
    ]
    assert all(value is not None for value in result["series"]["online_naver"])
    assert all(value is not None for value in result["series"]["online_coupang"])
    assert result["series"]["online_naver"][6] == 9050.0
    assert result["series"]["online_coupang"][7] == 6650.0
    assert any("추정치" in note for note in result["comparison_notes"])


def test_melon_seed_estimates_cover_every_day_from_sep_23_to_sep_30() -> None:
    path = Path(__file__).resolve().parents[2] / "data" / "normalized" / "online_price_summaries.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["item_code"] == "257"]

    expected_dates = {
        (date(2026, 9, 23) + timedelta(days=offset)).isoformat()
        for offset in range(8)
    }
    for platform in ("naver", "coupang", "combined"):
        platform_rows = [row for row in rows if row["platform"] == platform]
        assert {row["observed_date"] for row in platform_rows} == expected_dates
        assert all(row["average_unit_price"] for row in platform_rows)
        assert all(row["collection_status"] == "estimated" for row in platform_rows)


def test_melon_correlations_exclude_dashboard_estimates() -> None:
    service = ComparisonService(
        MelonPriceRepo(), EmptyOnlineRepo(), EmptyMarketRepo(), AnalyticsService()
    )

    rows = service.correlations(
        "257",
        "kamis_retail",
        date(2026, 9, 23),
        date(2026, 9, 30),
        "return_1d",
    )

    assert all(not row["comparison_series"].startswith("online_") for row in rows)
