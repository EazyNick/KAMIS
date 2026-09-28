from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.models import PriceObservation, PriceType
from app.domain.online_models import MatchStatus, PlatformPriceSummary, ShoppingOffer
from app.infrastructure.csv_repository import PriceFilters, PriceRepository
from app.infrastructure.market_data import MarketObservation, MarketRepository
from app.infrastructure.online_repository import OnlinePriceRepository
from log import app_logger


def _price(observed_date: date, value: str) -> PriceObservation:
    return PriceObservation(
        price_type=PriceType.RETAIL,
        observed_date=observed_date,
        collected_at=datetime(2026, 9, 28, 9, tzinfo=ZoneInfo("Asia/Seoul")),
        category_code="100",
        item_code="111",
        kind_code="01",
        rank_code="04",
        item_name="쌀",
        variety="20kg",
        region="서울",
        market_name="A-유통",
        price_krw=Decimal(value),
        requested_convert_kg=True,
    )


def _offer(platform: str, observed_date: date, product_id: str, value: str) -> ShoppingOffer:
    return ShoppingOffer(
        platform=platform,
        product_id=product_id,
        title="쌀 1kg",
        url=f"https://example.test/{product_id}",
        item_code="111",
        kind_code="01",
        match_status=MatchStatus.EXACT,
        base_price=Decimal(value),
        member_price=None,
        member_discount_scope=None,
        shipping_fee=Decimal("0"),
        quantity=Decimal("1"),
        unit="kg",
        available=True,
        observed_date=observed_date,
    )


def test_kamis_price_history_is_not_deleted_by_newer_collection(tmp_path) -> None:
    repository = PriceRepository(tmp_path, app_logger)
    repository.upsert([_price(date(2026, 9, 27), "1000")], "day-1")
    repository.upsert([_price(date(2026, 9, 28), "1100")], "day-2")

    rows = repository.search(PriceFilters(item_code="111"))
    assert [(row["observed_date"], row["price_krw"]) for row in rows] == [
        ("2026-09-27", 1000.0),
        ("2026-09-28", 1100.0),
    ]


def test_market_history_is_not_deleted_by_newer_collection(tmp_path) -> None:
    repository = MarketRepository(tmp_path, app_logger)
    collected_at = datetime(2026, 9, 28, 9, tzinfo=ZoneInfo("Asia/Seoul"))
    repository.upsert(
        [MarketObservation("sp500", "^GSPC", date(2026, 9, 25), 6700.0, "index", "index points", collected_at)],
        "day-1",
    )
    repository.upsert(
        [MarketObservation("sp500", "^GSPC", date(2026, 9, 28), 6750.0, "index", "index points", collected_at)],
        "day-2",
    )

    rows = repository.search(series_id="sp500")
    assert [(row["observed_date"], row["close"]) for row in rows] == [
        ("2026-09-25", 6700.0),
        ("2026-09-28", 6750.0),
    ]


def test_naver_and_coupang_history_is_not_deleted_by_newer_collection(tmp_path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)

    for observed_date, suffix in ((date(2026, 9, 27), "old"), (date(2026, 9, 28), "new")):
        offers = [
            _offer("naver", observed_date, f"naver-{suffix}", "1000"),
            _offer("coupang", observed_date, f"coupang-{suffix}", "900"),
        ]
        summaries = [
            PlatformPriceSummary("naver", "111", "01", Decimal("1000"), 1, 1, (offers[0],), ()),
            PlatformPriceSummary("coupang", "111", "01", Decimal("900"), 1, 1, (offers[1],), ()),
        ]
        repository.save_daily(offers, summaries, observed_date, f"run-{suffix}")

    rows = repository.search_summaries(item_code="111")
    assert {(row["observed_date"], row["platform"]) for row in rows} == {
        ("2026-09-27", "naver"),
        ("2026-09-27", "coupang"),
        ("2026-09-28", "naver"),
        ("2026-09-28", "coupang"),
    }
