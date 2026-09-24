from datetime import date
from decimal import Decimal
from pathlib import Path

from app.domain.online_models import MatchStatus, PlatformPriceSummary, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
from log import app_logger


def test_online_repository_persists_offers_and_summary(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    row = ShoppingOffer(
        platform="naver",
        product_id="p1",
        title="쌀 1kg",
        url="https://example.test/p1",
        item_code="111",
        kind_code="01",
        match_status=MatchStatus.EXACT,
        base_price=Decimal(1000),
        member_price=None,
        member_discount_scope=None,
        shipping_fee=Decimal(0),
        quantity=Decimal(1),
        unit="kg",
        available=True,
        observed_date=date(2026, 9, 24),
    )
    summary = PlatformPriceSummary(
        "naver", "111", "01", Decimal(1000), 1, 1, (row,), ()
    )

    repository.save_daily([row], [summary], date(2026, 9, 24), "run-1")

    assert repository.search_offers(item_code="111")[0]["platform"] == "naver"
    assert repository.search_summaries(item_code="111")[0]["sample_count"] == "1"
