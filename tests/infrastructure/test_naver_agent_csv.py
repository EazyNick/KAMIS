from __future__ import annotations

import csv
from pathlib import Path

from app.domain.models import ProductCatalogEntry
from app.infrastructure.naver_agent_csv import NaverAgentCsvParser

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


def write_naver_row(path: Path, *, url: str) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(
            {
                "run_id": "run-1",
                "observed_date": "2026-09-26",
                "collected_at": "2026-09-26T10:00:00+09:00",
                "platform": "naver",
                "item_code": "111",
                "kind_code": "10",
                "query": "쌀 10kg",
                "product_id": "naver-rice",
                "title": "국내산 쌀 10kg",
                "url": url,
                "displayed_price": "35000",
                "shipping_fee": "0",
                "member_price": "34000",
                "member_discount_scope": "all_members",
                "quantity": "10",
                "unit": "kg",
                "unit_price_text": "",
                "advertisement": "false",
                "availability": "available",
                "raw_accessible_name": "국내산 쌀 10kg 35000원",
            }
        )


def rice_entry() -> ProductCatalogEntry:
    return ProductCatalogEntry(
        "100",
        "식량",
        "111",
        "쌀",
        "10",
        "10kg",
        "kg",
        "10",
        "kg",
        "10",
        None,
        None,
        ("04",),
        ("04",),
        (),
    )


def manifest() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "observed_date": "2026-09-26",
        "targets": [{"item_code": "111", "kind_code": "10"}],
    }


def test_naver_parser_accepts_naver_rows_and_normalizes_kamis_unit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "offers.csv"
    write_naver_row(path, url="https://shopping.naver.com/product/1")

    result = NaverAgentCsvParser().parse(
        path, manifest(), {("111", "10"): rice_entry()}
    )

    offer = result.offers_by_key[("111", "10")][0]
    assert offer.platform == "naver"
    assert str(offer.quantity) == "1"
    assert str(offer.unit_price) == "34000"


def test_naver_parser_rejects_rows_without_a_naver_https_url(tmp_path: Path) -> None:
    path = tmp_path / "offers.csv"
    write_naver_row(path, url="")

    result = NaverAgentCsvParser().parse(
        path, manifest(), {("111", "10"): rice_entry()}
    )

    assert result.invalid_row_count == 1
    assert result.failed_keys == frozenset({("111", "10")})
