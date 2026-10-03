import json
import subprocess
import sys

import pytest


@pytest.mark.parametrize("option,unit,quantity", [
    ("후지 사과 10과", "10개", "10"),
    ("고등어 3미", "1마리", "3"),
    ("고등어 2마리 × 3팩", "1마리", "6"),
    ("사과 10개 x 2박스", "10개", "20"),
    ("사과 8~10과", "10개", None),
    ("사과 1박스", "10개", None),
])
def test_detail_snapshot_cli_binds_selected_option_price_and_url(option, unit, quantity):
    snapshot = dict(selected_options=[option], text=f"{option}\n판매가 30,000원\n무료배송", url="https://www.coupang.com/vp/products/1", order_quantity="1", comparison_unit=unit)
    result = run_snapshot(snapshot)
    assert result["verified"] is (quantity is not None)
    if quantity:
        assert result["quantity"] == quantity
        assert result["displayed_price"] == "30000"
        assert result["selected_option"] == option
        assert result["url"] == snapshot["url"]
        assert result["shipping_fee"] == "0"


def run_snapshot(snapshot):
    process = subprocess.run([sys.executable, "-m", "app.infrastructure.shopping_count_detail"], input=json.dumps(snapshot), text=True, encoding="utf-8", capture_output=True)
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


@pytest.mark.parametrize("changes", [
    {"selected_options": []}, {"selected_options": ["사과 10과", "사과 20과"]},
    {"text": "사과 10과\n판매가 30,000원\n판매가 50,000원"},
    {"text": "사과 10과\n100g당 500원"},
    {"text": "사과 10과\n판매가 30,000원\n쿠폰 적용가"},
    {"text": "사과 10과\n판매가 30,000원\n품절"},
    {"order_quantity": ""}, {"order_quantity": "2"}, {"url": ""},
    {"comparison_unit": "1마리"},
    {"selected_options": ["사과 10과 (+5,000원)"], "text": "사과 10과 (+5,000원)\n판매가 30,000원"},
    {"text": "사과 10과\n판매가 30,000원\n옵션 추가금 5,000원\n무료배송"},
])
def test_unverified_detail_snapshot_never_reuses_search_card_values(changes):
    snapshot = dict(selected_options=["사과 10과"], text="사과 10과\n판매가 30,000원\n무료배송", url="https://smartstore.naver.com/shop/products/1", order_quantity="1", comparison_unit="10개")
    snapshot.update(changes)
    result = run_snapshot(snapshot)
    assert result["verified"] is False
    assert not result.get("quantity")


def test_conditional_shipping_does_not_become_free_shipping():
    result = run_snapshot(dict(selected_options=["사과 10과"], text="사과 10과\n판매가 30,000원\n50,000원 이상 무료배송", url="https://smartstore.naver.com/shop/products/1", order_quantity="1", comparison_unit="10개"))
    assert result["shipping_fee"] == ""
