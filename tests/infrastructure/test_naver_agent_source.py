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
from app.infrastructure.naver_agent_source import NaverAgentSource
from log import app_logger

TODAY = date(2026, 9, 26)
ENTRY = ProductCatalogEntry(
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


def naver_offer() -> ShoppingOffer:
    return ShoppingOffer(
        "naver",
        "n1",
        "쌀 10kg",
        "https://shopping.naver.com/product/1",
        "111",
        "10",
        MatchStatus.EXACT,
        Decimal(35000),
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
        self.prompt = ""

    def run(self, prompt: str, *args: object) -> SimpleNamespace:
        self.calls += 1
        self.prompt = prompt
        return SimpleNamespace(exit_code=0, stdout="", stderr="")


class Parser:
    def parse(self, path: Path, manifest, catalog) -> CoupangCsvResult:
        return CoupangCsvResult(
            offers_by_key={("111", "10"): [naver_offer()]},
            failed_keys=frozenset(),
            invalid_row_count=0,
            errors=(),
        )


def build_source(tmp_path: Path, runner=None) -> NaverAgentSource:
    return NaverAgentSource(
        tmp_path,
        tmp_path / "runs",
        runner or Runner(),  # type: ignore[arg-type]
        Parser(),  # type: ignore[arg-type]
        app_logger,
        timeout_seconds=30,
    )


def test_naver_agent_source_invokes_naver_skill_once_and_caches_rows(
    tmp_path: Path,
) -> None:
    runner = Runner()
    source = build_source(tmp_path, runner)

    source.prepare([ENTRY], TODAY, "run-1")

    assert runner.calls == 1
    assert "$naver-ui-collector" in runner.prompt
    assert source.search(ENTRY, TODAY)[0].platform == "naver"


def test_naver_agent_failure_has_no_fallback(tmp_path: Path) -> None:
    runner = SimpleNamespace(run=lambda *args: SimpleNamespace(exit_code=1))
    source = build_source(tmp_path, runner)

    source.prepare([ENTRY], TODAY, "failed-run")

    with pytest.raises(RuntimeError, match="naver agent collection failed"):
        source.search(ENTRY, TODAY)


def test_naver_query_uses_food_name_and_comparison_unit(tmp_path: Path):
    import json

    source = build_source(tmp_path)
    source.prepare(
        [
            replace(
                ENTRY,
                item_name="배추",
                variety="가을",
                retail_unit="포기",
                retail_unit_size="1",
            )
        ],
        TODAY,
        "query-run",
    )
    manifest = json.loads(
        (tmp_path / "runs/query-run/manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["targets"][0]["query"] == "배추 1포기"
