"""Print KAMIS melon prices without dashboard indexing or kg conversion.

Run: python scripts/inspect_melon_prices.py
Quick check: python scripts/inspect_melon_prices.py --start-date 2026-10-01
Requires the project's KAMIS credentials in .env. Does not write price data.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.models import PriceQuery, PriceType
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from config.server_config import Settings
from log import app_logger


def twenty_years_before(day: date) -> date:
    try:
        return day.replace(year=day.year - 20)
    except ValueError:
        return day.replace(year=day.year - 20, day=28)


def date_chunks(start: date, end: date):
    while start <= end:
        stop = min(start + timedelta(days=30), end)
        yield start, stop
        start = stop + timedelta(days=1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--price-type", choices=["both", "retail", "wholesale"], default="both")
    args = parser.parse_args(argv)
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = args.start_date or twenty_years_before(today)
    end = args.end_date or today
    if start > end or end > today:
        parser.error("Require start-date <= end-date <= today (Asia/Seoul)")

    settings = Settings.from_env()
    settings.require_kamis_credentials()
    failures = 0
    total = 0
    summaries = defaultdict(list)
    dashboard_rank_daily = defaultdict(list)
    print(f"[RANGE] {start} ~ {end}; item=257; convert_kg=N", flush=True)
    print("[NOTE] Prices are KRW, not base100. Catalog units are CURRENT units, not historical proof.", flush=True)
    with build_requests_session() as session:
        client = KamisClient(settings, session, app_logger)
        entries = [entry for entry in client.fetch_catalog() if entry.item_code == "257"]
        if not entries:
            print("[ERROR] Melon (257) missing from current KAMIS catalog", flush=True)
            return 1
        for entry in entries:
            print("[CATALOG] " + json.dumps(entry.to_dict(), ensure_ascii=False), flush=True)
            for price_type in (PriceType.RETAIL, PriceType.WHOLESALE):
                if args.price_type not in ("both", price_type.value):
                    continue
                ranks = getattr(entry, f"{price_type.value}_rank_codes")
                for rank in ranks:
                    seen = set()
                    for first, last in date_chunks(start, end):
                        print(f"[QUERY] {first} ~ {last} kind={entry.kind_code} {price_type.value} rank={rank}", flush=True)
                        query = PriceQuery(price_type, first, last, entry, rank, convert_kg=False)
                        try:
                            rows = client.fetch_prices(query)
                        except Exception as error:
                            # Do not print request URLs or credentials from exception messages.
                            failures += 1
                            print(f"[ERROR] Query failed ({type(error).__name__}); this range is incomplete", flush=True)
                            continue
                        count = 0
                        for row in sorted(rows, key=lambda r: (r.observed_date, r.region or "", r.market_name or "")):
                            # Some API responses include rows outside the requested period.
                            if not first <= row.observed_date <= last:
                                continue
                            key = (row.observed_date, row.region, row.market_name, row.price_krw)
                            if key in seen:
                                continue
                            seen.add(key)
                            payload = {
                                "date": row.observed_date.isoformat(),
                                "item": row.item_name, "kind": row.kind_code,
                                "variety": row.variety, "type": price_type.value,
                                "rank": rank, "region": row.region, "market": row.market_name,
                                "price_krw": str(row.price_krw) if row.price_krw is not None else None,
                                "current_catalog_unit": getattr(entry, f"{price_type.value}_unit"),
                                "current_catalog_unit_size": getattr(entry, f"{price_type.value}_unit_size"),
                                "convert_kg": False,
                            }
                            print(json.dumps(payload, ensure_ascii=False), flush=True)
                            count += 1
                            total += 1
                            if row.price_krw is not None:
                                group = (row.observed_date.year, entry.kind_code, price_type.value, rank, row.region, row.market_name)
                                summaries[group].append(row.price_krw)
                                dashboard_rank_daily[
                                    (
                                        row.observed_date,
                                        entry.kind_code,
                                        price_type.value,
                                        rank,
                                    )
                                ].append(row.price_krw)
                        if not count:
                            print("[NO DATA] No observations in this requested range", flush=True)
    print("\n[YEAR SUMMARY] Kept separate by variety/type/rank/region/market; not inflation-adjusted", flush=True)
    for group, values in sorted(summaries.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
        print(json.dumps(dict(zip(("year", "kind", "type", "rank", "region", "market"), group)), ensure_ascii=False)
              + f" count={len(values)} min={min(values)} max={max(values)} mean={sum(values)/len(values):.2f}", flush=True)
    print("\n[DASHBOARD-EQUIVALENT SUMMARY]", flush=True)
    print(
        "[NOTE] Same aggregation rule as ComparisonService: for each date/type, "
        "use one stable rank (04 when available), then average regions/markets per day.",
        flush=True,
    )
    available_ranks = defaultdict(set)
    for observed, kind, price_type, rank in dashboard_rank_daily:
        available_ranks[(kind, price_type)].add(rank)

    selected_rank = {
        key: ("04" if "04" in ranks else sorted(ranks)[0])
        for key, ranks in available_ranks.items()
        if ranks
    }
    by_year_type = defaultdict(list)
    for (observed, kind, price_type, rank), values in sorted(
        dashboard_rank_daily.items()
    ):
        if not values or selected_rank.get((kind, price_type)) != rank:
            continue
        daily_mean = sum(values) / len(values)
        by_year_type[(observed.year, kind, price_type, rank)].append(daily_mean)
    for (year, kind, price_type, rank), values in sorted(by_year_type.items()):
        print(
            f"year={year} kind={kind} type={price_type} rank={rank} "
            f"days={len(values)} mean_of_daily_means={sum(values)/len(values):.2f} "
            f"min_daily={min(values):.2f} max_daily={max(values):.2f}",
            flush=True,
        )

    print(f"[DONE] rows={total}, failed_queries={failures}", flush=True)
    return 1 if failures or not total else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
