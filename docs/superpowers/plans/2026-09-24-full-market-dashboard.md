# Full Market Dashboard Implementation Plan

**Goal:** Extend the verified KAMIS backend into the approved daily comparison product: Naver/Coupang online prices, market series, statistics, analytics, and an interactive FastAPI dashboard.

**Architecture:** Keep source adapters, domain rules, CSV repositories, analytics, orchestration, and HTTP presentation separate. Every source failure is logged and isolated. CSV remains the durable source of truth; browser pages consume JSON APIs.

## Task 1: Online shopping prices

- Add shopping offer/match/summary domain models.
- Implement member-wide discount and shipping-inclusive unit-price normalization.
- Implement repeated 15% low-outlier removal, up-to-five platform mean, and combined mean.
- Add Naver and Coupang public search adapters with injectable HTTP/browser boundaries.
- Persist raw offers, decisions, tracked products, and daily platform summaries to CSV.
- Test parsers, eligibility, fewer-than-five behavior, and exclusion reasons.

## Task 2: Market data

- Add yfinance adapter for KOSPI, KOSDAQ, S&P 500, NASDAQ Composite, Dow Jones, USD/KRW, and configured commodity futures.
- Persist normalized observations with source ticker, date, close, currency, and unit.
- Expose searchable market API and test with an injected downloader.

## Task 3: Analytics

- Create aligned business-date series without forward filling.
- Compute raw/base-100/1-day/7-day views, Pearson, Spearman, p-values, FDR, lag -14..14, rolling 30/90 correlations, spreads, and volatility.
- Persist analysis tables and expose comparison/correlation APIs.
- Test deterministic numeric fixtures and missing-date handling.

## Task 4: Unified daily pipeline

- Orchestrate KAMIS, online sources, market collection, summary, and analytics under one run ID.
- Isolate source failures and record counts/errors in logs and run CSV.
- Update CLI and scheduler to run the unified daily job once per day.

## Task 5: Web dashboard

- Serve a polished responsive HTML/CSS/JavaScript dashboard from FastAPI.
- Provide overview cards, searchable/filterable data table, source status, selectable item/date/mode, a multi-series chart with per-series toggles, and correlation tables/heatmap.
- Keep non-trading/non-observed dates off the X axis by returning only observed aligned dates.

## Task 6: Verification and documentation

- Add end-to-end API/dashboard tests.
- Run pip check, full pytest, Ruff lint and format checks.
- Document source limitations, required optional credentials, commands, CSV schemas, and troubleshooting.
