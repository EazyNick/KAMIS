from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

"""Backfill about 20 years of KAMIS wholesale/retail daily prices.

Run from the repository root:
    python scripts/backfill/backfill_kamis_20y.py

Optional:
    python scripts/backfill/backfill_kamis_20y.py --all-catalog
    python scripts/backfill/backfill_kamis_20y.py --force
    python scripts/backfill/backfill_kamis_20y.py --start-year 2006

Required .env:
    KAMIS_CERT_KEY=...
    KAMIS_CERT_ID=...

Output:
    data/normalized/kamis_prices.csv
    data/backfill/kamis_20y_checkpoint.json
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.models import PriceQuery, PriceType
from app.infrastructure.csv_repository import CatalogRepository, PriceRepository
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from config.server_config import DEFAULT_ONLINE_TARGET_KEYS, Settings
from log import app_logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill KAMIS wholesale/retail prices for about 20 years."
    )
    parser.add_argument(
        "--all-catalog",
        action="store_true",
        help="Collect the complete KAMIS catalog instead of the project's 11 targets.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the checkpoint and query the full period again.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="First year to collect. Default: current year - 20.",
    )
    parser.add_argument(
        "--category-code", help="Limit backfill to one KAMIS category (100: grains)."
    )
    parser.add_argument("--end-year", type=int, help="Last year to collect, inclusive.")
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, 5),
        default=1,
        help="Concurrent read requests (1 to 4); writes remain sequential.",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=31,
        help="Maximum days per API request; avoids annual response timeouts.",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.chunk_days <= 366:
        parser.error("chunk-days must be between 1 and 366")
    if args.start_year and args.end_year and args.start_year > args.end_year:
        parser.error("start-year must not exceed end-year")
    return args


def fetch_in_chunks(client, query, chunk_days: int):
    rows = []
    start = query.start_date
    while start <= query.end_date:
        end = min(start + timedelta(days=chunk_days - 1), query.end_date)
        rows.extend(client.fetch_prices(replace(query, start_date=start, end_date=end)))
        start = end + timedelta(days=1)
    return rows


def load_checkpoint(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {str(value) for value in payload.get("completed_queries", [])}


def save_checkpoint(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            {"version": 1, "completed_queries": sorted(completed)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temp, path)


def query_key(
    item_code: str,
    kind_code: str,
    price_type: PriceType,
    rank_code: str,
    start_date: date,
    end_date: date,
) -> str:
    return (
        f"{item_code}:{kind_code}:{price_type.value}:{rank_code}:"
        f"{start_date.isoformat()}:{end_date.isoformat()}"
    )


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    settings.require_kamis_credentials()

    prices = PriceRepository(settings.data_dir, app_logger)
    catalog_repository = CatalogRepository(settings.data_dir, app_logger)
    client = KamisClient(settings, build_requests_session(), app_logger)

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    start_year = args.start_year or (today.year - 20)
    end_year = min(args.end_year or today.year, today.year)
    checkpoint_name = (
        f"kamis_20y_category_{args.category_code}.json"
        if args.category_code
        else "kamis_20y_checkpoint.json"
    )
    checkpoint_path = settings.data_dir / "backfill" / checkpoint_name
    completed_queries = set() if args.force else load_checkpoint(checkpoint_path)

    print("[CATALOG] fetching KAMIS productInfo")
    catalog = client.fetch_catalog()
    if not catalog:
        print("[FAILED] KAMIS catalog is empty")
        return 1

    catalog_repository.save_snapshot(
        catalog,
        today,
        f"kamis-20y-catalog-{uuid4().hex}",
    )

    if args.category_code:
        targets = [
            entry for entry in catalog if entry.category_code == args.category_code
        ]
    elif args.all_catalog:
        targets = catalog
    else:
        target_keys = set(DEFAULT_ONLINE_TARGET_KEYS)
        targets = [
            entry
            for entry in catalog
            if (entry.item_code, entry.kind_code) in target_keys
        ]
        found = {(entry.item_code, entry.kind_code) for entry in targets}
        missing = sorted(target_keys - found)
        if missing:
            print(
                "[WARN] targets missing from current catalog: "
                + ", ".join(f"{item}:{kind}" for item, kind in missing)
            )

    print(
        f"[START] KAMIS: {start_year}-01-01 ~ {today}, "
        f"targets={len(targets):,}, all_catalog={args.all_catalog}"
    )
    print(f"[OUTPUT] {prices.path}")
    print(f"[CHECKPOINT] {checkpoint_path}")

    total_rows = 0
    failed_queries: list[str] = []

    for year in range(start_year, end_year + 1):
        period_start = date(year, 1, 1)
        period_end = min(date(year, 12, 31), today)
        year_rows = []
        successful_keys: list[str] = []
        attempted = 0
        skipped = 0
        pending = []

        print("\n" + "=" * 72)
        print(f"[YEAR] {period_start} ~ {period_end}")

        for entry in targets:
            price_types = (
                (PriceType.WHOLESALE, entry.wholesale_rank_codes),
                (PriceType.RETAIL, entry.retail_rank_codes),
            )
            for price_type, rank_codes in price_types:
                for rank_code in rank_codes:
                    key = query_key(
                        entry.item_code,
                        entry.kind_code,
                        price_type,
                        rank_code,
                        period_start,
                        period_end,
                    )

                    if not args.force and key in completed_queries:
                        skipped += 1
                        continue

                    attempted += 1
                    query = PriceQuery(
                        price_type=price_type,
                        start_date=period_start,
                        end_date=period_end,
                        catalog_entry=entry,
                        rank_code=rank_code,
                        country_code=None,
                        convert_kg=True,
                    )

                    print(
                        f"[FETCH] {year} {entry.item_code}:{entry.kind_code} "
                        f"{entry.item_name}/{entry.variety} "
                        f"{price_type.value} rank={rank_code}"
                    )
                    pending.append((key, query))

        def fetch_one(job):
            key, query = job
            try:
                # Each worker owns its HTTP session. Repository writes stay on this thread.
                with build_requests_session() as session:
                    rows = fetch_in_chunks(
                        KamisClient(settings, session, app_logger),
                        query,
                        args.chunk_days,
                    )
                return key, rows, None
            except Exception as fetch_error:  # noqa: BLE001
                return key, [], type(fetch_error).__name__

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for key, rows, error in executor.map(fetch_one, pending):
                if error:
                    failed_queries.append(key)
                    print(f"[FAILED] {key}: {error}")
                else:
                    year_rows.extend(rows)
                    successful_keys.append(key)
                    print(f"[FETCHED] {key}: {len(rows):,} rows")

        if year_rows:
            result = prices.upsert(
                year_rows,
                f"kamis-20y-{year}-{uuid4().hex}",
            )
            total_rows += len(year_rows)
            print(
                f"[UPSERT] year={year}: fetched={len(year_rows):,}, "
                f"inserted={result.inserted:,}, updated={result.updated:,}"
            )
        else:
            print(
                f"[UPSERT] year={year}: no new rows "
                f"(attempted={attempted}, skipped={skipped})"
            )

        completed_queries.update(successful_keys)
        save_checkpoint(checkpoint_path, completed_queries)
        print(
            f"[YEAR DONE] {year}: attempted={attempted:,}, "
            f"checkpoint-skipped={skipped:,}, "
            f"successful={len(successful_keys):,}"
        )

    print("\n" + "=" * 72)
    print(f"[DONE] fetched rows this run: {total_rows:,}")
    print(f"[CHECKPOINT COUNT] {len(completed_queries):,}")
    print(f"[FAILED QUERY COUNT] {len(failed_queries):,}")
    if failed_queries:
        print(
            "[INFO] Failed queries are not checkpointed. "
            "Run the same command again to retry them."
        )

    return 1 if failed_queries else 0


if __name__ == "__main__":
    raise SystemExit(main())
