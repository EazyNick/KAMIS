from datetime import date
from types import SimpleNamespace

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


def service(rows):
    return ComparisonService(
        SimpleNamespace(search=lambda filters: rows),
        SimpleNamespace(search_summaries=lambda **kw: []),
        SimpleNamespace(search=lambda **kw: []),
        AnalyticsService(),
    )


def test_grain_chart_selects_one_measured_variety_instead_of_mixing_units():
    rows = [
        {
            "kind_code": "02",
            "observed_date": "2026-09-23",
            "price_type": "retail",
            "price_krw": 20000,
        },
        {
            "kind_code": "04",
            "observed_date": "2026-09-23",
            "price_type": "retail",
            "price_krw": 3000,
        },
    ]
    entries = [
        SimpleNamespace(
            to_dict=lambda: {
                "category_code": "100",
                "item_code": "121",
                "kind_code": "02",
                "retail_unit": "",
                "retail_unit_size": "",
            }
        ),
        SimpleNamespace(
            to_dict=lambda: {
                "category_code": "100",
                "item_code": "121",
                "kind_code": "04",
                "retail_unit": "kg",
                "retail_unit_size": "1",
                "retail_rank_codes": "04",
            }
        ),
    ]
    chart_service = ComparisonService(
        SimpleNamespace(search=lambda filters: rows),
        SimpleNamespace(search_summaries=lambda **kw: []),
        SimpleNamespace(search=lambda **kw: []),
        AnalyticsService(),
        catalog_repository=SimpleNamespace(entries=lambda: entries),
    )
    result = chart_service.chart("121", None, None, "raw")
    assert result["comparison_kinds"]["121"] == "04"
    assert result["series"]["kamis_retail"] == [3000]


def test_short_kamis_history_is_reported_without_filling_earlier_years():
    chart = service(
        [{"observed_date": "2026-09-23", "price_type": "retail", "price_krw": 1000}]
    ).chart("112", date(2006, 1, 1), date(2026, 10, 4), "base100")
    assert chart["kamis_coverage"]["kamis_retail"]["first_date"] == "2026-09-23"
    assert chart["dates"] == ["2026-09-23"]
    assert any("2026-09-23" in note for note in chart["comparison_notes"])


def test_empty_kamis_history_is_explicit_even_without_online_target():
    chart = service([]).chart("161", date(2006, 1, 1), date(2026, 10, 4), "base100")
    assert chart["kamis_coverage"]["kamis_retail"]["observations"] == 0
    assert any(
        "KAMIS 관측 가격이 없습니다" in note for note in chart["comparison_notes"]
    )


def test_kamis_coverage_does_not_count_carried_holiday_values_as_observations():
    chart_service = ComparisonService(
        SimpleNamespace(
            search=lambda filters: [
                {
                    "observed_date": "2026-09-23",
                    "price_type": "retail",
                    "price_krw": 1000,
                }
            ]
        ),
        SimpleNamespace(search_summaries=lambda **kw: []),
        SimpleNamespace(
            search=lambda **kw: [
                {"observed_date": "2026-09-24", "series_id": "sp500", "close": 5000}
            ]
        ),
        AnalyticsService(),
    )
    result = chart_service.chart("112", None, None, "raw")
    assert result["series"]["kamis_retail"] == [1000, 1000]
    assert result["kamis_coverage"]["kamis_retail"] == {
        "first_date": "2026-09-23",
        "last_date": "2026-09-23",
        "observations": 1,
    }
