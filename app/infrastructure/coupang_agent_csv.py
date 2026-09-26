from __future__ import annotations

import csv
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar

from app.core.errors import DataValidationError
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer

CatalogKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class CoupangCsvResult:
    offers_by_key: dict[CatalogKey, list[ShoppingOffer]]
    failed_keys: frozenset[CatalogKey]
    invalid_row_count: int
    errors: Sequence[str]


class CoupangAgentCsvParser:
    """Validate untrusted agent CSV and convert it to auditable offers."""

    _required_columns: ClassVar[set[str]] = {
        "run_id",
        "observed_date",
        "collected_at",
        "platform",
        "item_code",
        "kind_code",
        "query",
        "product_id",
        "title",
        "url",
        "displayed_price",
        "shipping_fee",
        "member_price",
        "member_discount_scope",
        "quantity",
        "unit",
        "unit_price_text",
        "advertisement",
        "availability",
        "raw_accessible_name",
    }
    _formula_prefixes = ("=", "+", "-", "@")
    _forbidden_product_keywords = (
        "모종",
        "묘목",
        "냉동",
        "사진",
        "주스용",
        "씨앗",
        "종자",
    )
    _unit_aliases: ClassVar[dict[str, tuple[str, Decimal]]] = {
        "kg": ("weight", Decimal(1000)),
        "킬로그램": ("weight", Decimal(1000)),
        "g": ("weight", Decimal(1)),
        "그램": ("weight", Decimal(1)),
        "l": ("volume", Decimal(1000)),
        "리터": ("volume", Decimal(1000)),
        "ml": ("volume", Decimal(1)),
        "개": ("count", Decimal(1)),
        "포기": ("head", Decimal(1)),
        "마리": ("fish", Decimal(1)),
        "봉": ("bag", Decimal(1)),
        "팩": ("pack", Decimal(1)),
    }

    def parse(
        self,
        path: Path,
        manifest: Mapping[str, object],
        catalog_by_key: Mapping[CatalogKey, ProductCatalogEntry],
    ) -> CoupangCsvResult:
        run_id = str(manifest.get("run_id", ""))
        observed_date_text = str(manifest.get("observed_date", ""))
        try:
            observed_date = date.fromisoformat(observed_date_text)
        except ValueError as error:
            raise DataValidationError("manifest observed_date is invalid") from error
        target_keys = self._manifest_keys(manifest)
        missing_catalog_keys = target_keys.difference(catalog_by_key)
        if missing_catalog_keys:
            missing_text = ", ".join(
                f"{item_code}:{kind_code}"
                for item_code, kind_code in sorted(missing_catalog_keys)
            )
            raise DataValidationError(
                f"manifest targets are missing from catalog: {missing_text}"
            )
        offers_by_key = {key: [] for key in target_keys}
        seen: set[tuple[str, str, str]] = set()
        errors: list[str] = []
        invalid_row_count = 0

        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            missing = self._required_columns.difference(reader.fieldnames or ())
            if missing:
                raise DataValidationError(
                    f"Coupang agent CSV is missing columns: {', '.join(sorted(missing))}"
                )
            for row_number, row in enumerate(reader, start=2):
                self._validate_integrity(
                    row,
                    row_number=row_number,
                    run_id=run_id,
                    observed_date=observed_date_text,
                    target_keys=target_keys,
                )
                key = (row["item_code"], row["kind_code"])
                dedupe_key = (*key, row["product_id"])
                if dedupe_key in seen:
                    invalid_row_count += 1
                    errors.append(f"row {row_number}: duplicate product_id")
                    continue
                seen.add(dedupe_key)
                try:
                    offer = self._to_offer(
                        row,
                        entry=catalog_by_key[key],
                        observed_date=observed_date,
                    )
                except (DataValidationError, InvalidOperation, ValueError) as error:
                    invalid_row_count += 1
                    errors.append(f"row {row_number}: {error}")
                    continue
                offers_by_key[key].append(offer)

        failed_keys = frozenset(
            key
            for key, offers in offers_by_key.items()
            if not any(offer.is_comparable for offer in offers)
        )
        return CoupangCsvResult(
            offers_by_key=offers_by_key,
            failed_keys=failed_keys,
            invalid_row_count=invalid_row_count,
            errors=tuple(errors),
        )

    def _manifest_keys(self, manifest: Mapping[str, object]) -> frozenset[CatalogKey]:
        raw_targets = manifest.get("targets")
        if not isinstance(raw_targets, list):
            raise DataValidationError("manifest targets are invalid")
        keys: set[CatalogKey] = set()
        for target in raw_targets:
            if not isinstance(target, Mapping):
                raise DataValidationError("manifest target is invalid")
            keys.add((str(target.get("item_code", "")), str(target.get("kind_code", ""))))
        if not keys:
            raise DataValidationError("manifest has no targets")
        return frozenset(keys)

    def _validate_integrity(
        self,
        row: Mapping[str, str],
        *,
        row_number: int,
        run_id: str,
        observed_date: str,
        target_keys: frozenset[CatalogKey],
    ) -> None:
        for field, value in row.items():
            if value and value.startswith(self._formula_prefixes):
                raise DataValidationError(
                    f"row {row_number} field {field} starts with spreadsheet formula prefix"
                )
        key = (row["item_code"], row["kind_code"])
        if (
            row["run_id"] != run_id
            or row["observed_date"] != observed_date
            or row["platform"] != "coupang"
            or key not in target_keys
        ):
            raise DataValidationError(f"row {row_number} does not match manifest")

    def _to_offer(
        self,
        row: Mapping[str, str],
        *,
        entry: ProductCatalogEntry,
        observed_date: date,
    ) -> ShoppingOffer:
        title = row["title"].strip()
        if not title or not row["product_id"].strip():
            raise DataValidationError("title and product_id are required")
        displayed_price = self._optional_decimal(row["displayed_price"], "displayed_price")
        member_price = self._optional_decimal(row["member_price"], "member_price")
        shipping_fee = self._optional_decimal(row["shipping_fee"], "shipping_fee")
        scope = row["member_discount_scope"].strip() or "unknown"

        exclusion_reason: str | None = None
        if any(keyword in title for keyword in self._forbidden_product_keywords):
            exclusion_reason = "forbidden_product_type"
        elif self._normalized(entry.item_name) not in self._normalized(title):
            exclusion_reason = "item_name_mismatch"

        if displayed_price is None:
            if scope == "all_members" and member_price is not None:
                displayed_price = member_price
            elif scope == "restricted" and member_price is not None:
                displayed_price = member_price
                exclusion_reason = exclusion_reason or "restricted_discount_only"
            else:
                raise DataValidationError("offer has no usable price")

        offered_quantity = self._positive_decimal(row["quantity"], "quantity")
        try:
            quantity = self.target_quantity(offered_quantity, row["unit"], entry)
        except DataValidationError:
            quantity = Decimal(1)
            exclusion_reason = exclusion_reason or "incompatible_unit"

        if shipping_fee is None:
            shipping_fee = Decimal(0)
            exclusion_reason = exclusion_reason or "shipping_unknown"
        if row["availability"] not in {"available", "sold_out"}:
            exclusion_reason = exclusion_reason or "availability_unknown"

        match_status = self._match_status(title, entry)
        if exclusion_reason is not None:
            match_status = MatchStatus.REJECTED
        try:
            collected_at = datetime.fromisoformat(row["collected_at"])
        except ValueError as error:
            raise DataValidationError("collected_at is invalid") from error

        return ShoppingOffer(
            platform="coupang",
            product_id=row["product_id"].strip(),
            title=title,
            url=row["url"].strip(),
            item_code=entry.item_code,
            kind_code=entry.kind_code,
            match_status=match_status,
            base_price=displayed_price,
            member_price=member_price,
            member_discount_scope=scope,
            shipping_fee=shipping_fee,
            quantity=quantity,
            unit="kamis_retail_unit",
            available=row["availability"] == "available",
            observed_date=observed_date,
            collected_at=collected_at,
            exclusion_reason=exclusion_reason,
        )

    @classmethod
    def target_quantity(
        cls,
        offered_quantity: Decimal,
        offered_unit: str,
        entry: ProductCatalogEntry,
    ) -> Decimal:
        if entry.retail_unit is None or entry.retail_unit_size is None:
            raise DataValidationError("KAMIS retail unit is unavailable")
        target_size = cls._positive_decimal(entry.retail_unit_size, "retail_unit_size")
        source_size, source_unit = cls.normalize_measure(
            offered_quantity, offered_unit
        )
        normalized_target_size, target_unit = cls.normalize_measure(
            target_size, entry.retail_unit
        )
        if source_unit != target_unit:
            raise DataValidationError("offer unit cannot convert to KAMIS retail unit")
        return source_size / normalized_target_size

    @classmethod
    def normalize_measure(
        cls, quantity: Decimal, unit: str
    ) -> tuple[Decimal, str]:
        normalized_unit = re.sub(r"\s+", "", unit).casefold()
        try:
            dimension, multiplier = cls._unit_aliases[normalized_unit]
        except KeyError as error:
            raise DataValidationError(f"unsupported offer unit: {unit}") from error
        return quantity * multiplier, dimension

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"\s+", "", value).casefold()

    @classmethod
    def _match_status(
        cls, title: str, entry: ProductCatalogEntry
    ) -> MatchStatus:
        normalized = cls._normalized(title)
        if cls._normalized(entry.item_name) not in normalized:
            return MatchStatus.REJECTED
        variety = cls._normalized(entry.variety)
        return MatchStatus.EXACT if variety and variety in normalized else MatchStatus.COMPATIBLE

    @staticmethod
    def _optional_decimal(value: str, field: str) -> Decimal | None:
        if not value.strip():
            return None
        parsed = Decimal(value.replace(",", ""))
        if parsed < 0:
            raise DataValidationError(f"{field} cannot be negative")
        return parsed

    @classmethod
    def _positive_decimal(cls, value: str, field: str) -> Decimal:
        parsed = cls._optional_decimal(value, field)
        if parsed is None or parsed <= 0:
            raise DataValidationError(f"{field} must be positive")
        return parsed
