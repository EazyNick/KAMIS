"""Inspect KAMIS rows that are actually eligible for dashboard charts.

Shows, per item, the selected kind based on stored official-average raw coverage,
plus wholesale/retail rank-04 observation counts and date ranges.

Run:
    python scripts/inspect_dashboard_kamis_coverage.py
"""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from config.server_config import Settings


def main() -> int:
    settings = Settings.from_env()
    path = settings.data_dir / "normalized" / "kamis_prices.csv"
    if not path.exists():
        print(f"[ERROR] missing: {path}")
        return 1

    sql = """
    WITH filtered AS (
        SELECT *
        FROM read_csv(?, header=true, all_varchar=true)
        WHERE lower(requested_convert_kg) IN ('false','n','0')
          AND region = '평균'
          AND observed_date IS NOT NULL
          AND observed_date <> ''
    ),
    kind_stats AS (
        SELECT
            item_code,
            any_value(item_name) AS item_name,
            kind_code,
            count(DISTINCT CASE WHEN price_type='wholesale' THEN observed_date END)
                AS wholesale_days,
            count(DISTINCT CASE WHEN price_type='retail' THEN observed_date END)
                AS retail_days,
            count(DISTINCT CASE
                WHEN price_type='wholesale' AND rank_code='04'
                THEN observed_date END) AS wholesale_rank04_days,
            count(DISTINCT CASE
                WHEN price_type='retail' AND rank_code='04'
                THEN observed_date END) AS retail_rank04_days,
            min(observed_date) AS first_date,
            max(observed_date) AS last_date,
            count(*) AS observations
        FROM filtered
        GROUP BY item_code, kind_code
    ),
    ranked AS (
        SELECT *,
            row_number() OVER (
                PARTITION BY item_code
                ORDER BY
                    least(wholesale_days, retail_days) DESC,
                    wholesale_days + retail_days DESC,
                    observations DESC,
                    kind_code ASC
            ) AS rn
        FROM kind_stats
    )
    SELECT
        item_code,
        item_name,
        kind_code,
        wholesale_rank04_days,
        retail_rank04_days,
        wholesale_days,
        retail_days,
        first_date,
        last_date,
        observations
    FROM ranked
    WHERE rn=1
    ORDER BY item_code
    """

    with duckdb.connect(config={"threads": 4}) as connection:
        rows = connection.execute(sql, [str(path)]).fetchall()

    print(f"[CSV] {path.resolve()}")
    print(f"[ITEMS] {len(rows)}")
    missing = 0
    for (
        item_code,
        item_name,
        kind_code,
        wholesale_rank04_days,
        retail_rank04_days,
        wholesale_days,
        retail_days,
        first_date,
        last_date,
        observations,
    ) in rows:
        status = "OK"
        if wholesale_days == 0 and retail_days == 0:
            status = "MISSING"
            missing += 1
        elif wholesale_days == 0 or retail_days == 0:
            status = "PARTIAL"
        print(
            f"{status:7s} item={item_code} name={item_name} kind={kind_code} "
            f"W04={wholesale_rank04_days} R04={retail_rank04_days} "
            f"W={wholesale_days} R={retail_days} "
            f"range={first_date}~{last_date} rows={observations}"
        )

    print(f"[DONE] items={len(rows)} missing={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
