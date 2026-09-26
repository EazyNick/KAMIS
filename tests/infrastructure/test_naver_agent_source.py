from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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


class Fallback:
    platform = "naver"

    def search(self, entry: ProductCatalogEntry, observed_date: date):
        raise AssertionError("fallback should not run")


def test_naver_agent_source_invokes_naver_skill_once_and_caches_rows(
    tmp_path: Path,
) -> None:
    runner = Runner()
    source = NaverAgentSource(
        tmp_path,
        tmp_path / "runs",
        runner,  # type: ignore[arg-type]
        Parser(),  # type: ignore[arg-type]
        Fallback(),  # type: ignore[arg-type]
        app_logger,
        timeout_seconds=30,
    )

    source.prepare([ENTRY], TODAY, "run-1")

    assert runner.calls == 1
    assert "$naver-ui-collector" in runner.prompt
    assert source.search(ENTRY, TODAY)[0].platform == "naver"
