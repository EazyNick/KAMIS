"""Supplement productInfo with period-API combinations verified on 2026-10-09.

September 2026 and November 2025 probes returned official-average prices.
Units come from the matching distribution channel in the bundled code workbook.
Existing combinations remain available for seasonal/historical observations.
"""

import json
from dataclasses import replace
from pathlib import Path

from app.domain.models import ProductCatalogEntry


def apply_verified_overrides(entries: list[ProductCatalogEntry]) -> list[ProductCatalogEntry]:
    path = Path(__file__).resolve().parents[2] / "config/kamis_verified_catalog_overrides.json"
    overrides = json.loads(path.read_text(encoding="utf-8"))
    result = []
    for entry in entries:
        changes = dict(overrides.get(f"{entry.item_code}:{entry.kind_code}", {}))
        for key in tuple(changes):
            if key.endswith("_rank_codes"):
                changes[key] = tuple(sorted(set(getattr(entry, key)) | set(changes[key])))
        result.append(replace(entry, **changes) if changes else entry)
    return result
