from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
from app.infrastructure.coupang_agent_csv import CoupangCsvResult
from app.infrastructure.coupang_agent_source import CoupangAgentSource
from log import app_logger

TODAY = date(2026, 9, 26)
BASE_ENTRY = ProductCatalogEntry(
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
TEN_ENTRIES = [
    replace(
        BASE_ENTRY,
        item_code=f"{111 + index}",
        kind_code=f"{10 + index}",
        item_name=f"품목{index}",
    )
    for index in range(10)
]


def offer(entry: ProductCatalogEntry) -> ShoppingOffer:
    return ShoppingOffer(
        "coupang",
        f"p-{entry.item_code}",
        f"{entry.item_name} 10kg",
        "https://example.test",
        entry.item_code,
        entry.kind_code,
        MatchStatus.EXACT,
        Decimal(10000),
        None,
        None,
        Decimal(0),
        Decimal(1),
        "kamis_retail_unit",
        True,
        observed_date=TODAY,
    )


class Runner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, *args: object, **kwargs: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(exit_code=0, stdout="", stderr="")


class Parser:
    def __init__(self, failed_keys: set[tuple[str, str]]) -> None:
        self.failed_keys = failed_keys

    def parse(self, path: Path, manifest, catalog) -> CoupangCsvResult:
        return CoupangCsvResult(
            offers_by_key={
                key: ([] if key in self.failed_keys else [offer(entry)])
                for key, entry in catalog.items()
            },
            failed_keys=frozenset(self.failed_keys),
            invalid_row_count=0,
            errors=(),
        )


def build_source(
    tmp_path: Path, failed_keys: set[tuple[str, str]]
) -> tuple[CoupangAgentSource, Runner]:
    runner = Runner()
    source = CoupangAgentSource(
        tmp_path,
        tmp_path / "runs",
        runner,  # type: ignore[arg-type]
        Parser(failed_keys),  # type: ignore[arg-type]
        app_logger,
        timeout_seconds=30,
    )
    return source, runner


def test_agent_source_invokes_codex_once_for_ten_entries(tmp_path: Path) -> None:
    source, runner = build_source(tmp_path, set())

    source.prepare(TEN_ENTRIES, TODAY, "run-1")
    for entry in TEN_ENTRIES:
        assert source.search(entry, TODAY)

    assert runner.calls == 1


def test_agent_source_reports_failed_keys_without_fallback(tmp_path: Path) -> None:
    failed = {
        (TEN_ENTRIES[2].item_code, TEN_ENTRIES[2].kind_code),
        (TEN_ENTRIES[4].item_code, TEN_ENTRIES[4].kind_code),
    }
    source, _ = build_source(tmp_path, failed)

    source.prepare(TEN_ENTRIES, TODAY, "run-1")

    for entry in TEN_ENTRIES:
        if (entry.item_code, entry.kind_code) in failed:
            with pytest.raises(RuntimeError, match="agent collection failed"):
                source.search(entry, TODAY)
        else:
            assert source.search(entry, TODAY)


def test_coupang_manifest_queries_include_comparison_unit(tmp_path: Path) -> None:
    import json

    source, _ = build_source(tmp_path, set())
    cabbage = replace(
        BASE_ENTRY,
        item_name="배추",
        variety="가을",
        retail_unit="포기",
        retail_unit_size="1",
    )
    source.prepare([cabbage], TODAY, "query-run")
    manifest = json.loads(
        (tmp_path / "runs/query-run/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["targets"][0]["query"] == "배추 1포기"
