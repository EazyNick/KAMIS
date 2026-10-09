"""Inspect the local KAMIS CSV exactly as the dashboard reads melon prices.

This script performs no network requests and does not modify data.

Run:
    python scripts/inspect_local_melon_csv.py
    python scripts/inspect_local_melon_csv.py --year 2026
    python scripts/inspect_local_melon_csv.py --date 2026-10-08

It separates legacy kg-converted rows (requested_convert_kg=True) from the
original KAMIS survey-unit rows (requested_convert_kg=False), then prints the
same daily wholesale/retail mean used by ComparisonService.
"""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import csv
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from config.server_config import Settings


def _as_bool(value: str) -> bool | None:
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "y", "1"}:
        return True
    if normalized in {"false", "n", "0"}:
        return False
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    path = settings.data_dir / "normalized" / "kamis_prices.csv"
    print(f"[CSV] {path.resolve()}")
    if not path.exists():
        print("[ERROR] kamis_prices.csv does not exist")
        return 1

    flags: Counter[bool | None] = Counter()
    raw_rows: list[dict[str, str]] = []
    converted_rows: list[dict[str, str]] = []

    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("item_code", "")) != "257":
                continue
            observed_text = str(row.get("observed_date", ""))
            try:
                observed = date.fromisoformat(observed_text)
            except ValueError:
                continue
            if args.date is not None and observed != args.date:
                continue
            if args.date is None and observed.year != args.year:
                continue

            flag = _as_bool(row.get("requested_convert_kg", ""))
            flags[flag] += 1
            if flag is False:
                raw_rows.append(row)
            elif flag is True:
                converted_rows.append(row)

    print(
        "[ROWS] "
        f"raw_N={len(raw_rows):,} legacy_Y={len(converted_rows):,} "
        f"unknown_flag={flags[None]:,}"
    )

    def summarize(label: str, rows: list[dict[str, str]]) -> None:
        groups: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
        by_date: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
        for row in rows:
            try:
                price = Decimal(str(row.get("price_krw", "")).replace(",", ""))
            except InvalidOperation:
                continue
            price_type = str(row.get("price_type", ""))
            rank = str(row.get("rank_code", ""))
            observed = str(row.get("observed_date", ""))
            groups[(price_type, rank)].append(price)
            by_date[(observed, price_type)].append(price)

        print(f"\n[{label}]")
        if not rows:
            print("  no rows")
            return
        for (price_type, rank), values in sorted(groups.items()):
            mean = sum(values) / len(values)
            print(
                f"  {price_type:9s} rank={rank or '-'} "
                f"n={len(values):,} mean={mean:.2f} "
                f"min={min(values):.2f} max={max(values):.2f}"
            )

        print("  [DASHBOARD EQUIVALENT: daily mean]")
        daily_means: dict[str, list[Decimal]] = defaultdict(list)
        for (observed, price_type), values in sorted(by_date.items()):
            daily_mean = sum(values) / len(values)
            daily_means[price_type].append(daily_mean)
            if args.date is not None:
                print(
                    f"    {observed} {price_type:9s} "
                    f"mean={daily_mean:.2f} rows={len(values)}"
                )
        for price_type, values in sorted(daily_means.items()):
            overall_daily_mean = sum(values) / len(values)
            print(
                f"    {price_type:9s} "
                f"mean_of_daily_means={overall_daily_mean:.2f} "
                f"days={len(values):,}"
            )

    summarize("RAW p_convert_kg_yn=N", raw_rows)
    summarize("LEGACY p_convert_kg_yn=Y", converted_rows)

    print(
        "\n[CATALOG NOTE] melon(257:00): wholesale current unit=8kg, "
        "retail current unit=1개. Do not compare a wholesale mean directly "
        "with the retail dashboard series."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
