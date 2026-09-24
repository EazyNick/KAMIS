from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.core.errors import DataValidationError, InvalidRunTransition
from app.domain.models import (
    CollectionRun,
    PriceObservation,
    ProductCatalogEntry,
    RunStatus,
)


def test_catalog_entry_normalizes_empty_arrays() -> None:
    entry = ProductCatalogEntry.from_api(
        {
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
    )

    assert entry.eco_unit is None
    assert entry.wholesale_rank_codes == ("04",)
    assert entry.retail_rank_codes == ("04", "05")


def test_negative_price_is_rejected() -> None:
    with pytest.raises(DataValidationError, match="negative"):
        PriceObservation.parse_price("-1")


def test_price_parser_handles_commas_and_missing_values() -> None:
    assert PriceObservation.parse_price("1,234") == Decimal(1234)
    assert PriceObservation.parse_price("") is None
    assert PriceObservation.parse_price([]) is None


def test_finished_run_cannot_be_finished_twice() -> None:
    run = CollectionRun.start("kamis", date(2026, 9, 24), date(2026, 9, 24))
    finished = run.finish(RunStatus.SUCCESS, record_count=1, error_count=0)

    with pytest.raises(InvalidRunTransition):
        replace(finished).finish(RunStatus.FAILED, record_count=0, error_count=1)
