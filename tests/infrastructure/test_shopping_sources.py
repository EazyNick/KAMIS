from datetime import date

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus
from app.infrastructure.shopping_sources import NaverShoppingSource
from log import app_logger

ENTRY = ProductCatalogEntry(
    category_code="100",
    category_name="식량작물",
    item_code="111",
    item_name="쌀",
    kind_code="01",
    variety="일반",
    wholesale_unit="kg",
    wholesale_unit_size="1",
    retail_unit="kg",
    retail_unit_size="1",
    eco_unit=None,
    eco_unit_size=None,
    wholesale_rank_codes=("04",),
    retail_rank_codes=("04",),
    eco_rank_codes=(),
)


def test_naver_parser_normalizes_shipping_quantity_and_member_discount() -> None:
    html = """
    <div class="product_item" data-id="p1">
      <a class="product_link" href="https://shop.test/p1">쌀 일반 2kg</a>
      <span class="price">12,000원</span><span class="shipping">3,000원</span>
      <span class="member-price" data-scope="all_members">10,000원</span>
    </div>
    """
    rows = NaverShoppingSource(None, app_logger).parse_html(
        html, ENTRY, date(2026, 9, 24)
    )

    assert len(rows) == 1
    assert rows[0].match_status is MatchStatus.EXACT
    assert rows[0].quantity == 2
    assert rows[0].unit_price == 6500


def test_plain_registration_discount_is_available_to_all_members() -> None:
    html = """
    <div class="product_item" data-id="p2">
      <a class="product_link" href="https://shop.test/p2">쌀 일반 1kg</a>
      <span class="price">12,000원</span>
      <span class="member-price">회원가입 할인가 10,000원</span>
    </div>
    """
    row = NaverShoppingSource(None, app_logger).parse_html(
        html, ENTRY, date(2026, 9, 24)
    )[0]
    assert row.member_discount_scope == "all_members"
    assert row.unit_price == 10000
