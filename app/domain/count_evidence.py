"""Conservative piece/fish counts for a single selected sale option."""
from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from urllib.parse import urlsplit

from app.core.errors import DataValidationError

COUNT = r"(?<![\d.,])(\d+)\s*(마리|개|과|미)(?![가-힣])"
PACK = r"(\d+)\s*(팩|박스|봉|세트)(?![가-힣])"
PRICE = re.compile(r"(?:판매\s*가격|판매가|총\s*상품\s*금액)\s*[:：]?\s*([\d,]+)\s*원")


def selected_count(text: str) -> tuple[Decimal, str]:
    """Reject estimates, alternative sizes, loose multipacks and partial matches."""
    if re.search(r"[~～–—−±]|\d\s*-\s*\d|(?:약|대략|내외|이상|이하|미만|초과|랜덤|또는|당|부터)|\d+\.\d+\s*(개|과|미|마리)|[+\-]\s*[\d,]+\s*원|추가\s*금", text):
        raise DataValidationError("uncertain count")
    counts = list(re.finditer(COUNT, text))
    packs = list(re.finditer(PACK, text))
    if len(counts) != 1 or len(packs) > 1:
        raise DataValidationError("one explicit count is required")
    count = counts[0]
    number = Decimal(count[1])
    unit = "마리" if count[2] in {"마리", "미"} else "개"
    if packs:
        pack = packs[0]
        if not re.fullmatch(r"\s*[xX×*]\s*", text[count.end():pack.start()]) or pack.start() < count.end():
            raise DataValidationError("pack multiplier is not explicit")
        number *= Decimal(pack[1])
        remainder = text[:count.start()] + text[pack.end():]
    else:
        remainder = text[:count.start()] + text[count.end():]
    if re.search(r"[×*]|\b[xX]\b|팩|박스|세트|묶음|\d+\s*봉", remainder) or number <= 0:
        raise DataValidationError("unresolved package")
    weights = re.findall(r"\d+(?:\.\d+)?\s*(?:kg|g)\b", text, re.I)
    if len(weights) > 1:
        raise DataValidationError("multiple weight options")
    if weights and unit == "개" and Decimal(count[1]) == 1 and not re.search(r"멜론|메론", text):
        raise DataValidationError("one weighted package is not one fruit")
    return number, unit


def validate_count_evidence(row: Mapping[str, str], price: Decimal, quantity: Decimal, unit: str) -> None:
    option = (row.get("selected_option") or "").strip()
    evidence = (row.get("quantity_evidence") or "").strip()
    detail = row.get("detail_accessible_name") or ""
    price_text = (row.get("price_evidence") or "").strip()
    if re.search(r"추가\s*(?:금|요금)|[+−-]\s*[\d,]+\s*원|쿠폰|카드\s*할인|회원가|와우회원", detail):
        raise DataValidationError("selected total is conditional or unresolved")
    url = urlsplit(row.get("url") or "")
    if (row.get("evidence_source") != "product_detail" or not option
            or evidence != option or option not in detail or not price_text
            or price_text not in detail or url.scheme != "https" or not url.hostname
            or row.get("order_quantity") != "1"):
        raise DataValidationError("missing selected sale evidence")
    parsed_quantity, parsed_unit = selected_count(evidence)
    canonical_unit = {"과": "개", "미": "마리"}.get(unit.strip(), unit.strip())
    prices = {Decimal(m[1].replace(",", "")) for m in PRICE.finditer(detail)}
    match = PRICE.fullmatch(price_text)
    if (parsed_quantity != quantity or parsed_unit != canonical_unit or match is None
            or Decimal(match[1].replace(",", "")) != price or prices != {price}):
        raise DataValidationError("count or price does not match selected sale")
