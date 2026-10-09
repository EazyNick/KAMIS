from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


def test_melon_dashboard_keeps_kamis_krw_exactly_as_collected():
    class MelonPrices:
        def search(self, filters):
            assert filters.requested_convert_kg is False
            return [
                {
                    "item_code": "257",
                    "kind_code": "00",
                    "observed_date": "2026-10-08",
                    "price_type": "retail",
                    "rank_code": "04",
                    "region": "서울",
                    "market_name": "테스트시장",
                    "price_krw": 28980.57,
                }
            ]

    class OnlineMustNotBeUsed:
        def search_summaries(self, **kwargs):
            raise AssertionError("online comparison is disabled")

    service = ComparisonService(
        MelonPrices(),
        OnlineMustNotBeUsed(),
        type("Market", (), {"search": lambda self, **kwargs: []})(),
        AnalyticsService(),
        target_keys={("257", "00")},
    )

    result = service.chart("257", None, None, "raw")

    assert result["series"]["kamis_retail"] == [28980.57]
    assert "online_naver" not in result["series"]
    assert "online_coupang" not in result["series"]
    assert "online_combined" not in result["series"]
