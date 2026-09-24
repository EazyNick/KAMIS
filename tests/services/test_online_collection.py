from datetime import date
from decimal import Decimal
from pathlib import Path

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
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

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
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
