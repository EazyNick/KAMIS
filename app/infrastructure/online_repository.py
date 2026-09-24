from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from app.domain.online_models import PlatformPriceSummary, ShoppingOffer
from app.infrastructure.csv_repository import _AtomicCsvRepository
from log.context_logger import ContextLogger


class OnlinePriceRepository:
    def __init__(self, data_dir: Path, logger: ContextLogger) -> None:
        self._offers = _AtomicCsvRepository(
            data_dir / "normalized" / "online_offers.csv", logger
        )
        self._summaries = _AtomicCsvRepository(
            data_dir / "normalized" / "online_price_summaries.csv", logger
        )
        self._decisions = _AtomicCsvRepository(
            data_dir / "normalized" / "online_offer_decisions.csv", logger
        )
        self._raw_root = data_dir / "raw" / "online"
        self._logger = logger

    @staticmethod
    def _upsert(
        existing: list[dict[str, str]],
        incoming: list[dict[str, Any]],
        keys: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        indexed: dict[tuple[str, ...], dict[str, Any]] = {
            tuple(str(row.get(key, "")) for key in keys): row for row in existing
        }
        for row in incoming:
            indexed[tuple(str(row.get(key, "")) for key in keys)] = row
        return list(indexed.values())

    def save_daily(
        self,
        offers: list[ShoppingOffer],
        summaries: list[PlatformPriceSummary],
        observed_date: date,
        run_id: str,
    ) -> None:
        offer_rows = [offer.to_dict() for offer in offers]
        summary_rows = [
            {**summary.to_dict(), "observed_date": observed_date.isoformat()}
            for summary in summaries
        ]
        decision_rows: list[dict[str, Any]] = []
        for summary in summaries:
            if summary.platform == "combined":
                continue
            decision_rows.extend(
                {
                    "observed_date": observed_date.isoformat(),
                    "platform": summary.platform,
                    "item_code": summary.item_code,
                    "kind_code": summary.kind_code,
                    "product_id": offer.product_id,
                    "included": True,
                    "exclusion_reason": None,
                    "unit_price": str(offer.unit_price),
                }
                for offer in summary.included_offers
            )
            decision_rows.extend(
                {
                    "observed_date": observed_date.isoformat(),
                    "platform": summary.platform,
                    "item_code": summary.item_code,
                    "kind_code": summary.kind_code,
                    "product_id": offer.product_id,
                    "included": False,
                    "exclusion_reason": offer.exclusion_reason,
                    "unit_price": str(offer.unit_price),
                }
                for offer in summary.excluded_offers
            )
        raw = _AtomicCsvRepository(
            self._raw_root / observed_date.isoformat() / "offers.csv", self._logger
        )
        raw._atomic_write(offer_rows, run_id)
        self._offers._atomic_write(
            self._upsert(
                self._offers._read(),
                offer_rows,
                ("observed_date", "platform", "item_code", "kind_code", "product_id"),
            ),
            run_id,
        )
        self._summaries._atomic_write(
            self._upsert(
                self._summaries._read(),
                summary_rows,
                ("observed_date", "platform", "item_code", "kind_code"),
            ),
            run_id,
        )
        self._decisions._atomic_write(
            self._upsert(
                self._decisions._read(),
                decision_rows,
                ("observed_date", "platform", "item_code", "kind_code", "product_id"),
            ),
            run_id,
        )

    def search_offers(
        self, *, item_code: str | None = None, platform: str | None = None
    ) -> list[dict[str, str]]:
        return [
            row
            for row in self._offers._read()
            if (item_code is None or row.get("item_code") == item_code)
            and (platform is None or row.get("platform") == platform)
        ]

    def search_summaries(
        self, *, item_code: str | None = None, platform: str | None = None
    ) -> list[dict[str, str]]:
        return [
            row
            for row in self._summaries._read()
            if (item_code is None or row.get("item_code") == item_code)
            and (platform is None or row.get("platform") == platform)
        ]

    def search_decisions(
        self, *, item_code: str | None = None, platform: str | None = None
    ) -> list[dict[str, str]]:
        return [
            row
            for row in self._decisions._read()
            if (item_code is None or row.get("item_code") == item_code)
            and (platform is None or row.get("platform") == platform)
        ]
