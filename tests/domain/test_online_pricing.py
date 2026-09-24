from decimal import Decimal

from app.domain.online_models import MatchStatus, ShoppingOffer
from app.services.online_pricing import OnlinePriceCalculator


def offer(
    price: str,
    *,
    platform: str = "naver",
    shipping: str = "0",
    member_price: str | None = None,
    member_scope: str | None = None,
    status: MatchStatus = MatchStatus.EXACT,
) -> ShoppingOffer:
    return ShoppingOffer(
        platform=platform,
        product_id=f"id-{price}-{shipping}",
        title="쌀 일반 1kg",
        url="https://example.test/product",
        item_code="111",
        kind_code="01",
        match_status=status,
        base_price=Decimal(price),
        member_price=Decimal(member_price) if member_price else None,
        member_discount_scope=member_scope,
        shipping_fee=Decimal(shipping),
        quantity=Decimal(1),
        unit="kg",
        available=True,
    )


def test_all_member_discount_and_shipping_are_included() -> None:
    row = offer(
        "12000", shipping="3000", member_price="10000", member_scope="all_members"
    )
    assert row.comparable_total == Decimal(13000)
    assert row.unit_price == Decimal(13000)


def test_private_or_card_discount_is_not_used() -> None:
    row = offer("12000", member_price="9000", member_scope="specific_payment_method")
    assert row.comparable_total == Decimal(12000)


def test_repeated_low_outliers_are_removed_then_up_to_five_are_averaged() -> None:
    rows = [
        offer(str(value)) for value in (100, 500, 1000, 1010, 1020, 1030, 1040, 1050)
    ]
    summary = OnlinePriceCalculator().summarize("naver", "111", "01", rows)

    assert [item.unit_price for item in summary.included_offers] == [
        Decimal(1000),
        Decimal(1010),
        Decimal(1020),
        Decimal(1030),
        Decimal(1040),
    ]
    assert summary.average_unit_price == Decimal(1020)
    assert len(summary.excluded_offers) == 3


def test_fewer_than_five_uses_remaining_comparable_items() -> None:
    rows = [offer(str(value)) for value in (100, 1000, 1100)]
    summary = OnlinePriceCalculator().summarize("naver", "111", "01", rows)
    assert summary.average_unit_price == Decimal(1050)
    assert summary.sample_count == 2


def test_combined_average_uses_platform_means_not_offer_counts() -> None:
    calculator = OnlinePriceCalculator()
    naver = calculator.summarize("naver", "111", "01", [offer("1000")])
    coupang = calculator.summarize(
        "coupang", "111", "01", [offer("2000", platform="coupang")]
    )
    assert calculator.combined_average([naver, coupang]) == Decimal(1500)
