from app.infrastructure.csv_repository import PriceFilters
from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


def test_dashboard_does_not_apply_shopping_unit_conversion_to_kamis_prices():
    original_price = 28980.57

    class Prices:
        def search(self, filters: PriceFilters):
            assert filters.requested_convert_kg is False
            return [
                {
                    "item_code": "257",
                    "kind_code": "00",
                    "observed_date": "2026-10-08",
                    "price_type": "retail",
                    "price_krw": original_price,
                    "region": "서울",
                }
            ]

    service = ComparisonService(
        Prices(),
        object(),
        type("Market", (), {"search": lambda self, **kwargs: []})(),
        AnalyticsService(),
        target_keys={("257", "00")},
    )

    chart = service.chart("257", None, None, "raw")

    assert chart["series"]["kamis_retail"] == [original_price]
    assert chart["raw_series"]["kamis_retail"] == [original_price]
