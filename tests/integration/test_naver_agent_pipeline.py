from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import PlatformPriceSummary
from app.infrastructure.naver_agent_csv import NaverAgentCsvParser
from app.infrastructure.naver_agent_source import NaverAgentSource
from app.infrastructure.online_repository import OnlinePriceRepository
from app.services.online_collection import OnlineCollectionService
from app.services.online_pricing import OnlinePriceCalculator
from config.server_config import DEFAULT_ONLINE_TARGET_KEYS
from log import app_logger

TODAY = date(2026, 9, 26)


def catalog_entries() -> list[ProductCatalogEntry]:
    return [
        ProductCatalogEntry(
            "100",
            "category",
            item_code,
            f"item-{index}",
            kind_code,
            "standard",
            "kg",
            "1",
            "kg",
            "1",
            None,
            None,
            ("04",),
            ("04",),
            (),
        )
        for index, (item_code, kind_code) in enumerate(DEFAULT_ONLINE_TARGET_KEYS)
    ]


class FixtureCodexRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.manifest_target_count = 0

    def run(
        self,
        prompt: str,
        schema_path: Path,
        output_path: Path,
        timeout_seconds: float,
    ) -> SimpleNamespace:
        self.calls += 1
        manifest = json.loads(
            (schema_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        targets = manifest["targets"]
        self.manifest_target_count = len(targets)
        output_csv = Path(manifest["output_csv"])
        fieldnames = tuple(
            line.split("`")[1]
            for line in (
                Path(".agents/skills/naver-ui-collector/references/csv-schema.md")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            if line.startswith("| `")
        )
        with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for target in targets:
                title = f"{target['item_name']} {target['variety']} 1kg"
                writer.writerow(
                    {
                        "run_id": manifest["run_id"],
                        "observed_date": manifest["observed_date"],
                        "collected_at": "2026-09-26T10:00:00+09:00",
                        "platform": "naver",
                        "item_code": target["item_code"],
                        "kind_code": target["kind_code"],
                        "query": target["query"],
                        "product_id": f"n-{target['item_code']}-{target['kind_code']}",
                        "title": title,
                        "url": "https://shopping.naver.com/product/1",
                        "displayed_price": "10000",
                        "shipping_fee": "0",
                        "member_price": "",
                        "member_discount_scope": "none",
                        "quantity": "1",
                        "unit": "kg",
                        "unit_price_text": "",
                        "advertisement": "false",
                        "availability": "available",
                        "raw_accessible_name": f"{title} 10000 won",
                    }
                )
        return SimpleNamespace(exit_code=0, stdout="", stderr="")


class UnexpectedFallback:
    platform = "naver"

    def search(self, entry: ProductCatalogEntry, observed_date: date):
        raise AssertionError(f"unexpected fallback for {entry.item_code}:{entry.kind_code}")


def test_pipeline_collects_only_missing_naver_rows_and_persists_csv(
    tmp_path: Path,
) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    repository.save_daily(
        [],
        [PlatformPriceSummary("naver", "111", "10", Decimal(33000), 5, 5, (), ())],
        TODAY,
        "seed-run",
    )
    runner = FixtureCodexRunner()
    source = NaverAgentSource(
        Path.cwd(),
        tmp_path / "runs/naver-agent",
        runner,  # type: ignore[arg-type]
        NaverAgentCsvParser(),
        UnexpectedFallback(),  # type: ignore[arg-type]
        app_logger,
        timeout_seconds=30,
    )
    service = OnlineCollectionService(
        [source],
        repository,
        OnlinePriceCalculator(),
        app_logger,
        target_keys=set(DEFAULT_ONLINE_TARGET_KEYS),
    )

    result = service.collect(catalog_entries(), TODAY, "run-2", include_combined=False)

    assert runner.calls == 1
    assert runner.manifest_target_count == 9
    assert result.error_count == 0
    assert len(
        {
            (row["item_code"], row["kind_code"])
            for row in repository.summaries_for_date(TODAY)
            if row["platform"] == "naver"
        }
    ) == 10
