from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.core.container import ApplicationContainer
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
from app.main import create_app
from app.services.collection_service import KamisCollectionService
from config.server_config import Settings
from log import app_logger


class IntegrationKamisClient:
    entry = ProductCatalogEntry(
        category_code="100",
        category_name="식량작물",
        item_code="111",
        item_name="쌀",
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

    def fetch_catalog(self) -> list[ProductCatalogEntry]:
        return [self.entry]

    def fetch_prices(self, query: PriceQuery) -> list[PriceObservation]:
        return [
            PriceObservation(
                price_type=query.price_type,
                observed_date=query.start_date,
                collected_at=datetime(2026, 9, 24, tzinfo=ZoneInfo("Asia/Seoul")),
                category_code="100",
                item_code="111",
                kind_code="01",
                rank_code="04",
                item_name="쌀",
                variety="일반",
                region="서울",
                market_name="테스트시장",
                price_krw=Decimal(1000),
                requested_convert_kg=True,
            )
        ]


def test_collection_results_are_queryable_from_api(tmp_path: Path) -> None:
    catalog = CatalogRepository(tmp_path, app_logger)
    prices = PriceRepository(tmp_path, app_logger)
    runs = RunRepository(tmp_path, app_logger)
    service = KamisCollectionService(
        IntegrationKamisClient(), catalog, prices, runs, app_logger
    )
    container = ApplicationContainer(
        Settings.from_env(), catalog, prices, runs, service
    )

    run = service.collect(date(2026, 9, 24), date(2026, 9, 24))
    response = TestClient(create_app(container)).get(
        "/api/v1/prices",
        params={"item_code": "111", "price_type": "retail"},
    )

    assert run.status is RunStatus.SUCCESS
    assert response.status_code == 200
    assert response.json()["items"][0]["item_name"] == "쌀"
