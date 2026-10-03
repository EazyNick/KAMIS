---
name: coupang-ui-collector
description: Collect a bounded Coupang product-price manifest through the user's ordinary Chrome session with Windows UI Automation and write the raw accessibility results to the requested CSV. Use only when explicitly invoked for the KAMIS repository's Coupang collection run.
---

# Coupang UI Collector

Use the deterministic repository script for collection. Do not browse independently,
edit application code, infer missing targets, or turn accessibility/CAPTCHA failures into
successful results.

## Required input

Receive one absolute JSON manifest path through `-ManifestPath`. The manifest must contain
`run_id`, `observed_date`, `run_dir`, `output_csv`, and no more than 10 `targets`. Each target
contains `item_code`, `kind_code`, `item_name`, `variety`, `comparison_unit`, and `query`.

## Execution

From the repository root, run exactly:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .agents\skills\coupang-ui-collector\scripts\collect_coupang_ui.ps1 -ManifestPath <manifest-path>
```

Do not use a direct Coupang search URL. The script reuses an ordinary Chrome window or opens
the Coupang homepage first, locates the accessible search box, and submits each query through
Windows UI Automation. Never attempt to evade an access block, CAPTCHA, login requirement, or
other access control.

## Browser cleanup

Browser cleanup is mandatory after the collection attempt finishes, including success,
partial success, script failure, parsing failure, timeout, or any other exception.

- Close the Coupang tab or browser window used for this collection run before returning the
  final JSON status.
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
or use the manifest's desired quantity as evidence. The current script does not
read selected options on product detail pages. Do not claim it verified them.

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

The script writes the raw CSV named by `output_csv` and a `validation-report.json` diagnostic artifact; its columns are defined in
`references/csv-schema.md`. Treat the CSV as the data result, not any prose in the agent reply.

Return a final JSON object with exactly these fields:

- `status`: `success`, `partial`, or `failed`
- `target_count`: number of manifest targets
- `completed_count`: targets with at least one validated comparable offer
- `failed_keys`: array of `item_code:kind_code` values not completed
- `csv_path`: absolute output path

If the script fails, preserve its failure honestly in the final JSON. Do not fabricate rows or
manually rewrite the CSV.

### Whole melon exception

A whole melon with a single explicit fruit count (`1개` or `1통`) and one weight
may use that count. A kg box of apples still cannot use its package count as a
fruit count. Reject melon boxes, sets, packs, cut fruit, halves and multiple
weight options. Unknown shipping remains unknown; the exception does not waive
price, shipping, availability or product validation.
