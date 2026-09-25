from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.container import ApplicationContainer
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
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


def test_health_reports_startup_backfill_as_collection_running(
    client: TestClient, container: ApplicationContainer
) -> None:
    container.startup_collection_service = SimpleNamespace(is_running=True)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["collection_running"] is True


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


def test_dashboard_defaults_endpoint_handles_empty_dataset(client: TestClient) -> None:
    response = client.get("/api/v1/dashboard/defaults")

    assert response.status_code == 200
    assert response.json() == {
        "item_code": None,
        "start_date": None,
        "end_date": None,
        "mode": "base100",
    }


def test_dashboard_bootstrap_reads_precomputed_default_chart(tmp_path: Path) -> None:
    settings = replace(Settings.from_env(), data_dir=tmp_path)
    container = ApplicationContainer.build(settings)
    container.startup_collection_service = None
    assert container.analytics_repository is not None
    container.analytics_repository.save(
        "comparison_series",
        [
            {
                "item_code": "111",
                "kind_code": "10",
                "observed_date": "2026-07-02",
                "mode": "base100",
                "series_id": "kamis_retail",
                "value": 100.0,
            },
            {
                "item_code": "111",
                "kind_code": "10",
                "observed_date": "2026-07-02",
                "mode": "base100",
                "series_id": "sp500",
                "value": 100.0,
            },
            {
                "item_code": "111",
                "kind_code": "10",
                "observed_date": "2026-07-03",
                "mode": "base100",
                "series_id": "kamis_retail",
                "value": 101.0,
            },
            {
                "item_code": "111",
                "kind_code": "10",
                "observed_date": "2026-07-02",
                "mode": "raw",
                "series_id": "kamis_retail",
                "value": 2500.0,
            },
            {
                "item_code": "111",
                "kind_code": "10",
                "observed_date": "2026-07-03",
                "mode": "raw",
                "series_id": "kamis_retail",
                "value": 2525.0,
            },
        ],
        "analytics-run",
    )

    response = TestClient(create_app(container)).get("/api/v1/dashboard/bootstrap")

    assert response.status_code == 200
    payload = response.json()
    assert payload["defaults"] == {
        "item_code": "111",
        "start_date": "2026-07-02",
        "end_date": "2026-07-03",
        "mode": "base100",
    }
    assert payload["chart"]["dates"] == ["2026-07-02", "2026-07-03"]
    assert payload["chart"]["series"]["kamis_retail"] == [100.0, 101.0]
    assert payload["chart"]["series"]["sp500"] == [100.0, 100.0]
    assert payload["chart"]["raw_series"]["kamis_retail"] == [2500.0, 2525.0]


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


def test_application_startup_checks_today_collection(
    container: ApplicationContainer,
) -> None:
    class FakeStartupCollection:
        def __init__(self) -> None:
            self.calls = 0

        def ensure_today(self) -> str:
            self.calls += 1
            return "scheduled"

    startup = FakeStartupCollection()
    container.startup_collection_service = startup

    with TestClient(create_app(container)):
        pass

    assert startup.calls == 1


def test_coupang_agent_endpoint_returns_collection_result(
    client: TestClient, container: ApplicationContainer
) -> None:
    entry = ProductCatalogEntry(
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
    container.catalog_repository.save_snapshot(
        [entry], date(2026, 9, 26), "catalog-run"
    )

    class AgentSource:
        platform = "coupang"

        def prepare(self, entries, observed_date, run_id):
            self.entries = entries

        def search(self, selected, observed_date):
            return [
                ShoppingOffer(
                    "coupang",
                    "p1",
                    "쌀 10kg",
                    "https://example.test",
                    selected.item_code,
                    selected.kind_code,
                    MatchStatus.EXACT,
                    Decimal("30000"),
                    None,
                    None,
                    Decimal("0"),
                    Decimal("1"),
                    "kamis_retail_unit",
                    True,
                    observed_date=observed_date,
                )
            ]

    container.coupang_agent_source = AgentSource()  # type: ignore[assignment]

    response = client.post(
        "/api/v1/collections/coupang-agent",
        json={"observed_date": "2026-09-26", "item": "111:10"},
    )

    assert response.status_code == 200
    assert response.json()["target_count"] == 1
    assert response.json()["offer_count"] == 1
