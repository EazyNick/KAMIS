from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    project_root = str(Path(__file__).resolve().parents[2])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

"""Backfill about 20 years of original-unit KAMIS wholesale/retail prices.

Prices are requested with p_convert_kg_yn=N and stored without kg/count/package
conversion. Only KAMIS' official region='평균' rows are kept in the normalized
research CSV because the dashboard no longer recomputes regional averages.

The same checkpoint is used by this CLI and main.py startup. Completed
item/kind/type/rank/year queries are skipped on later runs, so startup requests
only history that has not yet been verified in raw-price mode.

Run from the repository root:
    python scripts/backfill/backfill_kamis_20y.py
"""

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.domain.models import PriceQuery, PriceType
from app.infrastructure.csv_repository import CatalogRepository, PriceRepository
from app.infrastructure.kamis_client import KamisClient, build_requests_session
from config.server_config import Settings
from log import app_logger


@dataclass(frozen=True, slots=True)
class BackfillResult:
    fetched_rows: int
    completed_queries: int
    failed_queries: tuple[str, ...]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill KAMIS wholesale/retail original-unit prices."
    )
    parser.add_argument(
        "--all-catalog",
        action="store_true",
        help="Compatibility flag; the complete KAMIS catalog is now the default.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore the raw-price checkpoint and query the full period again.",
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


CHECKPOINT_STORAGE_SCOPE = "official_average_raw_v3_nonempty"


def load_checkpoint(path: Path) -> tuple[set[str], dict[str, int], str | None]:
    if not path.exists():
        return set(), {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), {}, None
    completed = {str(value) for value in payload.get("completed_queries", [])}
    counts = {
        str(key): int(value)
        for key, value in dict(payload.get("record_counts", {})).items()
        if str(value).isdigit()
    }
    return completed, counts, (
        str(payload.get("storage_scope"))
        if payload.get("storage_scope")
        else None
    )


def save_checkpoint(
    path: Path,
    completed: set[str],
    record_counts: dict[str, int],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(
            {
                "version": 3,
                "storage_scope": CHECKPOINT_STORAGE_SCOPE,
                "completed_queries": sorted(completed),
                "record_counts": {
                    key: record_counts[key]
                    for key in sorted(completed)
                    if key in record_counts
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temp, path)


def should_skip_query(
    *,
    force: bool,
    item_missing_from_dashboard: bool,
    key_completed: bool,
    expected_count: int | None,
    stored_count: int,
) -> bool:
    """Skip only when persisted dashboard data proves the query is covered."""
    return (
        not force
        and not item_missing_from_dashboard
        and key_completed
        and expected_count is not None
        and stored_count >= expected_count
    )


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


def run_backfill(
    settings: Settings,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    category_code: str | None = None,
    force: bool = False,
    workers: int = 4,
    chunk_days: int = 31,
) -> BackfillResult:
    """Fill unverified raw KAMIS history and persist progress after each year."""
    settings.require_kamis_credentials()
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    if not 1 <= chunk_days <= 366:
        raise ValueError("chunk_days must be between 1 and 366")

    prices = PriceRepository(settings.data_dir, app_logger)
    catalog_repository = CatalogRepository(settings.data_dir, app_logger)
    client = KamisClient(settings, build_requests_session(), app_logger)

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    first_year = start_year or (today.year - 20)
    last_year = min(end_year or today.year, today.year)
    checkpoint_name = (
        f"kamis_20y_raw_category_{category_code}.json"
        if category_code
        else "kamis_20y_raw_checkpoint.json"
    )
    checkpoint_path = settings.data_dir / "backfill" / checkpoint_name
    if force:
        completed_queries, checkpoint_counts, checkpoint_scope = set(), {}, None
    else:
        completed_queries, checkpoint_counts, checkpoint_scope = load_checkpoint(
            checkpoint_path
        )

    # The research dataset now uses only KAMIS' official nationwide average
    # (region='평균') in original survey units. Compact old regional/market and
    # kg-converted rows before reconciliation so subsequent reads/writes remain small.
    prices.compact_to_official_average_raw(
        f"kamis-average-compact-{uuid4().hex}"
    )

    stored_scope_year_counts = prices.scope_year_counts(
        first_year,
        last_year,
        requested_convert_kg=False,
    )
    stored_scope_month_counts = prices.scope_month_counts(
        today.year,
        requested_convert_kg=False,
    )
    existing_item_codes = set(
        prices.item_date_stats(
            requested_convert_kg=False,
            region="평균",
        )
    )

    if (
        not force
        and completed_queries
        and checkpoint_scope != CHECKPOINT_STORAGE_SCOPE
    ):
        migrated_counts: dict[str, int] = {}
        verified_completed: set[str] = set()
        recheck_count = 0
        for key in completed_queries:
            parts = key.split(":")
            if len(parts) != 6:
                recheck_count += 1
                continue
            item_code, kind_code, price_type, rank_code, start_text, end_text = parts
            try:
                query_start = date.fromisoformat(start_text)
                query_end = date.fromisoformat(end_text)
            except ValueError:
                recheck_count += 1
                continue
            if (
                query_start.year == today.year
                and query_end.year == today.year
                and query_start.month == query_end.month
            ):
                count = stored_scope_month_counts.get(
                    (
                        item_code,
                        kind_code,
                        price_type,
                        rank_code,
                        query_start.month,
                    ),
                    0,
                )
            else:
                count = stored_scope_year_counts.get(
                    (
                        item_code,
                        kind_code,
                        price_type,
                        rank_code,
                        query_start.year,
                    ),
                    0,
                )

            # Old checkpoints were produced before normalized storage was limited
            # to KAMIS' official region='평균' rows. A migrated count of zero
            # cannot prove that this query truly has no official-average data;
            # re-query it once under the v2 storage scope instead of accepting
            # the old completion marker as sufficient evidence.
            if count <= 0:
                recheck_count += 1
                continue

            verified_completed.add(key)
            migrated_counts[key] = count

        completed_queries = verified_completed
        checkpoint_counts = migrated_counts
        save_checkpoint(checkpoint_path, completed_queries, checkpoint_counts)
        checkpoint_scope = CHECKPOINT_STORAGE_SCOPE
        app_logger.info(
            "kamis.long_history.checkpoint.migrated",
            "Existing KAMIS checkpoint migrated to verified official-average coverage",
            migrated_query_count=len(migrated_counts),
            recheck_query_count=recheck_count,
        )

    app_logger.info(
        "kamis.long_history.started",
        "[확인 시작] KAMIS 20년 데이터 누락 여부 점검",
        start_year=first_year,
        end_year=last_year,
        checkpoint=checkpoint_path,
        completed_query_count=len(completed_queries),
    )

    catalog = client.fetch_catalog()
    if not catalog:
        raise RuntimeError("KAMIS catalog is empty")
    catalog_repository.save_snapshot(
        catalog,
        today,
        f"kamis-20y-catalog-{uuid4().hex}",
    )
    targets = (
        [entry for entry in catalog if entry.category_code == category_code]
        if category_code
        else catalog
    )
    missing_item_codes = {
        entry.item_code
        for entry in targets
        if entry.item_code not in existing_item_codes
        and (entry.wholesale_rank_codes or entry.retail_rank_codes)
    }
    targets = sorted(
        targets,
        key=lambda entry: (
            entry.item_code not in missing_item_codes,
            entry.item_code,
            entry.kind_code,
        ),
    )
    if missing_item_codes:
        app_logger.warning(
            "kamis.long_history.items.missing",
            "[우선 복구] 대시보드 가격이 0건인 KAMIS 품목을 먼저 다시 수집합니다.",
            missing_item_count=len(missing_item_codes),
            missing_item_codes=",".join(sorted(missing_item_codes)),
        )

    total_rows = 0
    failed_queries: list[str] = []

    for year in range(last_year, first_year - 1, -1):
        if year == today.year:
            segments: list[tuple[date, date]] = []
            for month in range(1, today.month + 1):
                month_start = date(year, month, 1)
                if month == 12:
                    next_month = date(year + 1, 1, 1)
                else:
                    next_month = date(year, month + 1, 1)
                month_end = min(next_month - timedelta(days=1), today)
                segments.append((month_start, month_end))
        else:
            segments = [(date(year, 1, 1), date(year, 12, 31))]

        year_rows = []
        successful_keys: list[str] = []
        successful_counts: dict[str, int] = {}
        pending: list[tuple[str, PriceQuery]] = []
        candidate_count = 0
        skipped_count = 0

        for entry in targets:
            for price_type, rank_codes in (
                (PriceType.WHOLESALE, entry.wholesale_rank_codes),
                (PriceType.RETAIL, entry.retail_rank_codes),
            ):
                for rank_code in rank_codes:
                    for period_start, period_end in segments:
                        candidate_count += 1
                        key = query_key(
                            entry.item_code,
                            entry.kind_code,
                            price_type,
                            rank_code,
                            period_start,
                            period_end,
                        )
                        if year == today.year:
                            stored_count = stored_scope_month_counts.get(
                                (
                                    entry.item_code,
                                    entry.kind_code,
                                    price_type.value,
                                    rank_code,
                                    period_start.month,
                                ),
                                0,
                            )
                        else:
                            stored_count = stored_scope_year_counts.get(
                                (
                                    entry.item_code,
                                    entry.kind_code,
                                    price_type.value,
                                    rank_code,
                                    year,
                                ),
                                0,
                            )
                        expected_count = checkpoint_counts.get(key)
                        if should_skip_query(
                            force=force,
                            item_missing_from_dashboard=(
                                entry.item_code in missing_item_codes
                            ),
                            key_completed=key in completed_queries,
                            expected_count=expected_count,
                            stored_count=stored_count,
                        ):
                            skipped_count += 1
                            continue
                        pending.append(
                            (
                                key,
                                PriceQuery(
                                    price_type=price_type,
                                    start_date=period_start,
                                    end_date=period_end,
                                    catalog_entry=entry,
                                    rank_code=rank_code,
                                    country_code=None,
                                    convert_kg=False,
                                ),
                            )
                        )

        if not pending:
            app_logger.info(
                "kamis.long_history.year.checked",
                f"[확인] {year}년 KAMIS 데이터 이미 저장됨 - API 수집 없음",
                year=year,
                total_query_count=candidate_count,
                skipped_query_count=skipped_count,
                pending_query_count=0,
            )
            continue

        app_logger.info(
            "kamis.long_history.year.started",
            f"[수집 필요] {year}년 KAMIS 누락 {len(pending)}구간 발견 - "
            "실제 API 수집 시작",
            year=year,
            segment_granularity="month" if year == today.year else "year",
            total_query_count=candidate_count,
            skipped_query_count=skipped_count,
            pending_query_count=len(pending),
        )

        def fetch_one(job: tuple[str, PriceQuery]):
            key, query = job
            try:
                with build_requests_session() as session:
                    rows = fetch_in_chunks(
                        KamisClient(settings, session, app_logger),
                        query,
                        chunk_days,
                    )
                raw_count = len(rows)
                rows = [
                    row
                    for row in rows
                    if query.start_date <= row.observed_date <= query.end_date
                    and row.region == "평균"
                ]
                unique = {}
                for row in rows:
                    row_key = (
                        row.price_type.value,
                        row.observed_date,
                        row.category_code,
                        row.item_code,
                        row.kind_code,
                        row.rank_code,
                        row.region,
                        row.market_name,
                        row.requested_convert_kg,
                    )
                    unique[row_key] = row
                return key, list(unique.values()), raw_count, None
            except Exception as fetch_error:  # noqa: BLE001
                return key, [], 0, fetch_error

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for key, rows, raw_count, error in executor.map(fetch_one, pending):
                if error is not None:
                    failed_queries.append(key)
                    app_logger.exception(
                        "kamis.long_history.query.failed",
                        "Raw KAMIS history query failed and will be retried next startup",
                        error,
                        query_key=key,
                    )
                    continue
                item_code = key.split(":", 1)[0]
                if not rows and raw_count > 0:
                    failed_queries.append(key)
                    app_logger.warning(
                        "kamis.long_history.average.missing",
                        "[미완료] KAMIS API 응답은 있지만 공식 평균값이 없어 checkpoint에 등록하지 않습니다.",
                        query_key=key,
                        api_record_count=raw_count,
                        official_average_record_count=0,
                    )
                    continue
                if (
                    not rows
                    and raw_count == 0
                    and item_code in missing_item_codes
                ):
                    app_logger.warning(
                        "kamis.long_history.item.no_data",
                        "[확인 필요] 저장 데이터가 없는 품목인데 KAMIS API도 0건을 반환했습니다.",
                        query_key=key,
                        api_record_count=0,
                    )
                    continue
                year_rows.extend(rows)
                successful_keys.append(key)
                successful_counts[key] = len(rows)

        # Mark queries complete only after their returned rows are safely persisted.
        if year_rows:
            prices.upsert(year_rows, f"kamis-20y-raw-{year}-{uuid4().hex}")
            total_rows += len(year_rows)

        completed_queries.update(successful_keys)
        checkpoint_counts.update(successful_counts)
        save_checkpoint(checkpoint_path, completed_queries, checkpoint_counts)
        app_logger.info(
            "kamis.long_history.year.completed",
            f"[저장 완료] {year}년 KAMIS 평균가격 보정 완료",
            year=year,
            fetched_rows=len(year_rows),
            completed_query_count=len(successful_keys),
            failed_query_count=len(pending) - len(successful_keys),
        )

    final_item_stats = prices.item_date_stats(
        requested_convert_kg=False,
        region="평균",
    )
    unresolved_items = sorted(
        {
            entry.item_code
            for entry in targets
            if (entry.wholesale_rank_codes or entry.retail_rank_codes)
            and entry.item_code not in final_item_stats
        }
    )
    if unresolved_items:
        app_logger.warning(
            "kamis.long_history.items.unresolved",
            "[누락 경고] 수집 종료 후에도 대시보드 가격이 0건인 품목이 있습니다.",
            missing_item_count=len(unresolved_items),
            missing_item_codes=",".join(unresolved_items),
        )

    result = BackfillResult(
        fetched_rows=total_rows,
        completed_queries=len(completed_queries),
        failed_queries=tuple(failed_queries),
    )
    app_logger.info(
        "kamis.long_history.completed",
        "[전체 완료] KAMIS 20년 데이터 확인/수집 종료",
        fetched_rows=result.fetched_rows,
        completed_query_count=result.completed_queries,
        failed_query_count=len(result.failed_queries),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings.from_env()
    result = run_backfill(
        settings,
        start_year=args.start_year,
        end_year=args.end_year,
        category_code=args.category_code,
        force=args.force,
        workers=args.workers,
        chunk_days=args.chunk_days,
    )
    return 1 if result.failed_queries else 0


if __name__ == "__main__":
    raise SystemExit(main())
