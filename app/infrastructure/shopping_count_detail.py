"""Validate a scoped accessibility snapshot, never infer from a search card."""
from __future__ import annotations

import json
import re
import sys
from decimal import Decimal

from app.core.errors import DataValidationError
from app.domain.count_evidence import PRICE, selected_count, validate_count_evidence


def extract_detail(snapshot: dict) -> dict:
    text = str(snapshot.get("text") or "")
    options = snapshot.get("selected_options") or []
    result = {
        "verified": False,
        "url": str(snapshot.get("url") or ""),
        "selected_option": options[0] if len(options) == 1 else "",
        "detail_accessible_name": text,
        "detail_product_title": str(snapshot.get("product_title") or ""),
        "order_quantity": str(snapshot.get("order_quantity") or ""),
        "evidence_source": "product_detail",
    }
    try:
        if len(options) != 1 or not isinstance(options[0], str):
            raise DataValidationError("selected option is unresolved")
        if re.search(r"품절|접근\s*제한|로그인\s*필요|CAPTCHA|쿠폰|카드\s*할인|회원가|와우회원", text, re.I):
            raise DataValidationError("sale is unavailable or conditional")
        quantity, unit = selected_count(options[0])
        expected = "마리" if "마리" in str(snapshot.get("comparison_unit")) else "개"
        if unit != expected:
            raise DataValidationError("incompatible count unit")
        prices = list(PRICE.finditer(text))
        if not prices:
            raise DataValidationError("selected sale price is unavailable")
        price = Decimal(prices[0][1].replace(",", ""))
        candidate = {**result, "quantity_evidence": options[0], "price_evidence": prices[0][0]}
        validate_count_evidence(candidate, price, quantity, unit)
        shipping = {m.replace(",", "") for m in re.findall(r"배송비\s*[:：]?\s*([\d,]+)\s*원", text)}
        if re.search(r"무료\s*배송", text):
            shipping.add("0")
        if re.search(r"이상|미만|조건|지역|제주|도서|산간|추가\s*배송", text):
            shipping.clear()
        result.update(candidate, verified=True, quantity=str(quantity), unit=unit,
                      displayed_price=str(price), shipping_fee=next(iter(shipping)) if len(shipping) == 1 else "")
    except (DataValidationError, ValueError, ArithmeticError) as error:
        result["reason"] = str(error)
    return result


def main() -> None:
    # PowerShell uses UTF-8 for the pipe; do not depend on Windows' ANSI code page.
    sys.stdin.reconfigure(encoding="utf-8-sig")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(extract_detail(json.load(sys.stdin)), ensure_ascii=True))


if __name__ == "__main__":
    main()
