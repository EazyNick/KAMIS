from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.domain.models import ProductCatalogEntry
from app.domain.online_models import PlatformPriceSummary, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
from app.services.online_pricing import OnlinePriceCalculator
from log.context_logger import ContextLogger


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
        logger: ContextLogger,
    ) -> None:
        self._sources = sources
        self._repository = repository
        self._calculator = calculator
        self._logger = logger

    def collect(
        self,
        catalog: list[ProductCatalogEntry],
        observed_date: date,
        run_id: str,
    ) -> OnlineCollectionResult:
        offers: list[ShoppingOffer] = []
        summaries: list[PlatformPriceSummary] = []
        errors: list[str] = []
        for entry in catalog:
            item_summaries: list[PlatformPriceSummary] = []
            for source in self._sources:
                try:
                    found = source.search(entry, observed_date)
                except Exception as error:
                    found = []
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
                summaries.append(summary)
                item_summaries.append(summary)
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
                )
            )
        self._repository.save_daily(offers, summaries, observed_date, run_id)
        self._logger.info(  # noqa: PLE1205
            "online.collection.completed",
            "Online price collection completed",
            run_id=run_id,
            source_count=len(self._sources),
            catalog_count=len(catalog),
            record_count=len(offers),
            summary_count=len(summaries),
            error_count=len(errors),
        )
        return OnlineCollectionResult(
            len(offers), len(summaries), len(errors), tuple(errors)
        )
