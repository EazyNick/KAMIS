from datetime import date
from types import SimpleNamespace

import pytest

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


class PriceRepo:
    def search(self, filters):
        assert filters.requested_convert_kg is False
        return [
            {
                "item_code": "257",
                "kind_code": "00",
                "observed_date": "2026-09-23",
                "price_type": "retail",
                "rank_code": "04",
                "price_krw": 28980.57,
                "region": "평균",
            },
            {
                "item_code": "257",
                "kind_code": "00",
                "observed_date": "2026-09-24",
                "price_type": "retail",
                "rank_code": "04",
                "price_krw": 30000,
                "region": "평균",
            },
            {
                "item_code": "257",
                "kind_code": "00",
                "observed_date": "2026-09-24",
                "price_type": "wholesale",
                "rank_code": "04",
                "price_krw": 42000,
                "region": "평균",
            },
        ]


class EmptyOnlineRepo:
    def search_summaries(self, **kwargs):
        raise AssertionError("online prices must not participate in comparison")


class MarketRepo:
    def search(self, **kwargs):
        return [
            {"observed_date": "2026-09-23", "series_id": "kospi", "close": 2600},
            {"observed_date": "2026-09-24", "series_id": "kospi", "close": 2610},
        ]


def service():
    return ComparisonService(
        PriceRepo(),
        EmptyOnlineRepo(),
        MarketRepo(),
        AnalyticsService(),
        target_keys={("257", "00")},
    )


def test_comparison_chart_uses_raw_kamis_prices_without_unit_conversion() -> None:
    result = service().chart(
        "257", date(2026, 9, 1), date(2026, 9, 30), "raw"
    )

    assert result["dates"] == ["2026-09-23", "2026-09-24"]
    assert result["series"]["kamis_retail"] == [28980.57, 30000.0]
    assert result["series"]["kamis_wholesale"] == [None, 42000.0]
    assert result["series"]["kospi"] == [2600.0, 2610.0]
    assert "online_naver" not in result["series"]
    assert any("p_convert_kg_yn=N" in note for note in result["comparison_notes"])


def test_comparison_uses_kamis_official_average_instead_of_regional_mean() -> None:
    rows = [
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "retail",
            "rank_code": "04",
            "price_krw": 13516.45,
            "region": "평균",
            "market_name": None,
        },
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "retail",
            "rank_code": "04",
            "price_krw": 5000,
            "region": "서울",
            "market_name": "A-유통",
        },
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "retail",
            "rank_code": "04",
            "price_krw": 21000,
            "region": "포항",
            "market_name": "죽도",
        },
    ]
    comparison = ComparisonService(
        SimpleNamespace(search=lambda filters: rows),
        EmptyOnlineRepo(),
        SimpleNamespace(search=lambda **kwargs: []),
        AnalyticsService(),
        target_keys={("257", "00")},
    )

    result = comparison.chart("257", None, None, "raw")

    assert result["series"]["kamis_retail"] == [13516.45]
    assert any(
        "region=평균" in note
        for note in result["comparison_notes"]
    )


def test_comparison_prefers_rank_04_and_exposes_survey_units() -> None:
    rows = [
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "retail",
            "rank_code": "04",
            "price_krw": 16000,
            "region": "평균",
        },
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "retail",
            "rank_code": "05",
            "price_krw": 8000,
            "region": "평균",
        },
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "wholesale",
            "rank_code": "04",
            "price_krw": 44000,
            "region": "평균",
        },
        {
            "item_code": "257",
            "kind_code": "00",
            "observed_date": "2026-05-14",
            "price_type": "wholesale",
            "rank_code": "05",
            "price_krw": 33000,
            "region": "평균",
        },
    ]
    catalog_entry = SimpleNamespace(
        item_code="257",
        kind_code="00",
        wholesale_rank_codes=("04", "05"),
        retail_rank_codes=("04", "05"),
        wholesale_unit="kg",
        wholesale_unit_size="8",
        retail_unit="개",
        retail_unit_size="1",
    )
    comparison = ComparisonService(
        SimpleNamespace(search=lambda filters: rows),
        EmptyOnlineRepo(),
        SimpleNamespace(search=lambda **kwargs: []),
        AnalyticsService(),
        target_keys={("257", "00")},
        catalog_repository=SimpleNamespace(entries=lambda: [catalog_entry]),
    )

    result = comparison.chart("257", None, None, "raw")

    assert result["series"]["kamis_retail"] == [16000.0]
    assert result["series"]["kamis_wholesale"] == [44000.0]
    assert result["kamis_selected_ranks"] == {
        "wholesale": "04",
        "retail": "04",
    }
    assert result["series_labels"]["kamis_wholesale"] == "KAMIS 도매 (8kg)"
    assert result["series_labels"]["kamis_retail"] == "KAMIS 소매 (1개)"


def test_base100_uses_first_raw_observation_once_for_entire_range() -> None:
    result = service().chart(
        "257", date(2026, 9, 1), date(2026, 9, 30), "base100"
    )

    assert result["series"]["kamis_retail"] == pytest.approx(
        [100.0, 30000 / 28980.57 * 100]
    )
    assert result["raw_series"]["kamis_retail"] == [28980.57, 30000.0]
    assert result["raw_series"]["kospi"] == [2600.0, 2610.0]


def test_dashboard_defaults_use_raw_kamis_date_stats_only() -> None:
    class DateStatsRepo:
        def item_date_stats(self, *, requested_convert_kg=None):
            assert requested_convert_kg is False
            return {"257": (date(2009, 5, 4), date(2026, 10, 8), 1000)}

    comparison = ComparisonService(
        DateStatsRepo(),
        EmptyOnlineRepo(),
        MarketRepo(),
        AnalyticsService(),
    )

    assert comparison.dashboard_defaults() == {
        "item_code": "257",
        "start_date": "2009-05-04",
        "end_date": "2026-10-08",
        "mode": "base100",
    }


def test_catalog_selects_one_kind_without_unit_conversion_rules() -> None:
    entries = [
        SimpleNamespace(
            item_code="121",
            kind_code="02",
            wholesale_rank_codes=(),
            retail_rank_codes=(),
        ),
        SimpleNamespace(
            item_code="121",
            kind_code="04",
            wholesale_rank_codes=("04",),
            retail_rank_codes=("04",),
        ),
    ]
    comparison = ComparisonService(
        SimpleNamespace(search=lambda filters: []),
        EmptyOnlineRepo(),
        SimpleNamespace(search=lambda **kwargs: []),
        AnalyticsService(),
        catalog_repository=SimpleNamespace(entries=lambda: entries),
    )

    assert comparison.comparison_kinds["121"] == "04"
