"""Rank KAMIS varieties by correlation with KOSPI.

Primary research metric:
    KOSPI daily return vs KAMIS daily price return on common observation dates.

The script also reports:
- Spearman correlation of daily returns
- monthly-return Pearson/Spearman correlation
- price-level Pearson correlation (reference only; can be spuriously high)
- p-values and Benjamini-Hochberg FDR for the primary daily Pearson test

Only normalized KAMIS rows used by the dashboard are analyzed:
- requested_convert_kg = false
- region = '평균'
- wholesale / retail analyzed separately
- rank 04 is preferred when available; otherwise the rank with most observations

Run:
    python scripts/analyze_kospi_kamis_correlations.py

Examples:
    python scripts/analyze_kospi_kamis_correlations.py --top 20
    python scripts/analyze_kospi_kamis_correlations.py --price-type wholesale
    python scripts/analyze_kospi_kamis_correlations.py --min-observations 1000
    python scripts/analyze_kospi_kamis_correlations.py --start-date 2010-01-01
"""

from __future__ import annotations

if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

from config.server_config import Settings


@dataclass(frozen=True, slots=True)
class CorrelationResult:
    item_code: str
    item_name: str
    kind_code: str
    variety: str
    price_type: str
    rank_code: str
    first_date: str
    last_date: str
    price_observations: int
    common_level_observations: int
    daily_observations: int
    monthly_observations: int
    level_pearson: float | None
    daily_pearson: float | None
    daily_pearson_p: float | None
    daily_spearman: float | None
    daily_spearman_p: float | None
    monthly_pearson: float | None
    monthly_spearman: float | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KAMIS 품종별 가격과 KOSPI 상관관계를 전수 분석합니다."
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="양/음 상관관계 각각 출력할 개수 (기본 20)",
    )
    parser.add_argument(
        "--min-observations",
        type=int,
        default=500,
        help="일간 수익률 공통 관측 최소 개수 (기본 500)",
    )
    parser.add_argument(
        "--price-type",
        choices=("all", "wholesale", "retail"),
        default="all",
        help="도매/소매 필터 (기본 all)",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help="분석 시작일 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="분석 종료일 YYYY-MM-DD",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="결과 CSV 경로. 기본: data/analysis/kospi_kamis_correlations.csv",
    )
    return parser.parse_args()


def ensure_real_csv(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"파일이 없습니다: {path}")
    if path.stat().st_size == 0:
        raise RuntimeError(f"빈 파일입니다: {path}")
    with path.open("rb") as handle:
        prefix = handle.read(80)
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        raise RuntimeError(
            f"{path} 가 Git LFS 포인터만 내려받아진 상태입니다. "
            "먼저 'git lfs pull'을 실행하세요."
        )


def _safe_corr(
    x: pd.Series,
    y: pd.Series,
    *,
    method: str,
) -> tuple[float | None, float | None, int]:
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    observations = len(pair)
    if observations < 3 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None, None, observations
    if method == "pearson":
        result = pearsonr(pair["x"], pair["y"])
    else:
        result = spearmanr(pair["x"], pair["y"])
    coefficient = float(result.statistic)
    p_value = float(result.pvalue)
    if np.isnan(coefficient):
        return None, None, observations
    return coefficient, p_value, observations


def _fdr_bh(values: list[float | None]) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    valid = [
        (index, float(value))
        for index, value in enumerate(values)
        if value is not None and not np.isnan(value)
    ]
    if not valid:
        return output

    ordered = sorted(valid, key=lambda pair: pair[1])
    total = len(ordered)
    running = 1.0
    for reverse_index in range(total - 1, -1, -1):
        original_index, p_value = ordered[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_value * total / rank)
        output[original_index] = min(running, 1.0)
    return output


def load_kamis_series(
    path: Path,
    *,
    start_date: date | None,
    end_date: date | None,
    price_type: str,
) -> pd.DataFrame:
    conditions = [
        "lower(requested_convert_kg) IN ('false', 'n', '0')",
        "region = '평균'",
        "price_krw IS NOT NULL",
        "price_krw <> ''",
        "observed_date IS NOT NULL",
        "observed_date <> ''",
    ]
    parameters: list[object] = [str(path)]

    if start_date is not None:
        conditions.append("CAST(observed_date AS DATE) >= ?")
        parameters.append(start_date)
    if end_date is not None:
        conditions.append("CAST(observed_date AS DATE) <= ?")
        parameters.append(end_date)
    if price_type != "all":
        conditions.append("price_type = ?")
        parameters.append(price_type)

    where_clause = " AND ".join(conditions)
    query = f"""
        WITH filtered AS (
            SELECT
                item_code,
                item_name,
                kind_code,
                variety,
                price_type,
                rank_code,
                CAST(observed_date AS DATE) AS observed_date,
                TRY_CAST(price_krw AS DOUBLE) AS price_krw,
                collected_at
            FROM read_csv(?, header=true, all_varchar=true)
            WHERE {where_clause}
        ),
        valid AS (
            SELECT *
            FROM filtered
            WHERE price_krw IS NOT NULL
        ),
        rank_stats AS (
            SELECT
                item_code,
                kind_code,
                price_type,
                rank_code,
                count(DISTINCT observed_date) AS observed_days,
                row_number() OVER (
                    PARTITION BY item_code, kind_code, price_type
                    ORDER BY
                        CASE WHEN rank_code='04' THEN 0 ELSE 1 END,
                        count(DISTINCT observed_date) DESC,
                        rank_code ASC
                ) AS rank_order
            FROM valid
            GROUP BY item_code, kind_code, price_type, rank_code
        ),
        selected AS (
            SELECT
                v.*,
                row_number() OVER (
                    PARTITION BY
                        v.item_code,
                        v.kind_code,
                        v.price_type,
                        v.observed_date
                    ORDER BY v.collected_at DESC NULLS LAST
                ) AS date_order
            FROM valid v
            JOIN rank_stats r
              ON v.item_code=r.item_code
             AND v.kind_code=r.kind_code
             AND v.price_type=r.price_type
             AND v.rank_code=r.rank_code
            WHERE r.rank_order=1
        )
        SELECT
            item_code,
            any_value(item_name) AS item_name,
            kind_code,
            any_value(variety) AS variety,
            price_type,
            any_value(rank_code) AS rank_code,
            observed_date,
            any_value(price_krw) AS price_krw
        FROM selected
        WHERE date_order=1
        GROUP BY item_code, kind_code, price_type, observed_date
        ORDER BY item_code, kind_code, price_type, observed_date
    """

    with duckdb.connect(config={"threads": 4}) as connection:
        frame = connection.execute(query, parameters).fetchdf()
    if not frame.empty:
        frame["observed_date"] = pd.to_datetime(frame["observed_date"])
    return frame


def load_kospi(
    path: Path,
    *,
    start_date: date | None,
    end_date: date | None,
) -> pd.DataFrame:
    conditions = [
        "series_id = 'kospi'",
        "observed_date IS NOT NULL",
        "observed_date <> ''",
        "close IS NOT NULL",
        "close <> ''",
    ]
    parameters: list[object] = [str(path)]
    if start_date is not None:
        conditions.append("CAST(observed_date AS DATE) >= ?")
        parameters.append(start_date)
    if end_date is not None:
        conditions.append("CAST(observed_date AS DATE) <= ?")
        parameters.append(end_date)

    query = """
        WITH filtered AS (
            SELECT
                CAST(observed_date AS DATE) AS observed_date,
                TRY_CAST(close AS DOUBLE) AS close,
                collected_at,
                row_number() OVER (
                    PARTITION BY observed_date
                    ORDER BY collected_at DESC NULLS LAST
                ) AS row_order
            FROM read_csv(?, header=true, all_varchar=true)
            WHERE """ + " AND ".join(conditions) + """
        )
        SELECT observed_date, close
        FROM filtered
        WHERE row_order=1 AND close IS NOT NULL
        ORDER BY observed_date
    """
    with duckdb.connect(config={"threads": 4}) as connection:
        frame = connection.execute(query, parameters).fetchdf()
    if not frame.empty:
        frame["observed_date"] = pd.to_datetime(frame["observed_date"])
    return frame


def analyze_group(group: pd.DataFrame, kospi: pd.DataFrame) -> CorrelationResult:
    group = group.sort_values("observed_date").drop_duplicates(
        subset=["observed_date"], keep="last"
    )
    item = group.iloc[0]

    kamis = group.set_index("observed_date")["price_krw"].astype(float)
    kospi_level = kospi.set_index("observed_date")["close"].astype(float)

    level_pair = pd.concat(
        [kamis.rename("kamis"), kospi_level.rename("kospi")], axis=1
    ).dropna()
    level_pearson, _, common_level_observations = _safe_corr(
        level_pair["kamis"],
        level_pair["kospi"],
        method="pearson",
    )

    kamis_return = kamis.pct_change(fill_method=None)
    kospi_return = kospi_level.pct_change(fill_method=None)
    daily_pair = pd.concat(
        [kamis_return.rename("kamis"), kospi_return.rename("kospi")], axis=1
    ).dropna()
    daily_pearson, daily_pearson_p, daily_observations = _safe_corr(
        daily_pair["kamis"],
        daily_pair["kospi"],
        method="pearson",
    )
    daily_spearman, daily_spearman_p, _ = _safe_corr(
        daily_pair["kamis"],
        daily_pair["kospi"],
        method="spearman",
    )

    kamis_month = kamis.resample("ME").last().pct_change(fill_method=None)
    kospi_month = kospi_level.resample("ME").last().pct_change(fill_method=None)
    monthly_pair = pd.concat(
        [kamis_month.rename("kamis"), kospi_month.rename("kospi")], axis=1
    ).dropna()
    monthly_pearson, _, monthly_observations = _safe_corr(
        monthly_pair["kamis"],
        monthly_pair["kospi"],
        method="pearson",
    )
    monthly_spearman, _, _ = _safe_corr(
        monthly_pair["kamis"],
        monthly_pair["kospi"],
        method="spearman",
    )

    return CorrelationResult(
        item_code=str(item["item_code"]),
        item_name=str(item["item_name"]),
        kind_code=str(item["kind_code"]),
        variety=str(item["variety"]),
        price_type=str(item["price_type"]),
        rank_code=str(item["rank_code"]),
        first_date=group["observed_date"].min().isoformat(),
        last_date=group["observed_date"].max().isoformat(),
        price_observations=len(group),
        common_level_observations=common_level_observations,
        daily_observations=daily_observations,
        monthly_observations=monthly_observations,
        level_pearson=level_pearson,
        daily_pearson=daily_pearson,
        daily_pearson_p=daily_pearson_p,
        daily_spearman=daily_spearman,
        daily_spearman_p=daily_spearman_p,
        monthly_pearson=monthly_pearson,
        monthly_spearman=monthly_spearman,
    )


def print_table(title: str, frame: pd.DataFrame, top: int) -> None:
    print()
    print("=" * 110)
    print(title)
    print("=" * 110)
    if frame.empty:
        print("조건을 만족하는 결과가 없습니다.")
        return
    columns = [
        "item_code",
        "item_name",
        "kind_code",
        "variety",
        "price_type",
        "rank_code",
        "daily_pearson",
        "daily_spearman",
        "monthly_pearson",
        "daily_observations",
        "daily_pearson_fdr",
        "first_date",
        "last_date",
    ]
    display = frame.loc[:, columns].head(top).copy()
    for column in (
        "daily_pearson",
        "daily_spearman",
        "monthly_pearson",
        "daily_pearson_fdr",
    ):
        display[column] = display[column].map(
            lambda value: "" if pd.isna(value) else f"{value:.4f}"
        )
    print(display.to_string(index=False))


def main() -> int:
    args = parse_args()
    settings = Settings.from_env()
    kamis_path = settings.data_dir / "normalized" / "kamis_prices.csv"
    market_path = settings.data_dir / "normalized" / "market_observations.csv"
    output_path = (
        args.output
        if args.output is not None
        else settings.data_dir / "analysis" / "kospi_kamis_correlations.csv"
    )

    if args.start_date and args.end_date and args.end_date < args.start_date:
        raise SystemExit("--end-date가 --start-date보다 빠릅니다.")

    ensure_real_csv(kamis_path)
    ensure_real_csv(market_path)

    print("[1/4] KAMIS 공식 평균가격 로딩")
    kamis = load_kamis_series(
        kamis_path,
        start_date=args.start_date,
        end_date=args.end_date,
        price_type=args.price_type,
    )
    print(f"      선택된 품종/가격 행: {len(kamis):,}")

    print("[2/4] KOSPI 로딩")
    kospi = load_kospi(
        market_path,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(f"      KOSPI 관측일: {len(kospi):,}")

    if kamis.empty:
        print("[ERROR] 분석 가능한 KAMIS 평균가격이 없습니다.")
        return 1
    if kospi.empty:
        print("[ERROR] KOSPI 데이터가 없습니다.")
        return 1

    print("[3/4] 품종별 상관관계 계산")
    results: list[CorrelationResult] = []
    group_columns = ["item_code", "kind_code", "price_type"]
    for _, group in kamis.groupby(group_columns, sort=True):
        results.append(analyze_group(group, kospi))

    frame = pd.DataFrame(
        {
            field: [getattr(result, field) for result in results]
            for field in CorrelationResult.__dataclass_fields__
        }
    )
    frame["daily_pearson_fdr"] = _fdr_bh(frame["daily_pearson_p"].tolist())
    frame["daily_spearman_fdr"] = _fdr_bh(frame["daily_spearman_p"].tolist())
    frame["research_eligible"] = (
        frame["daily_observations"].ge(args.min_observations)
        & frame["daily_pearson"].notna()
        & frame["daily_spearman"].notna()
    )

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values(
        ["research_eligible", "daily_pearson", "daily_observations"],
        ascending=[False, False, False],
    ).to_csv(output_path, index=False, encoding="utf-8-sig")

    eligible = frame.loc[frame["research_eligible"]].copy()
    positive = eligible.sort_values(
        ["daily_pearson", "daily_observations"],
        ascending=[False, False],
    )
    negative = eligible.sort_values(
        ["daily_pearson", "daily_observations"],
        ascending=[True, False],
    )
    absolute = eligible.assign(
        abs_daily_pearson=eligible["daily_pearson"].abs()
    ).sort_values(
        ["abs_daily_pearson", "daily_observations"],
        ascending=[False, False],
    )

    print_table(
        f"KOSPI와 가장 비슷하게 움직인 품종 TOP {args.top} "
        f"(일간 수익률 Pearson, n>={args.min_observations})",
        positive,
        args.top,
    )
    print_table(
        f"KOSPI와 반대로 움직인 품종 TOP {args.top} "
        f"(일간 수익률 Pearson, n>={args.min_observations})",
        negative,
        args.top,
    )
    print_table(
        f"|상관계수|가 큰 품종 TOP {args.top} "
        f"(논문 후보 탐색용, n>={args.min_observations})",
        absolute,
        args.top,
    )

    print()
    print("[4/4] 완료")
    print(f"전체 품종/가격구분: {len(frame):,}")
    print(f"연구 최소관측 조건 통과: {len(eligible):,}")
    print(f"결과 CSV: {output_path}")
    print()
    print(
        "[주의] level_pearson은 가격 수준의 장기 추세 때문에 허위상관이 "
        "커질 수 있으므로 참고값입니다. 논문 주 결과는 daily_pearson/"
        "daily_spearman과 FDR, 관측치 수를 함께 보세요."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
