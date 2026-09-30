from datetime import date

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


class MelonPriceRepo:
    def search(self, filters):
        return [
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-24", "price_type": "retail", "price_krw": 9800},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-25", "price_type": "retail", "price_krw": 9600},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-28", "price_type": "retail", "price_krw": 9900},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-29", "price_type": "retail", "price_krw": 9400},
            {"item_code": "257", "kind_code": "00", "observed_date": "2026-09-30", "price_type": "retail", "price_krw": 9169.85},
        ]


class EmptyOnlineRepo:
    def search_summaries(self, **kwargs):
        return []


class EmptyMarketRepo:
    def search(self, **kwargs):
        return []


def test_melon_chart_generates_lagged_dashboard_only_online_estimates() -> None:
    service = ComparisonService(
        MelonPriceRepo(), EmptyOnlineRepo(), EmptyMarketRepo(), AnalyticsService()
    )

    result = service.chart("257", date(2026, 9, 24), date(2026, 9, 30), "raw")

    assert result["estimated_series"] == [
        "online_naver",
        "online_coupang",
        "online_combined",
    ]
    assert result["series"]["online_naver"][0] is None
    assert result["series"]["online_coupang"][:2] == [None, None]
    assert result["series"]["online_naver"][2] > result["series"]["online_naver"][1]
    assert result["series"]["online_coupang"][3] > result["series"]["online_coupang"][2]
    assert any("추정치" in note for note in result["comparison_notes"])


def test_melon_correlations_exclude_dashboard_estimates() -> None:
    service = ComparisonService(
        MelonPriceRepo(), EmptyOnlineRepo(), EmptyMarketRepo(), AnalyticsService()
    )

    rows = service.correlations(
        "257",
        "kamis_retail",
        date(2026, 9, 24),
        date(2026, 9, 30),
        "return_1d",
    )

    assert all(not row["comparison_series"].startswith("online_") for row in rows)
