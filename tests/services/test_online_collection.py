from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
from app.infrastructure.shopping_sources import BrowserResponse
from app.services.online_collection import OnlineCollectionService
from app.services.online_pricing import OnlinePriceCalculator
from log import app_logger

ENTRY = ProductCatalogEntry(
    "100",
    "식량",
    "111",
    "쌀",
    "01",
    "일반",
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


class Source:
    def __init__(self, platform: str, *, fail: bool = False) -> None:
        self.platform = platform
        self.fail = fail
        self.calls = 0

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
        self.calls += 1
        if self.fail:
            raise TimeoutError("blocked")
        return [
            ShoppingOffer(
                self.platform,
                "p1",
                "쌀 일반 1kg",
                "https://example.test",
                entry.item_code,
                entry.kind_code,
                MatchStatus.EXACT,
                Decimal(1000),
                None,
                None,
                Decimal(0),
                Decimal(1),
                "kg",
                True,
                observed_date=observed_date,
            )
        ]


class BlockingSource:
    platform = "naver"

    def __init__(self) -> None:
        self.calls = 0

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
        self.calls += 1
        BrowserResponse("blocked", 418).raise_for_status()
        return []


def test_online_collection_isolates_platform_failure(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    service = OnlineCollectionService(
        [Source("naver"), Source("coupang", fail=True)],
        repository,
        OnlinePriceCalculator(),
        app_logger,
    )

    result = service.collect([ENTRY], date(2026, 9, 24), "run-1")

    assert result.offer_count == 1
    assert result.error_count == 1
    summaries = repository.search_summaries(item_code="111")
    assert {row["platform"] for row in summaries} == {"naver", "coupang", "combined"}
    coupang = next(row for row in summaries if row["platform"] == "coupang")
    assert coupang["collection_status"] == "collection_failed"


def test_online_collection_only_searches_configured_representatives(
    tmp_path: Path,
) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    source = Source("naver")
    service = OnlineCollectionService(
        [source],
        repository,
        OnlinePriceCalculator(),
        app_logger,
        target_keys={("111", "01")},
    )
    other = replace(
        ENTRY,
        item_code="222",
        item_name="감자",
        kind_code="00",
        variety="감자",
    )

    result = service.collect([ENTRY, ENTRY, other], date(2026, 9, 25), "run-targets")

    assert result.offer_count == 1
    assert source.calls == 1
    assert {row["item_code"] for row in repository.search_summaries()} == {"111"}
    assert service.has_collected_date([ENTRY, other], date(2026, 9, 25)) is True


def test_online_collection_stops_platform_after_access_block(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    blocked = BlockingSource()
    service = OnlineCollectionService(
        [blocked], repository, OnlinePriceCalculator(), app_logger
    )
    other = replace(
        ENTRY,
        item_code="222",
        item_name="감자",
        kind_code="00",
        variety="감자",
    )

    result = service.collect([ENTRY, other], date(2026, 9, 25), "run-blocked")

    assert blocked.calls == 1
    assert result.error_count == 1
    summaries = repository.search_summaries()
    assert all(row["collection_status"] == "blocked" for row in summaries)
    assert service.has_collected_date([ENTRY, other], date(2026, 9, 25)) is False
