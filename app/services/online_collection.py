from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Protocol

from app.core.errors import ShoppingAccessBlocked
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import PlatformPriceSummary, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
from app.services.online_pricing import OnlinePriceCalculator
from log.logger import StructuredLogger


class ShoppingSourceProtocol(Protocol):
    platform: str

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]: ...


@dataclass(frozen=True, slots=True)
class OnlineCollectionResult:
    offer_count: int
    summary_count: int
    error_count: int
    errors: tuple[str, ...]


class OnlineCollectionService:
    def __init__(
        self,
        sources: list[ShoppingSourceProtocol],
        repository: OnlinePriceRepository,
        calculator: OnlinePriceCalculator,
        logger: StructuredLogger,
        *,
        target_keys: set[tuple[str, str]] | None = None,
    ) -> None:
        self._sources = sources
        self._repository = repository
        self._calculator = calculator
        self._logger = logger
        self._target_keys = frozenset(target_keys) if target_keys is not None else None

    def has_collected_date(
        self, catalog: list[ProductCatalogEntry], observed_date: date
    ) -> bool:
        selected_keys = {
            (entry.item_code, entry.kind_code)
            for entry in catalog
            if self._target_keys is None
            or (entry.item_code, entry.kind_code) in self._target_keys
        }
        if not selected_keys:
            return False
        platforms = tuple(source.platform for source in self._sources) + ("combined",)
        expected = {
            (platform, item_code, kind_code)
            for item_code, kind_code in selected_keys
            for platform in platforms
        }
        completed = {
            (
                row.get("platform", ""),
                row.get("item_code", ""),
                row.get("kind_code", ""),
            )
            for row in self._repository.summaries_for_date(observed_date)
            if row.get("collection_status") not in {"blocked", "collection_failed"}
        }
        return expected.issubset(completed)

    def collect(
        self,
        catalog: list[ProductCatalogEntry],
        observed_date: date,
        run_id: str,
        *,
        include_combined: bool = True,
    ) -> OnlineCollectionResult:
        offers: list[ShoppingOffer] = []
        summaries: list[PlatformPriceSummary] = []
        errors: list[str] = []
        blocked_sources: set[str] = set()
        if self._target_keys is None:
            selected_catalog = catalog
        else:
            selected_by_key = {
                (entry.item_code, entry.kind_code): entry
                for entry in catalog
                if (entry.item_code, entry.kind_code) in self._target_keys
            }
            selected_catalog = list(selected_by_key.values())
            missing_targets = self._target_keys - selected_by_key.keys()
            if missing_targets:
                self._logger.warning(  # noqa: PLE1205
                    "online.collection.targets.missing",
                    "Configured online targets were absent from the KAMIS catalog",
                    run_id=run_id,
                    missing_count=len(missing_targets),
                    missing_targets=",".join(
                        f"{item_code}:{kind_code}"
                        for item_code, kind_code in sorted(missing_targets)
                    ),
                )
        for entry in selected_catalog:
            item_summaries: list[PlatformPriceSummary] = []
            for source in self._sources:
                source_failed = False
                source_blocked = source.platform in blocked_sources
                found: list[ShoppingOffer] = []
                if not source_blocked:
                    try:
                        found = source.search(entry, observed_date)
                    except ShoppingAccessBlocked as error:
                        source_blocked = True
                        blocked_sources.add(source.platform)
                        scope = f"{source.platform}:{entry.item_code}:{entry.kind_code}"
                        errors.append(f"{scope}:{type(error).__name__}:{error}")
                        self._logger.exception(  # noqa: PLE1205
                            "online.collection.source.blocked",
                            "Shopping source blocked; remaining targets will be skipped",
                            error,  # noqa: TRY401
                            run_id=run_id,
                            source=source.platform,
                            item_code=entry.item_code,
                            kind_code=entry.kind_code,
                            status_code=error.status_code,
                        )
                    except Exception as error:
                        source_failed = True
                        scope = f"{source.platform}:{entry.item_code}:{entry.kind_code}"
                        errors.append(f"{scope}:{type(error).__name__}:{error}")
                        self._logger.exception(  # noqa: PLE1205
                            "online.collection.item.failed",
                            "Online product search failed; collection will continue",
                            error,  # noqa: TRY401
                            run_id=run_id,
                            source=source.platform,
                            item_code=entry.item_code,
                            kind_code=entry.kind_code,
                        )
                offers.extend(found)
                summary = self._calculator.summarize(
                    source.platform,
                    entry.item_code,
                    entry.kind_code,
                    found,
                )
                if source_blocked:
                    summary = replace(summary, collection_status="blocked")
                elif source_failed:
                    summary = replace(summary, collection_status="collection_failed")
                summaries.append(summary)
                item_summaries.append(summary)
            if include_combined:
                combined = self._calculator.combined_average(item_summaries)
                summaries.append(
                    PlatformPriceSummary(
                        "combined",
                        entry.item_code,
                        entry.kind_code,
                        combined,
                        sum(summary.sample_count for summary in item_summaries),
                        sum(summary.candidate_count for summary in item_summaries),
                        (),
                        (),
                        (
                            "available"
                            if combined is not None
                            else (
                                "blocked"
                                if any(
                                    summary.collection_status == "blocked"
                                    for summary in item_summaries
                                )
                                else (
                                    "collection_failed"
                                    if any(
                                        summary.collection_status == "collection_failed"
                                        for summary in item_summaries
                                    )
                                    else "unavailable"
                                )
                            )
                        ),
                    )
                )
        self._repository.save_daily(offers, summaries, observed_date, run_id)
        self._logger.info(  # noqa: PLE1205
            "online.collection.completed",
            "Online price collection completed",
            run_id=run_id,
            source_count=len(self._sources),
            catalog_count=len(catalog),
            target_count=len(selected_catalog),
            record_count=len(offers),
            summary_count=len(summaries),
            error_count=len(errors),
        )
        return OnlineCollectionResult(
            len(offers), len(summaries), len(errors), tuple(errors)
        )
