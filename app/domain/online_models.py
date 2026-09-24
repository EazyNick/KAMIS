from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.core.errors import DataValidationError


class MatchStatus(StrEnum):
    EXACT = "exact"
    COMPATIBLE = "compatible"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ShoppingOffer:
    platform: str
    product_id: str
    title: str
    url: str
    item_code: str
    kind_code: str
    match_status: MatchStatus
    base_price: Decimal
    member_price: Decimal | None
    member_discount_scope: str | None
    shipping_fee: Decimal
    quantity: Decimal
    unit: str
    available: bool
    observed_date: date | None = None
    collected_at: datetime | None = None
    seller: str | None = None
    origin: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.base_price < 0 or self.shipping_fee < 0:
            raise DataValidationError("offer prices cannot be negative")
        if self.quantity <= 0:
            raise DataValidationError("offer quantity must be positive")

    @property
    def eligible_price(self) -> Decimal:
        if (
            self.member_price is not None
            and self.member_discount_scope == "all_members"
        ):
            return self.member_price
        return self.base_price

    @property
    def comparable_total(self) -> Decimal:
        return self.eligible_price + self.shipping_fee

    @property
    def unit_price(self) -> Decimal:
        return self.comparable_total / self.quantity

    @property
    def is_comparable(self) -> bool:
        return self.available and self.match_status in {
            MatchStatus.EXACT,
            MatchStatus.COMPATIBLE,
        }

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["match_status"] = self.match_status.value
        for key in (
            "base_price",
            "member_price",
            "shipping_fee",
            "quantity",
        ):
            value = row[key]
            row[key] = str(value) if value is not None else None
        row["unit_price"] = str(self.unit_price)
        row["comparable_total"] = str(self.comparable_total)
        row["observed_date"] = (
            self.observed_date.isoformat() if self.observed_date else None
        )
        row["collected_at"] = (
            self.collected_at.isoformat() if self.collected_at else None
        )
        return row


@dataclass(frozen=True, slots=True)
class PlatformPriceSummary:
    platform: str
    item_code: str
    kind_code: str
    average_unit_price: Decimal | None
    sample_count: int
    candidate_count: int
    included_offers: tuple[ShoppingOffer, ...]
    excluded_offers: tuple[ShoppingOffer, ...]
    collection_status: str = "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "item_code": self.item_code,
            "kind_code": self.kind_code,
            "average_unit_price": (
                str(self.average_unit_price)
                if self.average_unit_price is not None
                else None
            ),
            "sample_count": self.sample_count,
            "candidate_count": self.candidate_count,
            "collection_status": self.collection_status,
        }
