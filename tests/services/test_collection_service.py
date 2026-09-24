from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import CollectionAlreadyRunning
from app.domain.models import (
    PriceObservation,
    PriceQuery,
    ProductCatalogEntry,
    RunStatus,
)
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.services.collection_service import KamisCollectionService
from log import app_logger


def catalog_entry(item_code: str) -> ProductCatalogEntry:
    return ProductCatalogEntry(
        category_code="100",
        category_name="식량작물",
        item_code=item_code,
        item_name="쌀" if item_code == "111" else "감자",
        kind_code="01",
        variety="일반",
        wholesale_unit="kg",
        wholesale_unit_size="1",
        retail_unit="kg",
        retail_unit_size="1",
        eco_unit=None,
        eco_unit_size=None,
        wholesale_rank_codes=("04",),
        retail_rank_codes=("04",),
        eco_rank_codes=(),
    )


class FakeKamisClient:
    def __init__(self) -> None:
        self.entries = [catalog_entry("111"), catalog_entry("222")]

    def fetch_catalog(self) -> list[ProductCatalogEntry]:
        return self.entries

    def fetch_prices(self, query: PriceQuery) -> list[PriceObservation]:
        if query.catalog_entry.item_code == "222":
            raise TimeoutError("timeout")
        return [
            PriceObservation(
                price_type=query.price_type,
                observed_date=query.start_date,
                collected_at=datetime(2026, 9, 24, 7, tzinfo=ZoneInfo("Asia/Seoul")),
                category_code=query.catalog_entry.category_code,
                item_code=query.catalog_entry.item_code,
                kind_code=query.catalog_entry.kind_code,
                rank_code=query.rank_code,
                item_name=query.catalog_entry.item_name,
                variety=query.catalog_entry.variety,
                region="서울",
                market_name="테스트시장",
                price_krw=PriceObservation.parse_price("1000"),
                requested_convert_kg=True,
            )
        ]


@pytest.fixture
def service(tmp_path: Path) -> KamisCollectionService:
    return KamisCollectionService(
        FakeKamisClient(),
        CatalogRepository(tmp_path, app_logger),
        PriceRepository(tmp_path, app_logger),
        RunRepository(tmp_path, app_logger),
        app_logger,
    )


def test_collection_continues_after_one_item_fails(
    service: KamisCollectionService,
) -> None:
    run = service.collect(date(2026, 9, 24), date(2026, 9, 24))

    assert run.status is RunStatus.PARTIAL_FAILURE
    assert run.error_count == 2
    assert service.price_repository.count() == 2
    assert service.run_repository.get(run.run_id)["status"] == "partial_failure"


def test_three_year_backfill_is_split_without_gaps() -> None:
    ranges = KamisCollectionService.split_backfill_period(
        date(2023, 9, 25), date(2026, 9, 24)
    )

    assert all((part.end - part.start).days <= 365 for part in ranges)
    assert ranges[0].start == date(2023, 9, 25)
    assert ranges[-1].end == date(2026, 9, 24)
    assert all(
        left.end + timedelta(days=1) == right.start for left, right in pairwise(ranges)
    )


def test_second_collection_is_rejected_while_running(
    service: KamisCollectionService,
) -> None:
    service.acquire_for_test()
    try:
        with pytest.raises(CollectionAlreadyRunning):
            service.collect(date(2026, 9, 24), date(2026, 9, 24))
    finally:
        service.release_for_test()
