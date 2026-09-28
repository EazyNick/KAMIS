from datetime import date

from app.services.analytics import AnalyticsService
from app.services.comparison import ComparisonService


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
