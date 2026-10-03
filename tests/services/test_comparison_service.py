from datetime import date

import pytest

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


class PriceRepo:
    def search(self, filters):
        return [
            {"observed_date": "2026-09-23", "price_type": "retail", "price_krw": 1000},
            {"observed_date": "2026-09-24", "price_type": "retail", "price_krw": 1100},
            {
                "observed_date": "2026-09-24",
                "price_type": "wholesale",
                "price_krw": 900,
            },
        ]


class OnlineRepo:
    def search_summaries(self, **kwargs):
        return [
            {
                "observed_date": "2026-09-24",
                "platform": "naver",
                "average_unit_price": "1200",
            },
            {
                "observed_date": "2026-09-24",
                "platform": "combined",
                "average_unit_price": "1250",
            },
        ]


class MarketRepo:
    def search(self, **kwargs):
        return [
            {"observed_date": "2026-09-23", "series_id": "kospi", "close": 2600},
            {"observed_date": "2026-09-24", "series_id": "kospi", "close": 2610},
        ]


class DefaultPriceRepo:
    def search(self, filters):
        return [
            {
                "item_code": "111",
                "observed_date": "2000-01-01",
                "price_type": "retail",
                "price_krw": 900,
            },
            {
                "item_code": "111",
                "observed_date": "2026-01-01",
                "price_type": "retail",
                "price_krw": 1000,
            },
            {
                "item_code": "111",
                "observed_date": "2026-09-24",
                "price_type": "retail",
                "price_krw": 1100,
            },
            {
                "item_code": "222",
                "observed_date": "2026-09-25",
                "price_type": "retail",
                "price_krw": 900,
            },
        ]


class DefaultOnlineRepo:
    def search_summaries(self, **kwargs):
        return [
            {
                "item_code": "111",
                "platform": "naver",
                "average_unit_price": "1200",
                "observed_date": "2026-09-24",
            },
            {
                "item_code": "222",
                "platform": "naver",
                "average_unit_price": None,
                "observed_date": "2026-09-25",
            },
        ]


def test_comparison_chart_uses_kamis_observation_dates_and_all_series() -> None:
    service = ComparisonService(
        PriceRepo(), OnlineRepo(), MarketRepo(), AnalyticsService()
    )
    result = service.chart("111", date(2026, 9, 1), date(2026, 9, 30), "raw")

    assert result["dates"] == ["2026-09-23", "2026-09-24"]
    assert result["series"]["kamis_retail"] == [1000.0, 1100.0]
    assert result["series"]["online_naver"] == [None, 1200.0]
    assert result["series"]["kospi"] == [2600.0, 2610.0]


def test_base100_chart_keeps_raw_values_for_tooltips() -> None:
    service = ComparisonService(
        PriceRepo(), OnlineRepo(), MarketRepo(), AnalyticsService()
    )

    result = service.chart(
        "111", date(2026, 9, 1), date(2026, 9, 30), "base100"
    )

    assert result["series"]["kamis_retail"] == pytest.approx([100.0, 110.0])
    assert result["raw_series"]["kamis_retail"] == [1000.0, 1100.0]
    assert result["raw_series"]["kospi"] == [2600.0, 2610.0]


def test_comparison_fills_exchange_holiday_but_not_missing_open_session() -> None:
    class HolidayPriceRepo:
        def search(self, filters):
            return [
                {
                    "observed_date": observed_date,
                    "price_type": "retail",
                    "price_krw": 1000,
                }
                for observed_date in (
                    "2026-07-02",
                    "2026-07-03",
                    "2026-07-06",
                    "2026-09-21",
                    "2026-09-22",
                    "2026-09-23",
                )
            ]

    class HolidayMarketRepo:
        def search(self, **kwargs):
            return [
                {"observed_date": "2026-07-02", "series_id": "sp500", "close": 100},
                {"observed_date": "2026-07-06", "series_id": "sp500", "close": 101},
                {"observed_date": "2026-09-21", "series_id": "sp500", "close": 110},
                {"observed_date": "2026-09-23", "series_id": "sp500", "close": 112},
                {
                    "observed_date": "2026-07-02",
                    "series_id": "corn_futures",
                    "close": 500,
                },
                {
                    "observed_date": "2026-07-06",
                    "series_id": "corn_futures",
                    "close": 510,
                },
                {
                    "observed_date": "2026-09-21",
                    "series_id": "corn_futures",
                    "close": 520,
                },
                {
                    "observed_date": "2026-09-23",
                    "series_id": "corn_futures",
                    "close": 530,
                },
            ]

    service = ComparisonService(
        HolidayPriceRepo(), OnlineRepo(), HolidayMarketRepo(), AnalyticsService()
    )

    result = service.chart("111", None, None, "raw")

    assert result["series"]["sp500"] == [100.0, 100.0, 101.0, 110.0, None, 112.0, None]
    assert result["series"]["corn_futures"] == [
        500.0,
        500.0,
        510.0,
        520.0,
        None,
        530.0,
        None,
    ]


def test_dashboard_defaults_prefer_online_item_and_use_available_20_year_window() -> None:
    service = ComparisonService(
        DefaultPriceRepo(), DefaultOnlineRepo(), MarketRepo(), AnalyticsService()
    )

    assert service.dashboard_defaults() == {
        "item_code": "111",
        "start_date": "2006-09-24",
        "end_date": "2026-09-24",
        "mode": "base100",
    }


class WeekendOnlineRepo:
    def search_summaries(self, **kwargs):
        return [
            {"item_code": "111", "observed_date": "2026-09-27", "platform": platform, "average_unit_price": value}
            for platform, value in (("naver", "42420"), ("coupang", "35930"), ("combined", "51160"))
        ]


def test_comparison_keeps_configured_rice_weight_separate():
    class RicePrices:
        def search(self, filters):
            return [
                {"observed_date": "2026-09-24", "price_type": "retail", "kind_code": kind, "price_krw": price}
                for kind, price in (("01", 60000), ("10", 30000))
            ]

    class RiceOnline:
        def search_summaries(self, **kwargs):
            return [
                {"observed_date": "2026-09-24", "platform": platform, "kind_code": kind, "average_unit_price": price}
                for platform in ("naver", "coupang")
                for kind, price in (("01", 80000), ("10", 40000))
            ]

    service = ComparisonService(RicePrices(), RiceOnline(), MarketRepo(), AnalyticsService(), target_keys={("111", "10")})
    result = service.chart("111", None, None, "raw")
    assert result["series"]["kamis_retail"] == [30000]
    assert result["series"]["online_naver"] == [40000]
    assert result["series"]["online_coupang"] == [40000]
    assert result["comparison_kinds"] == {"111": "10"}

    class CachedAnalytics:
        def read_comparison_series(self, items, mode="base100"):
            return [{"item_code": "111", "observed_date": "2026-09-24", "series_id": "kamis_retail", "value": 60000}]

    from app.services.dashboard_bootstrap import DashboardBootstrapService
    payload = DashboardBootstrapService(CachedAnalytics(), service, ("111",)).load()
    assert payload["chart"]["raw_series"]["kamis_retail"] == [30000]


def test_online_weekend_prices_remain_visible_and_respect_date_filter():
    service = ComparisonService(PriceRepo(), WeekendOnlineRepo(), MarketRepo(), AnalyticsService())
    result = service.chart("111", date(2026, 9, 1), date(2026, 9, 27), "raw")
    assert result["dates"][-1] == "2026-09-27"
    assert result["series"]["online_naver"][-1] == 42420
    assert result["series"]["online_coupang"][-1] == 35930
    assert result["series"]["online_combined"][-1] == 39175
    assert result["series"]["kamis_retail"][-1] == 1100
    earlier = service.chart("111", None, date(2026, 9, 24), "raw")
    assert "2026-09-27" not in earlier["dates"]


def test_defaults_include_latest_online_date():
    service = ComparisonService(DefaultPriceRepo(), WeekendOnlineRepo(), MarketRepo(), AnalyticsService())
    assert service.dashboard_defaults()["end_date"] == "2026-09-27"


def test_bootstrap_overlays_fresh_online_prices_on_cached_chart():
    from app.services.dashboard_bootstrap import DashboardBootstrapService

    class CachedAnalytics:
        def read_comparison_series(self, items, mode="base100"):
            return [{"item_code": "111", "observed_date": "2026-09-23", "series_id": "kamis_retail", "value": 100 if mode == "base100" else 1000}]

    comparison = ComparisonService(PriceRepo(), WeekendOnlineRepo(), MarketRepo(), AnalyticsService())
    payload = DashboardBootstrapService(CachedAnalytics(), comparison, ("111",)).load()
    assert payload["defaults"]["end_date"] == "2026-09-27"
    assert payload["chart"]["series"]["online_naver"][-1] == 100
    assert payload["chart"]["raw_series"]["online_coupang"][-1] == 35930


def test_dashboard_defaults_prefer_melon_with_available_history_window():
    class MelonPrices:
        def search(self, filters):
            return [{"item_code": "257", "observed_date": "2026-09-30", "price_krw": 5000}]
    service = ComparisonService(MelonPrices(), DefaultOnlineRepo(), MarketRepo(), AnalyticsService())
    defaults = service.dashboard_defaults()
    assert defaults["item_code"] == "257"
    assert defaults["start_date"] == "2026-09-30"
    assert defaults["end_date"] == "2026-09-30"
