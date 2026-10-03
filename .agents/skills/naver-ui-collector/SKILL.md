---
name: naver-ui-collector
description: Collect a bounded Naver Shopping product-price manifest through the user's ordinary Chrome session with Windows UI Automation and write raw accessibility results to CSV. Use only when explicitly invoked for this repository's Naver collection run.
---

# Naver UI Collector

Run only the deterministic repository script. Do not browse independently, edit application
code, infer missing products, or report a blocked/CAPTCHA result as successful.

## Required input

Receive one absolute JSON manifest through `-ManifestPath`. It contains `run_id`,
`observed_date`, `run_dir`, `output_csv`, and at most 10 `targets`. Each target provides
`item_code`, `kind_code`, `item_name`, `variety`, `comparison_unit`, and `query`.

## Execution

From the repository root, run exactly:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .agents\skills\naver-ui-collector\scripts\collect_naver_ui.ps1 -ManifestPath <manifest-path>
```

The script must enter `https://shopping.naver.com/` first when there is no usable Naver
Shopping Chrome document. It finds and submits the accessible search input; never navigate
directly to a search-result URL. Never evade an access block, CAPTCHA, login requirement, or
other access control.

## Browser cleanup

Browser cleanup is mandatory after the collection attempt finishes, including success,
partial success, script failure, parsing failure, timeout, or any other exception.

- Close the Naver Shopping tab or browser window used for this collection run before returning
  the final JSON status.
- Close only the tab/window used by this run. Do not close unrelated user tabs or unrelated
  Chrome windows.
- Do not leave a collection tab, popup, or browser window open after the run completes.
- Cleanup must still be attempted when collection fails. A cleanup failure must not be
  reported as successful collection; preserve the underlying collection result honestly.
- Return the final JSON only after the cleanup attempt has completed.

## Product exclusions

Exclude product cards marked `광고`, `AD`, or `sponsored`, including labels in
their accessibility text. Exclude unrelated items and processed products: rice
noodles/snacks/storage bins are not rice; cabbage kimchi/green cabbage are not
fresh napa cabbage. A substring match alone does not establish product identity.
Use the shared rules in `app/domain/shopping_filter_rules.json` through the
deterministic script and CSV validator. Apply exclusions before the result limit;
excluded cards must not consume the target's offer quota. Do not count a target
with only excluded cards as completed. Never invent replacements for excluded rows.

## Price and quantity evidence

Use only an unambiguous package quantity attached to the displayed sale price.
The script supports explicit `과` → `개` and `미` → `마리` counts. A `1개` kg box
does not mean one fruit. A per-unit quote such as `100g당` is not the package size.
Do not convert kg to pieces or fish without an explicit count.

Multiple weights/options (`4kg 3kg 2kg 1kg`), count ranges (`8~10과`), and
multipacks with unresolved totals are rejected; never pick the first/last number
or use the manifest's desired quantity as evidence.

For `개`/`마리` targets the script opens the exposed product link in a temporary
tab and reads the currently selected option, public sale price, and order quantity
from one local purchase area. It never changes options or purchases anything.
Explicit `2마리 × 3팩` is 6마리; a box alone and count ranges are not counts.
Order quantity must be explicitly 1. Missing selected controls, unsupported detail
layouts, surcharges, conflicting prices, and restricted prices are excluded.
Conditional shipping is unknown, not free. There is no search-card fallback for
count targets. Only an owned new tab is closed; cleanup failure is not success.
Raw CSV retains the selected option, count/price evidence, detail title/text, and
actual product URL. Ingestion validates this evidence again. Live-site support
depends on the accessibility controls exposed by the current page.

The script scans up to four times the requested offer limit (at most 40 visible
eligible cards per target, one search). Candidates with missing or incompatible
quantities do not consume the usable-offer quota. Their raw rows remain as evidence.
If no comparable candidate remains, report that target as failed; do not retry
indefinitely, browse outside the script, or rewrite missing quantities by hand.

Final validation runs with the repository `.venv` and the same CSV parser as ingestion.
Read `validation-report.json` in `run_dir` for row-numbered validation errors,
per-target comparable counts and exclusion reasons. An accessible page or a CSV
with rows is not collection success. Return the validator's final JSON unchanged.

## Output contract

The raw CSV named by `output_csv` is the price data result; `validation-report.json` is a diagnostic artifact. Its exact fields are in
`references/csv-schema.md`; agent prose is not data.

Return a final JSON object with exactly:

- `status`: `success`, `partial`, or `failed`
- `target_count`: manifest target count
- `completed_count`: targets with at least one validated comparable offer
- `failed_keys`: unfinished `item_code:kind_code` values
- `csv_path`: absolute raw CSV path

Preserve failures honestly. Never fabricate or manually rewrite product rows.

### Whole melon exception

A whole melon with a single explicit fruit count (`1개` or `1통`) and one weight
may use that count. A kg box of apples still cannot use its package count as a
fruit count. Reject melon boxes, sets, packs, cut fruit, halves and multiple
weight options. Unknown shipping remains unknown; the exception does not waive
price, shipping, availability or product validation.
For detail verification, the selected option must explicitly establish `개`; a
card's `통` wording alone is insufficient.
