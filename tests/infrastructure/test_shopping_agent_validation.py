import csv
from pathlib import Path

from app.domain.models import ProductCatalogEntry
from app.infrastructure.shopping_agent_validation import validate_collection


def test_completion_requires_comparable_offers_and_reports_bad_quantity(tmp_path):
    fixture = Path("tests/fixtures/coupang_agent_offers.csv")
    with fixture.open(encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    row = rows[0]
    row["quantity"] = ""
    path = tmp_path / "offers.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    entry = ProductCatalogEntry("100", "식량", "111", "쌀", "10", "일반계",
                                "kg", "10", "kg", "10", None, None, (), (), ())
    manifest = {"run_id": "fixture-run", "observed_date": "2026-09-26",
                "targets": [{"item_code": "111", "kind_code": "10"}]}
    status, diagnostics = validate_collection(path, manifest, {("111", "10"): entry}, "coupang")
    assert status["status"] == "failed"
    assert status["completed_count"] == 0
    assert status["failed_keys"] == ["111:10"]
    assert "quantity must be positive" in diagnostics["errors"][0]
    assert diagnostics["targets"]["111:10"]["comparable_count"] == 0

    row["quantity"] = "10"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    status, diagnostics = validate_collection(path, manifest, {("111", "10"): entry}, "coupang")
    assert status["status"] == "success"
    assert status["completed_count"] == 1
    assert not status["failed_keys"]
