from __future__ import annotations

import logging
from collections import deque
from datetime import date
from typing import Any

import pytest

from app.core.errors import KamisAuthenticationError
from app.domain.models import PriceQuery, PriceType, ProductCatalogEntry
from app.infrastructure.kamis_client import KamisClient
from config.server_config import Settings
from log.logger import StructuredLogger

CATALOG_ROW = {
    "itemcategorycode": "100",
    "itemcategoryname": "식량작물",
    "itemcode": "111",
    "itemname": "쌀",
    "kindcode": "01",
    "kindname": "20kg",
    "wholesale_unit": "kg",
    "wholesale_unitsize": "20",
    "retail_unit": "kg",
    "retail_unitsize": "20",
    "eco_unit": [],
    "eco_unitsize": [],
    "whole_productrankcode": "04",
    "retail_productrankcode": "04,05",
    "new_natreu_productrankcode": [],
}


class FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self._responses: deque[FakeResponse] = deque()
        self.last_params: dict[str, str] | None = None

    def queue_json(self, payload: dict[str, Any]) -> None:
        self._responses.append(FakeResponse(payload))

    def get(self, _url: str, *, params: dict[str, str], timeout: float) -> FakeResponse:
        assert timeout > 0
        self.last_params = params
        return self._responses.popleft()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_level="DEBUG",
        timezone="Asia/Seoul",
        kamis_base_url="https://example.test/kamis",
        kamis_cert_key="secret-key",
        kamis_cert_id="9780",
        request_timeout_seconds=5,
        scheduler_hour=7,
        scheduler_minute=0,
    )


def test_fetch_catalog_parses_success_response(settings: Settings) -> None:
    session = FakeSession()
    session.queue_json(
        {"condition": [[[]]], "error_code": "000", "info": [CATALOG_ROW]}
    )
    client = KamisClient(
        settings, session, StructuredLogger(logging.getLogger("test.kamis"))
    )

    rows = client.fetch_catalog()

    assert rows[0].item_code == "111"
    assert session.last_params == {"action": "productInfo", "p_returntype": "json"}


def test_auth_failure_does_not_log_credentials(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    session = FakeSession()
    session.queue_json({"error_code": "900", "error_message": "Unauthenticated"})
    client = KamisClient(
        settings, session, StructuredLogger(logging.getLogger("test.kamis.auth"))
    )
    query = PriceQuery(
        price_type=PriceType.WHOLESALE,
        start_date=date(2026, 9, 24),
        end_date=date(2026, 9, 24),
        catalog_entry=ProductCatalogEntry.from_api(CATALOG_ROW),
        rank_code="04",
    )

    with (
        caplog.at_level(logging.ERROR, logger="test.kamis.auth"),
        pytest.raises(KamisAuthenticationError),
    ):
        client.fetch_prices(query)

    assert settings.kamis_cert_key not in caplog.text
    assert settings.kamis_cert_id not in caplog.text


def test_no_data_response_returns_empty_list(settings: Settings) -> None:
    session = FakeSession()
    session.queue_json({"error_code": "001", "error_message": "no data"})
    client = KamisClient(
        settings, session, StructuredLogger(logging.getLogger("test.kamis.empty"))
    )
    query = PriceQuery(
        price_type=PriceType.RETAIL,
        start_date=date(2026, 9, 24),
        end_date=date(2026, 9, 24),
        catalog_entry=ProductCatalogEntry.from_api(CATALOG_ROW),
        rank_code="04",
    )

    assert client.fetch_prices(query) == []
