from __future__ import annotations

from decimal import Decimal

from app.domain.online_models import PlatformPriceSummary, ShoppingOffer


class OnlinePriceCalculator:
    """Applies the approved transparent offer-selection and averaging rules."""

    _minimum_ratio = Decimal("0.85")
    _maximum_sample = 5

    def summarize(
        self,
        platform: str,
        item_code: str,
        kind_code: str,
        offers: list[ShoppingOffer],
    ) -> PlatformPriceSummary:
        comparable = sorted(
            (offer for offer in offers if offer.is_comparable),
            key=lambda offer: offer.unit_price,
        )
        excluded = [offer for offer in offers if not offer.is_comparable]
        remaining = list(comparable)
        while len(remaining) > 1:
            cheapest = remaining[0]
            comparison = remaining[1 : 1 + self._maximum_sample]
            comparison_mean = sum(
                (offer.unit_price for offer in comparison), Decimal(0)
            ) / len(comparison)
            if cheapest.unit_price <= comparison_mean * self._minimum_ratio:
                excluded.append(remaining.pop(0))
                continue
            break
        included = remaining[: self._maximum_sample]
        excluded.extend(remaining[self._maximum_sample :])
        average = (
            sum((offer.unit_price for offer in included), Decimal(0)) / len(included)
            if included
            else None
        )
        return PlatformPriceSummary(
            platform=platform,
            item_code=item_code,
            kind_code=kind_code,
            average_unit_price=average,
            sample_count=len(included),
            candidate_count=len(offers),
            included_offers=tuple(included),
            excluded_offers=tuple(excluded),
        )

    @staticmethod
    def combined_average(
        summaries: list[PlatformPriceSummary],
    ) -> Decimal | None:
        values = [
            summary.average_unit_price
            for summary in summaries
            if summary.average_unit_price is not None
        ]
        return sum(values, Decimal(0)) / len(values) if values else None
