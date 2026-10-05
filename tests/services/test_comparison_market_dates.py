from datetime import date

from app.services.analytics import AnalyticsService
from app.services.comparison import MARKET_EXCHANGES, ComparisonService


def test_kamis_holidays_continue_prices_but_open_day_gaps_remain():
    import pandas as pd

    from app.services.comparison import fill_exchange_holidays

    dates = pd.to_datetime([
        "2026-07-16", "2026-07-17", "2026-07-20",
        "2026-08-14", "2026-08-17", "2026-08-18",
        "2026-09-23", "2026-09-24", "2026-09-25",
        "2026-09-26", "2026-09-27", "2026-09-28",
    ])
    frame = pd.DataFrame({
        "kamis_retail": [100, None, None, 110, None, 120, 130, None, None, None, None, 140],
        "kamis_wholesale": [90, 91, None, 100, None, 110, 120, None, None, None, None, 130],
        "online_naver": [None] * 12,
    }, index=dates)
    result = fill_exchange_holidays(frame)
    assert result.loc["2026-07-17", "kamis_retail"] == 100
    assert result.loc["2026-07-17", "kamis_wholesale"] == 91
    assert pd.isna(result.loc["2026-07-20", "kamis_retail"])
    assert result.loc["2026-08-17", "kamis_retail"] == 110
    assert result.loc["2026-09-24":"2026-09-27", "kamis_retail"].tolist() == [130] * 4
    assert result["online_naver"].isna().all()
    assert pd.isna(frame.loc["2026-07-17", "kamis_retail"])


def test_all_market_series_fill_weekend_closures_but_keep_weekday_gaps():
    import pandas as pd

    from app.services.comparison import MARKET_EXCHANGES, fill_exchange_holidays

    expected_series = {
        "kospi",
        "kosdaq",
        "sp500",
        "nasdaq",
        "dow_jones",
        "usd_krw",
        "corn_futures",
        "wheat_futures",
        "soybean_futures",
        "rough_rice_futures",
        "coffee_futures",
        "sugar_futures",
        "cotton_futures",
        "orange_juice_futures",
    }
    assert set(MARKET_EXCHANGES) == expected_series

    dates = pd.to_datetime(
        [
            "2026-09-25",  # Friday
            "2026-09-26",  # Saturday
            "2026-09-27",  # Sunday
            "2026-09-28",  # Monday
            "2026-09-29",  # Tuesday
        ]
    )
    frame = pd.DataFrame(
        {
            series_id: [100.0, None, None, 110.0, None]
            for series_id in expected_series
        },
        index=dates,
    )

    result = fill_exchange_holidays(frame)

    for series_id in expected_series:
        assert result.loc["2026-09-26", series_id] == 100.0
        assert result.loc["2026-09-27", series_id] == 100.0
        assert result.loc["2026-09-28", series_id] == 110.0
        assert pd.isna(result.loc["2026-09-29", series_id])


class OneDayPriceRepo:
    def search(self, filters):
        return [
            {
                "observed_date": "2026-09-28",
                "price_type": "retail",
                "price_krw": 1000,
            }
        ]


class EmptyOnlineRepo:
    def search_summaries(self, **kwargs):
        return []


class HistoricalMarketRepo:
    def search(self, **kwargs):
        return [
            {"observed_date": "2026-09-24", "series_id": "kospi", "close": 2600},
            {"observed_date": "2026-09-25", "series_id": "kospi", "close": 2610},
            {"observed_date": "2026-09-28", "series_id": "kospi", "close": 2620},
        ]


class WeekendOnlineRepo:
    def search_summaries(self, **kwargs):
        return [
            {
                "observed_date": observed_date,
                "platform": "naver",
                "average_unit_price": "1000",
            }
            for observed_date in ("2026-09-26", "2026-09-27")
        ]


class AllMarketWeekendRepo:
    def search(self, **kwargs):
        return [
            {
                "observed_date": observed_date,
                "series_id": series_id,
                "close": close,
            }
            for series_id in MARKET_EXCHANGES
            for observed_date, close in (
                ("2026-09-25", 100.0),
                ("2026-09-28", 110.0),
            )
        ]


def test_chart_payload_keeps_all_market_series_continuous_across_weekend() -> None:
    service = ComparisonService(
        OneDayPriceRepo(),
        WeekendOnlineRepo(),
        AllMarketWeekendRepo(),
        AnalyticsService(),
    )

    result = service.chart(
        "111", date(2026, 9, 25), date(2026, 9, 28), "raw"
    )

    assert result["dates"] == [
        "2026-09-25",
        "2026-09-26",
        "2026-09-27",
        "2026-09-28",
    ]
    for series_id in MARKET_EXCHANGES:
        assert result["series"][series_id] == [100.0, 100.0, 100.0, 110.0]


def test_market_history_dates_extend_chart_timeline() -> None:
    service = ComparisonService(
        OneDayPriceRepo(), EmptyOnlineRepo(), HistoricalMarketRepo(), AnalyticsService()
    )

    result = service.chart(
        "111", date(2026, 9, 24), date(2026, 9, 28), "raw"
    )

    assert result["dates"] == ["2026-09-24", "2026-09-25", "2026-09-28"]
    assert result["series"]["kamis_retail"] == [None, None, 1000.0]
    assert result["series"]["kospi"] == [2600.0, 2610.0, 2620.0]
