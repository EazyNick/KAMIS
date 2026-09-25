from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import DataValidationError
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus
from app.infrastructure.coupang_agent_csv import CoupangAgentCsvParser

RUN_ID = "run-1"
OBSERVED_DATE = "2026-09-26"
FIELDNAMES = (
    "run_id",
    "observed_date",
    "collected_at",
    "platform",
    "item_code",
    "kind_code",
    "query",
    "product_id",
    "title",
    "url",
    "displayed_price",
    "shipping_fee",
    "member_price",
    "member_discount_scope",
    "quantity",
    "unit",
    "unit_price_text",
    "advertisement",
    "availability",
    "raw_accessible_name",
)


def entry(
    item_code: str,
    kind_code: str,
    item_name: str,
    variety: str,
    retail_unit: str,
    retail_unit_size: str,
) -> ProductCatalogEntry:
    return ProductCatalogEntry(
        category_code="100",
        category_name="식량",
        item_code=item_code,
        item_name=item_name,
        kind_code=kind_code,
        variety=variety,
        wholesale_unit=retail_unit,
        wholesale_unit_size=retail_unit_size,
        retail_unit=retail_unit,
        retail_unit_size=retail_unit_size,
        eco_unit=None,
        eco_unit_size=None,
        wholesale_rank_codes=("04",),
        retail_rank_codes=("04",),
        eco_rank_codes=(),
    )


CATALOG = {
    ("111", "10"): entry("111", "10", "쌀", "일반계", "kg", "10"),
    ("211", "03"): entry("211", "03", "배추", "가을", "포기", "1"),
    ("411", "05"): entry("411", "05", "사과", "후지", "개", "10"),
}
MANIFEST = {
    "run_id": RUN_ID,
    "observed_date": OBSERVED_DATE,
    "targets": [
        {"item_code": item_code, "kind_code": kind_code}
        for item_code, kind_code in CATALOG
    ],
}


def row(
    item_code: str = "111",
    kind_code: str = "10",
    title: str = "국내산 쌀 일반계 10kg",
    displayed_price: str = "34900",
    quantity: str = "10",
    unit: str = "kg",
    **overrides: str,
) -> dict[str, str]:
    result = {
        "run_id": RUN_ID,
        "observed_date": OBSERVED_DATE,
        "collected_at": "2026-09-26T10:00:00+09:00",
        "platform": "coupang",
        "item_code": item_code,
        "kind_code": kind_code,
        "query": title,
        "product_id": f"product-{item_code}-{kind_code}",
        "title": title,
        "url": "https://www.coupang.com/vp/products/1",
        "displayed_price": displayed_price,
        "shipping_fee": "0",
        "member_price": "",
        "member_discount_scope": "none",
        "quantity": quantity,
        "unit": unit,
        "unit_price_text": "",
        "advertisement": "false",
        "availability": "available",
        "raw_accessible_name": f"{title} {displayed_price}원",
    }
    result.update(overrides)
    return result


def write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_parser_normalizes_rice_10kg_to_one_kamis_retail_unit(
    tmp_path: Path,
) -> None:
    result = CoupangAgentCsvParser().parse(
        write_csv(tmp_path / "offers.csv", [row()]), MANIFEST, CATALOG
    )

    offer = result.offers_by_key[("111", "10")][0]
    assert offer.quantity == Decimal("1")
    assert offer.unit == "kamis_retail_unit"
    assert offer.unit_price == Decimal("34900")


def test_parser_rejects_seedling_and_nonconvertible_apple_weight(
    tmp_path: Path,
) -> None:
    rows = [
        row("211", "03", "가을 배추 모종 15개", "9220", "15", "개"),
        row("411", "05", "후지 사과 5kg", "25000", "5", "kg"),
    ]

    result = CoupangAgentCsvParser().parse(
        write_csv(tmp_path / "offers.csv", rows), MANIFEST, CATALOG
    )

    assert result.offers_by_key[("211", "03")][0].match_status is MatchStatus.REJECTED
    assert result.offers_by_key[("211", "03")][0].exclusion_reason == "forbidden_product_type"
    assert result.offers_by_key[("411", "05")][0].match_status is MatchStatus.REJECTED
    assert result.offers_by_key[("411", "05")][0].exclusion_reason == "incompatible_unit"


def test_parser_rejects_manifest_mismatch_and_csv_formula(tmp_path: Path) -> None:
    bad_formula = row(title='=HYPERLINK("bad")')
    with pytest.raises(DataValidationError, match="spreadsheet formula"):
        CoupangAgentCsvParser().parse(
            write_csv(tmp_path / "formula.csv", [bad_formula]), MANIFEST, CATALOG
        )

    bad_run = row(run_id="different-run")
    with pytest.raises(DataValidationError, match="manifest"):
        CoupangAgentCsvParser().parse(
            write_csv(tmp_path / "run.csv", [bad_run]), MANIFEST, CATALOG
        )


def test_parser_uses_public_price_for_restricted_discount_and_rejects_unknown_shipping(
    tmp_path: Path,
) -> None:
    rows = [
        row(
            product_id="restricted-with-base",
            displayed_price="34900",
            member_price="29900",
            member_discount_scope="restricted",
        ),
        row(
            product_id="shipping-unknown",
            shipping_fee="",
        ),
    ]

    result = CoupangAgentCsvParser().parse(
        write_csv(tmp_path / "offers.csv", rows), MANIFEST, CATALOG
    )

    offers = result.offers_by_key[("111", "10")]
    assert offers[0].eligible_price == Decimal("34900")
    assert offers[1].match_status is MatchStatus.REJECTED
    assert offers[1].exclusion_reason == "shipping_unknown"


def test_parser_deduplicates_product_ids(tmp_path: Path) -> None:
    duplicate = row(product_id="same")
    result = CoupangAgentCsvParser().parse(
        write_csv(tmp_path / "offers.csv", [duplicate, duplicate]),
        MANIFEST,
        CATALOG,
    )

    assert len(result.offers_by_key[("111", "10")]) == 1
    assert result.invalid_row_count == 1


def test_parser_rejects_manifest_key_missing_from_catalog(tmp_path: Path) -> None:
    manifest = {
        "run_id": RUN_ID,
        "observed_date": OBSERVED_DATE,
        "targets": [{"item_code": "999", "kind_code": "99"}],
    }

    with pytest.raises(DataValidationError, match="catalog"):
        CoupangAgentCsvParser().parse(
            write_csv(
                tmp_path / "offers.csv",
                [row(item_code="999", kind_code="99")],
            ),
            manifest,
            CATALOG,
        )
