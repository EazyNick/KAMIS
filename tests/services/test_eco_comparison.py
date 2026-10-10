from datetime import date
from types import SimpleNamespace

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


def test_eco_price_is_a_separate_series_with_observed_coverage():
    rows = [
        {"observed_date": "2026-09-01", "kind_code": "01", "price_type": "eco",
         "rank_code": "07", "region": "평균", "price_krw": 18600},
        {"observed_date": "2026-09-08", "kind_code": "01", "price_type": "eco",
         "rank_code": "07", "region": "평균", "price_krw": 20071},
    ]
    service = ComparisonService(
        SimpleNamespace(search=lambda filters: rows), None,
        SimpleNamespace(search=lambda **kwargs: []), AnalyticsService(),
    )
    chart = service.chart("114", date(2026, 9, 1), date(2026, 9, 30), "raw")
    assert chart["series"]["kamis_eco"] == [18600, 20071]
    assert chart["series"]["kamis_retail"] == [None, None]
    assert chart["kamis_coverage"]["kamis_eco"]["observations"] == 2
    assert chart["kamis_selected_ranks"]["eco"] == "07"
