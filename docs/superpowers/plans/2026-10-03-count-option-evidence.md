# Count option evidence implementation plan

**Goal:** Verify the total pieces/fish belonging to the selected sale option, retain its price and URL, and exclude uncertain counts.
**Spec:** User-approved design in this conversation: 10과 → 10개; 3미 → 3마리; explicit 2마리 × 3팩 → 6마리; no box-as-fruit or range estimates.
**Architecture:** Shared strict count parsing and ingestion validation, plus a bounded Windows accessibility detail reader used by both collectors. Evidence travels with raw and normalized offers.
**Tech stack:** Python, pytest, PowerShell, Windows UI Automation.

## Constraints and rulings
- Approval to implement has already been given; execute in this workspace without another approval cycle. Preserve existing data changes; do not commit or collect live prices as part of automated tests.
- Count-based offers require detail evidence. Existing weight/head paths stay compatible.
- Do not select/purchase options or bypass access blocks. Read the currently selected option only; unknown/unsupported detail layouts fail closed.
- Keep price evidence scoped to the selected product, not recommendations or search-card prices.

## Tasks
- [x] Add failing tests for aliases, explicit multipacks, ranges, boxes, conflicting options/prices, and missing evidence.
- [x] Implement strict count evidence validation and retain evidence on ShoppingOffer/CSV persistence.
- [x] Add a bounded shared detail reader, integrate both UI collectors, and test its evidence extraction without a live browser.
- [x] Update collector schema/documentation, run the full suite and review the diff.

## Review focus
Wrong price/option pairing; stale search elements after navigation; inaccessible details; extra pack multipliers; old CSV compatibility.

## Progress
Initial inspection: collectors read search cards only; ingestion trusts quantity and loses selected-option evidence.

Implementation: `app/domain/count_evidence.py` validates the selected sale; `app/infrastructure/shopping_count_detail.py` validates scoped UI snapshots; `scripts/collectors/shopping_count_detail.ps1` reads supported selected controls and closes only the new detail tab. Both platform collectors use the reader. Raw and normalized offers retain option, pre-scaling count/unit, price evidence, product title, detail text, and URL.

Review fixes: surcharge evidence in both option and purchase text; exclusive bounds and em-dash ranges; conditional shipping; preexisting tab identity; search-card snapshots before navigation; detail product identity; ambiguous 1개 weighted boxes. Each defect was reproduced in failing tests before its fix.

Verification: final `.venv/Scripts/python.exe -m pytest -q --tb=short` completed with **306 passed, 9 failed**, including all 60 new focused cases. Baseline before implementation: 245 passed, 9 failed; the final failures are exactly the same tests. One existing Starlette/httpx deprecation warning remains. `git diff --check` passed for changed code/docs. No live shopping collection was performed, and no collected-data files were intentionally changed. Supported UI layouts must expose a selected option, a labeled price and an explicit order quantity of 1; unsupported layouts are excluded rather than guessed. Detail-tab cleanup exceptions abort collection rather than allowing a success report.

Existing full-suite failures (also present before these changes):
- `tests/api/test_routes.py::test_dashboard_bootstrap_does_not_use_unverified_variety_cache`
- `tests/integration/test_coupang_agent_pipeline.py::test_pipeline_collects_only_missing_coupang_rows_and_persists_csv`
- `tests/integration/test_naver_agent_pipeline.py::test_pipeline_collects_only_missing_naver_rows_and_persists_csv`
- `tests/services/test_comparison_service.py::test_comparison_keeps_configured_rice_weight_separate`
- `tests/services/test_daily_pipeline.py::test_daily_pipeline_isolates_source_partial_failure`
- `tests/services/test_daily_pipeline.py::test_daily_pipeline_uses_rank_level_kamis_coverage`
- `tests/services/test_daily_pipeline.py::test_daily_pipeline_logs_each_source_before_collection`
- `tests/services/test_melon_dashboard_estimates.py::test_melon_seed_estimates_cover_every_day_from_sep_23_to_sep_30`
- `tests/web/test_dashboard.py::test_dashboard_refreshes_chart_after_startup_collection_finishes`
