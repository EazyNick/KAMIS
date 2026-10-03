from datetime import date
from decimal import Decimal

import pytest

from app.infrastructure.coupang_agent_csv import ShoppingAgentCsvParser
from app.infrastructure.naver_agent_csv import NaverAgentCsvParser
from app.infrastructure.online_repository import OnlinePriceRepository
from log import app_logger
from tests.infrastructure.test_coupang_agent_csv import entry, row


def count_offer(platform="coupang", option="후지 사과 10과", quantity="10", unit="개", **changes):
    fish = unit in {"마리", "미"}
    catalog = entry("411", "05", "고등어" if fish else "사과", "", "마리" if fish else "개", "1" if fish else "10")
    data = row("411", "05", "고등어" if fish else "후지 사과", "30000", quantity, unit,
               platform=platform, selected_option=option, quantity_evidence=option,
               url="https://smartstore.naver.com/shop/products/1" if platform == "naver" else "https://www.coupang.com/vp/products/1",
               price_evidence="판매가 30,000원", evidence_source="product_detail",
               detail_accessible_name=f"{option}\n판매가 30,000원\n무료배송",
               detail_product_title="고등어" if fish else "후지 사과",
               order_quantity="1")
    data.update(changes)
    parser = NaverAgentCsvParser() if platform == "naver" else ShoppingAgentCsvParser(platform)
    return parser._to_offer(data, entry=catalog, observed_date=date(2026, 10, 3))


@pytest.mark.parametrize("platform", ["coupang", "naver"])
@pytest.mark.parametrize("option,quantity,unit,normalized", [
    ("후지 사과 10과", "10", "과", "1"),
    ("고등어 3미", "3", "미", "3"),
    ("고등어 2마리 × 3팩", "6", "마리", "6"),
])
def test_selected_sale_count_and_evidence_survive_storage(tmp_path, platform, option, quantity, unit, normalized):
    offer = count_offer(platform, option, quantity, unit)
    assert offer.is_comparable
    assert offer.quantity == Decimal(normalized)
    repo = OnlinePriceRepository(tmp_path, app_logger)
    repo.save_daily([offer], [], date(2026, 10, 3), "count-test")
    saved = repo.search_offers()[0]
    assert saved["selected_option"] == option
    assert saved["offered_quantity"] == quantity
    assert saved["offered_unit"] in {"개", "마리"}
    assert saved["base_price"] == "30000"
    assert saved["price_evidence"] == "판매가 30,000원"
    assert saved["url"] == ("https://smartstore.naver.com/shop/products/1" if platform == "naver" else "https://www.coupang.com/vp/products/1")


@pytest.mark.parametrize("option,quantity,unit", [
    ("사과 1박스", "1", "개"), ("사과 8~10개", "10", "개"),
    ("사과 8개~10개", "10", "개"), ("사과 약 10개", "10", "개"),
    ("사과 10개 내외", "10", "개"), ("사과 10개 또는 20개", "10", "개"),
    ("사과 10개 2박스", "10", "개"), ("사과 1.5개", "1.5", "개"),
    ("사과 10개 x 2박스 x 3세트", "20", "개"),
    ("고등어 2마리 × 3팩", "2", "마리"),
    ("사과 100g당 1개", "1", "개"),
    ("사과 8—10개", "10", "개"), ("사과 10개 미만", "10", "개"),
    ("사과 10개 초과", "10", "개"),
    ("사과 10개 (+5,000원)", "10", "개"),
    ("사과 5kg 1개", "1", "개"),
])
def test_uncertain_or_mismatched_counts_are_excluded(option, quantity, unit):
    offer = count_offer(option=option, quantity=quantity, unit=unit)
    assert not offer.is_comparable
    assert offer.exclusion_reason == "count_evidence_invalid"


@pytest.mark.parametrize("changes", [
    {"selected_option": ""}, {"quantity_evidence": ""}, {"evidence_source": "search_card"},
    {"url": ""}, {"url": "javascript:bad"}, {"order_quantity": "2"},
    {"price_evidence": "판매가 20,000원"}, {"detail_accessible_name": "다른 상품"},
    {"member_price": "25000", "member_discount_scope": "all_members"},
    {"detail_product_title": ""}, {"detail_product_title": "다른 상품 감자"},
    {"detail_accessible_name": "후지 사과 10과\n판매가 30,000원\n옵션 추가금 5,000원\n무료배송"},
])
def test_missing_or_unpaired_sale_evidence_is_excluded(changes):
    assert not count_offer(**changes).is_comparable
