import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.domain.online_models import MatchStatus, PlatformPriceSummary, ShoppingOffer
from app.infrastructure.online_repository import OnlinePriceRepository
from log import app_logger


def test_online_repository_persists_offers_and_summary(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    row = ShoppingOffer(
        platform="naver",
        product_id="p1",
        title="쌀 1kg",
        url="https://example.test/p1",
        item_code="111",
        kind_code="01",
        match_status=MatchStatus.EXACT,
        base_price=Decimal(1000),
        member_price=None,
        member_discount_scope=None,
        shipping_fee=Decimal(0),
        quantity=Decimal(1),
        unit="kg",
        available=True,
        observed_date=date(2026, 9, 24),
    )
    summary = PlatformPriceSummary(
        "naver", "111", "01", Decimal(1000), 1, 1, (row,), ()
    )

    repository.save_daily([row], [summary], date(2026, 9, 24), "run-1")

    assert repository.search_offers(item_code="111")[0]["platform"] == "naver"
    assert repository.search_summaries(item_code="111")[0]["sample_count"] == "1"


def test_platform_runs_preserve_other_platform_raw_offers(tmp_path: Path) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    observed = date(2026, 9, 25)

    def offer(platform: str) -> ShoppingOffer:
        return ShoppingOffer(
            platform=platform,
            product_id=f"{platform}-1",
            title="쌀 1kg",
            url=f"https://example.test/{platform}",
            item_code="111",
            kind_code="01",
            match_status=MatchStatus.EXACT,
            base_price=Decimal(1000),
            member_price=None,
            member_discount_scope=None,
            shipping_fee=Decimal(0),
            quantity=Decimal(1),
            unit="kg",
            available=True,
            observed_date=observed,
        )

    for platform in ("naver", "coupang"):
        row = offer(platform)
        summary = PlatformPriceSummary(
            platform, "111", "01", Decimal(1000), 1, 1, (row,), ()
        )
        repository.save_daily([row], [summary], observed, f"run-{platform}")

    raw_path = tmp_path / "raw/online/2026-09-25/offers.csv"
    with raw_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))

    assert {row["platform"] for row in rows} == {"naver", "coupang"}


def test_repository_reports_completed_platform_keys_and_one_summary(
    tmp_path: Path,
) -> None:
    repository = OnlinePriceRepository(tmp_path, app_logger)
    observed = date(2026, 9, 26)
    summary = PlatformPriceSummary(
        "naver", "111", "01", Decimal("1000"), 1, 1, (), ()
    )
    repository.save_daily([], [summary], observed, "run-1")

    assert repository.completed_platform_keys(observed) == {
        ("naver", "111", "01")
    }
    assert repository.summary_for_date(observed, "naver", "111", "01") == {
        "platform": "naver",
        "item_code": "111",
        "kind_code": "01",
        "average_unit_price": "1000",
        "sample_count": "1",
        "candidate_count": "1",
        "collection_status": "available",
        "observed_date": "2026-09-26",
    }
