"""Convert observed KAMIS prices to the shopping comparison package."""

import math
import re


def _measure(size, unit):
    unit = (unit or "").strip()
    if unit not in {"kg", "g", "개", "포기", "마리"}:
        return None
    try:
        amount = float(size)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    return ("kg", amount / 1000) if unit == "g" else (unit, amount)


def comparable_kamis_rows(rows, item_code, kind, catalog):
    entries = {(r["item_code"], r["kind_code"]): r for r in catalog}
    target = entries.get((item_code, kind))
    if target is None:
        return [r for r in rows if r.get("kind_code") == kind], []
    target_measure = _measure(target.get("retail_unit_size"), target.get("retail_unit"))
    if target_measure is None:
        return [], ["KAMIS: 온라인 비교 단위를 확인할 수 없어 제외했습니다."]
    notes = set()
    converted = []
    for row in rows:
        source_kind = row.get("kind_code")
        fallback = (item_code, kind, source_kind) == ("111", "10", "01")
        if source_kind != kind and not fallback:
            continue
        if row.get("region") == "평년":
            continue
        try:
            price = float(row["price_krw"])
        except (ValueError, TypeError, KeyError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        source = entries.get((item_code, source_kind), {})
        price_type = row.get("price_type", "")
        unit = source.get(f"{price_type}_unit")
        size = source.get(f"{price_type}_unit_size")
        # The response unit wins: convert_kg is a request, not a guarantee.
        match = re.search(r"\((\d+(?:\.\d+)?)\s*(kg|g|개|포기|마리)\)$", row.get("variety", ""))
        if match:
            size, unit = match.groups()
        elif str(row.get("requested_convert_kg")).lower() in {"true", "y", "1"} and (unit or "").startswith("kg"):
            size, unit = "1", "kg"
        elif fallback and str(row.get("requested_convert_kg")).lower() in {"true", "y", "1"}:
            size, unit = "1", "kg"
        elif source_kind == kind and price_type == "retail":
            size, unit = target.get("retail_unit_size"), target.get("retail_unit")
        measure = _measure(size, unit)
        if measure is None or measure[0] != target_measure[0]:
            label = "도매" if price_type == "wholesale" else "소매"
            notes.add(f"KAMIS {label}: 온라인과 단위가 달라 환산할 수 없는 가격은 제외했습니다.")
            continue
        converted.append((fallback, {**row, "price_krw": price * target_measure[1] / measure[1]}))
    exact = {(r["observed_date"], r["price_type"]) for fallback, r in converted if not fallback}
    result = []
    for fallback, row in converted:
        if fallback and (row["observed_date"], row["price_type"]) in exact:
            continue
        if fallback:
            notes.add("쌀 KAMIS: 20kg 품목 가격을 10kg 기준으로 환산했습니다. 실제 10kg 포장 조사 가격과 다릅니다.")
        result.append(row)
    if not result:
        notes.add("선택한 품종·비교 단위에 맞는 KAMIS 관측 가격이 없습니다.")
    else:
        present = {row["price_type"] for row in result}
        for price_type, label in (("wholesale", "도매"), ("retail", "소매")):
            if price_type not in present:
                notes.add(f"KAMIS {label}: 비교 가능한 관측 가격이 없습니다.")
    return result, sorted(notes)
