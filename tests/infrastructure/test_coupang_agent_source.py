from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

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
        Decimal("10000"),
        None,
        None,
        Decimal("0"),
        Decimal("1"),
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


class Fallback:
    platform = "coupang"

    def __init__(self) -> None:
        self.searched_keys: set[tuple[str, str]] = set()

    def search(self, entry: ProductCatalogEntry, observed_date: date):
        self.searched_keys.add((entry.item_code, entry.kind_code))
        return [offer(entry)]


def build_source(
    tmp_path: Path, failed_keys: set[tuple[str, str]]
) -> tuple[CoupangAgentSource, Runner, Fallback]:
    runner = Runner()
    fallback = Fallback()
    source = CoupangAgentSource(
        tmp_path,
        tmp_path / "runs",
        runner,  # type: ignore[arg-type]
        Parser(failed_keys),  # type: ignore[arg-type]
        fallback,  # type: ignore[arg-type]
        app_logger,
        timeout_seconds=30,
    )
    return source, runner, fallback


def test_agent_source_invokes_codex_once_for_ten_entries(tmp_path: Path) -> None:
    source, runner, _ = build_source(tmp_path, set())

    source.prepare(TEN_ENTRIES, TODAY, "run-1")
    for entry in TEN_ENTRIES:
        assert source.search(entry, TODAY)

    assert runner.calls == 1


def test_agent_source_falls_back_only_for_failed_keys(tmp_path: Path) -> None:
    failed = {
        (TEN_ENTRIES[2].item_code, TEN_ENTRIES[2].kind_code),
        (TEN_ENTRIES[4].item_code, TEN_ENTRIES[4].kind_code),
    }
    source, _, fallback = build_source(tmp_path, failed)

    source.prepare(TEN_ENTRIES, TODAY, "run-1")

    assert fallback.searched_keys == failed
    for entry in TEN_ENTRIES:
        assert source.search(entry, TODAY)
