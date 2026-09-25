from datetime import date

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
            ]

    service = ComparisonService(
        HolidayPriceRepo(), OnlineRepo(), HolidayMarketRepo(), AnalyticsService()
    )

    result = service.chart("111", None, None, "raw")

    assert result["series"]["sp500"] == [100.0, 100.0, 101.0, 110.0, None, 112.0]


def test_dashboard_defaults_prefer_online_item_and_bound_window_to_90_days() -> None:
    service = ComparisonService(
        DefaultPriceRepo(), DefaultOnlineRepo(), MarketRepo(), AnalyticsService()
    )

    assert service.dashboard_defaults() == {
        "item_code": "111",
        "start_date": "2026-06-27",
        "end_date": "2026-09-24",
        "mode": "base100",
    }
