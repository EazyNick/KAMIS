from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.errors import DataValidationError, InvalidRunTransition


def optional_text(value: object) -> str | None:
    if value is None or value == "" or value == [] or value == {}:
        return None
    text = str(value).strip()
    return text or None


def split_codes(value: object) -> tuple[str, ...]:
    text = optional_text(value)
    if text is None:
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


class PriceType(StrEnum):
    WHOLESALE = "wholesale"
    RETAIL = "retail"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ProductCatalogEntry:
    category_code: str
    category_name: str
    item_code: str
    item_name: str
    kind_code: str
    variety: str
    wholesale_unit: str | None
    wholesale_unit_size: str | None
    retail_unit: str | None
    retail_unit_size: str | None
    eco_unit: str | None
    eco_unit_size: str | None
    wholesale_rank_codes: tuple[str, ...]
    retail_rank_codes: tuple[str, ...]
    eco_rank_codes: tuple[str, ...]

    @classmethod
    def from_api(cls, data: dict[str, object]) -> ProductCatalogEntry:
        required = {
            "itemcategorycode": "category_code",
            "itemcategoryname": "category_name",
            "itemcode": "item_code",
            "itemname": "item_name",
            "kindcode": "kind_code",
            "kindname": "variety",
        }
        normalized: dict[str, str] = {}
        for source, target in required.items():
            value = optional_text(data.get(source))
            if value is None:
                raise DataValidationError(f"missing catalog field: {source}")
            normalized[target] = value
        return cls(
            **normalized,
            wholesale_unit=optional_text(data.get("wholesale_unit")),
            wholesale_unit_size=optional_text(data.get("wholesale_unitsize")),
            retail_unit=optional_text(data.get("retail_unit")),
            retail_unit_size=optional_text(data.get("retail_unitsize")),
            eco_unit=optional_text(data.get("eco_unit")),
            eco_unit_size=optional_text(data.get("eco_unitsize")),
            wholesale_rank_codes=split_codes(data.get("whole_productrankcode")),
            retail_rank_codes=split_codes(data.get("retail_productrankcode")),
            eco_rank_codes=split_codes(data.get("new_natreu_productrankcode")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("wholesale_rank_codes", "retail_rank_codes", "eco_rank_codes"):
            result[key] = ",".join(result[key])
        return result


@dataclass(frozen=True, slots=True)
class PriceQuery:
    price_type: PriceType
    start_date: date
    end_date: date
    catalog_entry: ProductCatalogEntry
    rank_code: str
    country_code: str | None = None
    convert_kg: bool = True

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise DataValidationError("end date precedes start date")
        if (self.end_date - self.start_date).days > 365:
            raise DataValidationError("KAMIS query cannot exceed one year")


@dataclass(frozen=True, slots=True)
class PriceObservation:
    price_type: PriceType
    observed_date: date
    collected_at: datetime
    category_code: str
    item_code: str
    kind_code: str
    rank_code: str
    item_name: str
    variety: str
    region: str | None
    market_name: str | None
    price_krw: Decimal | None
    requested_convert_kg: bool

    @staticmethod
    def parse_price(value: object) -> Decimal | None:
        text = optional_text(value)
        if text in {None, "-"}:
            return None
        try:
            price = Decimal(text.replace(",", ""))
        except (InvalidOperation, AttributeError) as error:
            raise DataValidationError(f"invalid price: {value!r}") from error
        if price < 0:
            raise DataValidationError("negative price is not allowed")
        return price

    @classmethod
    def from_api(
        cls,
        data: dict[str, object],
        query: PriceQuery,
        collected_at: datetime,
    ) -> PriceObservation:
        regday = optional_text(data.get("regday"))
        if regday is None:
            raise DataValidationError("missing price field: regday")
        return cls(
            price_type=query.price_type,
            observed_date=date.fromisoformat(regday),
            collected_at=collected_at,
            category_code=query.catalog_entry.category_code,
            item_code=query.catalog_entry.item_code,
            kind_code=query.catalog_entry.kind_code,
            rank_code=query.rank_code,
            item_name=optional_text(data.get("itemname")) or query.catalog_entry.item_name,
            variety=optional_text(data.get("kindname")) or query.catalog_entry.variety,
            region=optional_text(data.get("countyname")),
            market_name=optional_text(data.get("marketname")),
            price_krw=cls.parse_price(data.get("price")),
            requested_convert_kg=query.convert_kg,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["price_type"] = self.price_type.value
        result["observed_date"] = self.observed_date.isoformat()
        result["collected_at"] = self.collected_at.isoformat()
        result["price_krw"] = str(self.price_krw) if self.price_krw is not None else None
        return result


@dataclass(frozen=True, slots=True)
class CollectionError:
    scope: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class CollectionRun:
    run_id: str
    source: str
    requested_start: date
    requested_end: date
    started_at: datetime
    finished_at: datetime | None
    status: RunStatus
    record_count: int
    error_count: int
    errors: tuple[CollectionError, ...] = ()

    @classmethod
    def start(
        cls, source: str, requested_start: date, requested_end: date
    ) -> CollectionRun:
        return cls(
            run_id=uuid4().hex,
            source=source,
            requested_start=requested_start,
            requested_end=requested_end,
            started_at=datetime.now(ZoneInfo("Asia/Seoul")),
            finished_at=None,
            status=RunStatus.RUNNING,
            record_count=0,
            error_count=0,
        )

    def finish(
        self,
        status: RunStatus,
        *,
        record_count: int,
        error_count: int,
        errors: tuple[CollectionError, ...] = (),
    ) -> CollectionRun:
        if self.status is not RunStatus.RUNNING:
            raise InvalidRunTransition(f"run is already {self.status.value}")
        if status is RunStatus.RUNNING:
            raise InvalidRunTransition("cannot finish a run as running")
        return replace(
            self,
            finished_at=datetime.now(ZoneInfo("Asia/Seoul")),
            status=status,
            record_count=record_count,
            error_count=error_count,
            errors=errors,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["requested_start"] = self.requested_start.isoformat()
        result["requested_end"] = self.requested_end.isoformat()
        result["started_at"] = self.started_at.isoformat()
        result["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        result["status"] = self.status.value
        return result


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date
