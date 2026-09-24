from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.container import ApplicationContainer
from app.domain.models import ProductCatalogEntry
from app.infrastructure.csv_repository import (
    CatalogRepository,
    PriceRepository,
    RunRepository,
)
from app.infrastructure.market_data import MarketRepository
from app.infrastructure.online_repository import OnlinePriceRepository
from app.main import create_app
from app.services.analytics import AnalyticsService
from app.services.collection_service import KamisCollectionService
from app.services.comparison import ComparisonService
from config.server_config import Settings
from log import app_logger


class EmptyClient:
    def fetch_catalog(self) -> list[ProductCatalogEntry]:
        return []

    def fetch_prices(self, query: object) -> list[object]:
        return []


@pytest.fixture
def container(tmp_path: Path) -> ApplicationContainer:
    settings = Settings.from_env()
    catalog = CatalogRepository(tmp_path, app_logger)
    prices = PriceRepository(tmp_path, app_logger)
    runs = RunRepository(tmp_path, app_logger)
    service = KamisCollectionService(EmptyClient(), catalog, prices, runs, app_logger)
    online = OnlinePriceRepository(tmp_path, app_logger)
    market = MarketRepository(tmp_path, app_logger)
    comparison = ComparisonService(prices, online, market, AnalyticsService())
    return ApplicationContainer(
        settings,
        catalog,
        prices,
        runs,
        service,
        online_repository=online,
        market_repository=market,
        comparison_service=comparison,
    )


@pytest.fixture
def client(container: ApplicationContainer) -> TestClient:
    return TestClient(create_app(container))


def test_health_reports_service_and_data_status(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_filters_and_paginates(
    client: TestClient, container: ApplicationContainer
) -> None:
    row = ProductCatalogEntry(
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
    container.catalog_repository.save_snapshot([row], date(2026, 9, 24), "run-1")

    response = client.get("/api/v1/catalog", params={"item_name": "쌀"})

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["item_name"] == "쌀"


def test_concurrent_collection_returns_409(
    client: TestClient, container: ApplicationContainer
) -> None:
    container.collection_service.acquire_for_test()
    try:
        response = client.post(
            "/api/v1/collections/kamis",
            json={"start_date": "2026-09-24", "end_date": "2026-09-24"},
        )
    finally:
        container.collection_service.release_for_test()

    assert response.status_code == 409


def test_unknown_run_returns_404(client: TestClient) -> None:
    assert client.get("/api/v1/collections/missing").status_code == 404


def test_price_date_order_is_validated(client: TestClient) -> None:
    response = client.get(
        "/api/v1/prices",
        params={"start_date": "2026-09-25", "end_date": "2026-09-24"},
    )
    assert response.status_code == 422


def test_dashboard_is_served_as_html(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "KAMIS Market Lens" in response.text
    assert "comparisonChart" in response.text


def test_comparison_api_exposes_every_required_toggle(client: TestClient) -> None:
    response = client.get(
        "/api/v1/comparison", params={"item_code": "111", "mode": "base100"}
    )
    assert response.status_code == 200
    required = {
        "kamis_wholesale",
        "kamis_retail",
        "online_naver",
        "online_coupang",
        "kospi",
        "kosdaq",
        "sp500",
        "nasdaq",
        "dow_jones",
    }
    assert required.issubset(response.json()["series"])
