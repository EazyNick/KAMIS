from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, datetime
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
from app.infrastructure.kamis_catalog_overrides import apply_verified_overrides
from config.server_config import Settings
from log.logger import StructuredLogger


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
        logger: StructuredLogger,
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
            raise requests.ConnectionError(
                f"retryable HTTP status {response.status_code}"
            )
        response.raise_for_status()
        return response.json()

    def _get(self, action: str, params: dict[str, str]) -> dict[str, Any] | None:
        started = perf_counter()
        context = {"source": "kamis", "action": action}
        self._logger.debug(
            "kamis.request.started",
            "KAMIS HTTP request started",
            **context,
        )
        try:
            payload = self._retrying(self._request_once, action, params)
            code = self._error_code(payload)
            if code == "001":
                self._logger.debug(
                    "kamis.request.no_data",
                    "KAMIS HTTP response contained no data",
                    **context,
                    duration_ms=round((perf_counter() - started) * 1000),
                )
                return None
            if code == "900":
                raise KamisAuthenticationError(code, self._extract_message(payload))
            if code != "000":
                raise KamisApiError(code, self._extract_message(payload))
            self._logger.debug(
                "kamis.request.succeeded",
                "KAMIS HTTP request completed",
                **context,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return payload
        except Exception as error:
            self._logger.exception(
                "kamis.request.failed",
                "KAMIS request failed",
                error,  # noqa: TRY401 - StructuredLogger records error metadata
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
        return apply_verified_overrides([
            ProductCatalogEntry.from_api(cast(dict[str, object], row))
            for row in raw_rows
            if isinstance(row, dict)
        ])

    def fetch_prices(self, query: PriceQuery) -> list[PriceObservation]:
        if query.price_type is PriceType.ECO and query.start_date.year != query.end_date.year:
            boundary = date(query.start_date.year, 12, 31)
            return self.fetch_prices(replace(query, end_date=boundary)) + self.fetch_prices(
                replace(query, start_date=date(boundary.year + 1, 1, 1))
            )
        cert_key, cert_id = self._settings.require_kamis_credentials()
        action = (
            "periodWholesaleProductList"
            if query.price_type is PriceType.WHOLESALE
            else "periodRetailProductList"
        )
        if query.price_type is PriceType.ECO:
            action = "periodEcoPriceList"
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
        price_label = (
            "도매" if query.price_type is PriceType.WHOLESALE else "소매"
        )
        if query.price_type is PriceType.ECO:
            price_label = "친환경 소매"
        log_context = {
            "item_name": query.catalog_entry.item_name,
            "item_code": query.catalog_entry.item_code,
            "kind_code": query.catalog_entry.kind_code,
            "price_type": query.price_type.value,
            "rank_code": query.rank_code,
            "start_date": query.start_date,
            "end_date": query.end_date,
            "convert_kg": "Y" if query.convert_kg else "N",
        }
        self._logger.info(
            "kamis.price.fetch.started",
            f"[수집] {query.catalog_entry.item_name} {price_label} "
            f"rank={query.rank_code} {query.start_date}~{query.end_date} "
            "KAMIS API 요청",
            **log_context,
        )
        fetch_started = perf_counter()
        payload = self._get(action, params)
        if payload is None:
            self._logger.info(
                "kamis.price.fetch.completed",
                f"[완료] {query.catalog_entry.item_name} {price_label} "
                f"rank={query.rank_code} 수집 결과 없음",
                **log_context,
                returned_records=0,
                official_average_records=0,
                duration_ms=round((perf_counter() - fetch_started) * 1000),
            )
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
        observations = [
            PriceObservation.from_api(
                {"yyyy": str(query.start_date.year), **row}
                if query.price_type is PriceType.ECO else cast(dict[str, object], row),
                query, collected_at,
            )
            for row in raw_rows
            if isinstance(row, dict)
        ]
        official_average_count = sum(
            1 for row in observations if row.region == "평균"
        )
        self._logger.info(
            "kamis.price.fetch.completed",
            f"[완료] {query.catalog_entry.item_name} {price_label} "
            f"rank={query.rank_code} API {len(observations)}건 / "
            f"대시보드 평균값 {official_average_count}건",
            **log_context,
            returned_records=len(observations),
            official_average_records=official_average_count,
            duration_ms=round((perf_counter() - fetch_started) * 1000),
        )
        return observations


def build_requests_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": "KAMIS-Research-Dashboard/0.1"})
    return session
