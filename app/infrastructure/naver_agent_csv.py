from collections.abc import Mapping
from datetime import date
from urllib.parse import urlsplit

from app.core.errors import DataValidationError
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import ShoppingOffer
from app.infrastructure.coupang_agent_csv import (
    CoupangCsvResult,
    ShoppingAgentCsvParser,
)


class NaverAgentCsvParser(ShoppingAgentCsvParser):
    """Validate Naver UI-agent rows using the shared shopping policy."""

    def __init__(self) -> None:
        super().__init__("naver")

    def _to_offer(
        self,
        row: Mapping[str, str],
        *,
        entry: ProductCatalogEntry,
        observed_date: date,
    ) -> ShoppingOffer:
        parsed_url = urlsplit(row["url"].strip())
        hostname = (parsed_url.hostname or "").casefold()
        if parsed_url.scheme != "https" or not (
            hostname == "naver.com" or hostname.endswith(".naver.com")
        ):
            raise DataValidationError("Naver offer URL must be an HTTPS naver.com URL")
        return super()._to_offer(row, entry=entry, observed_date=observed_date)


__all__ = ["CoupangCsvResult", "NaverAgentCsvParser"]
