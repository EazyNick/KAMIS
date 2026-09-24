from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from time import perf_counter
from typing import Any, Protocol, cast
from zoneinfo import ZoneInfo

import requests
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.errors import KamisApiError, KamisAuthenticationError
from app.domain.models import (
    PriceObservation,
    PriceQuery,
    PriceType,
    ProductCatalogEntry,
)
from config.server_config import Settings
from log.context_logger import ContextLogger


class ResponseLike(Protocol):
    status_code: int

    def raise_for_status(self) -> None: ...

    def json(self) -> dict[str, Any]: ...


class SessionLike(Protocol):
    def get(
        self, url: str, *, params: dict[str, str], timeout: float
    ) -> ResponseLike: ...


class KamisClient:
    def __init__(
        self,
        settings: Settings,
        session: SessionLike,
        logger: ContextLogger,
    ) -> None:
        self._settings = settings
        self._session = session
        self._logger = logger
        self._retrying = Retrying(
            retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.2, min=0.2, max=2),
            reraise=True,
        )

    def _request_once(self, action: str, params: dict[str, str]) -> dict[str, Any]:
        response = self._session.get(
            self._settings.kamis_base_url,
            params={"action": action, **params},
            timeout=self._settings.request_timeout_seconds,
        )
        if response.status_code == 429 or response.status_code >= 500:
            raise requests.ConnectionError(f"retryable HTTP status {response.status_code}")
        response.raise_for_status()
        return response.json()

    def _get(self, action: str, params: dict[str, str]) -> dict[str, Any] | None:
        started = perf_counter()
        context = {"source": "kamis", "action": action}
        self._logger.info("kamis.request.started", "KAMIS request started", **context)
        try:
            payload = self._retrying(self._request_once, action, params)
            code = self._error_code(payload)
            if code == "001":
                self._logger.info(
                    "kamis.request.no_data",
                    "KAMIS returned no data",
                    **context,
                    duration_ms=round((perf_counter() - started) * 1000),
                )
                return None
            if code == "900":
                raise KamisAuthenticationError(code, self._extract_message(payload))
            if code != "000":
                raise KamisApiError(code, self._extract_message(payload))
            self._logger.info(
                "kamis.request.succeeded",
                "KAMIS request completed",
                **context,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return payload
        except Exception as error:
            self._logger.exception(
                "kamis.request.failed",
                "KAMIS request failed",
                error,  # noqa: TRY401 - ContextLogger records explicit error metadata
                **context,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise

    @staticmethod
    def _error_code(payload: Mapping[str, Any]) -> str:
        direct = payload.get("error_code") or payload.get("code")
        if direct is not None:
            return str(direct)
        data = payload.get("data")
        if isinstance(data, Mapping):
            nested = data.get("error_code") or data.get("code")
            if nested is not None:
                return str(nested)
        return "000"

    @staticmethod
    def _extract_message(payload: Mapping[str, Any]) -> str:
        for key in ("error_message", "message", "Message"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data")
        if isinstance(data, Mapping):
            for key in ("error_message", "message", "Message"):
                value = data.get(key)
                if value:
                    return str(value)
        return "unknown KAMIS error"

    def fetch_catalog(self) -> list[ProductCatalogEntry]:
        payload = self._get("productInfo", {"p_returntype": "json"})
        if payload is None:
            return []
        raw_rows = payload.get("info", [])
        if not isinstance(raw_rows, list):
            raise KamisApiError("PARSE", "productInfo.info is not a list")
        return [
            ProductCatalogEntry.from_api(cast(dict[str, object], row))
            for row in raw_rows
            if isinstance(row, dict)
        ]

    def fetch_prices(self, query: PriceQuery) -> list[PriceObservation]:
        cert_key, cert_id = self._settings.require_kamis_credentials()
        action = (
            "periodWholesaleProductList"
            if query.price_type is PriceType.WHOLESALE
            else "periodRetailProductList"
        )
        params = {
            "p_startday": query.start_date.isoformat(),
            "p_endday": query.end_date.isoformat(),
            "p_itemcategorycode": query.catalog_entry.category_code,
            "p_itemcode": query.catalog_entry.item_code,
            "p_kindcode": query.catalog_entry.kind_code,
            "p_productrankcode": query.rank_code,
            "p_countrycode": query.country_code or "",
            "p_convert_kg_yn": "Y" if query.convert_kg else "N",
            "p_cert_key": cert_key,
            "p_cert_id": cert_id,
            "p_returntype": "json",
        }
        payload = self._get(action, params)
        if payload is None:
            return []
        raw_data = payload.get("data", [])
        if isinstance(raw_data, Mapping):
            raw_rows = raw_data.get("item", raw_data.get("items", []))
        else:
            raw_rows = raw_data
        if isinstance(raw_rows, Mapping):
            raw_rows = [raw_rows]
        if not isinstance(raw_rows, list):
            raise KamisApiError("PARSE", "price data is not a list")
        collected_at = datetime.now(ZoneInfo(self._settings.timezone))
        return [
            PriceObservation.from_api(cast(dict[str, object], row), query, collected_at)
            for row in raw_rows
            if isinstance(row, dict)
        ]


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "KAMIS-Research-Dashboard/0.1"})
    return session
