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

## Product exclusions

Exclude product cards marked `광고`, `AD`, or `sponsored`, including labels in
their accessibility text. Exclude unrelated items and processed products: rice
noodles/snacks/storage bins are not rice; cabbage kimchi/green cabbage are not
fresh napa cabbage. A substring match alone does not establish product identity.
Use the shared rules in `app/domain/shopping_filter_rules.json` through the
deterministic script and CSV validator. Apply exclusions before the result limit;
excluded cards must not consume the target's offer quota. Do not count a target
with only excluded cards as completed. Never invent replacements for excluded rows.

## Output contract

The raw CSV named by `output_csv` is the only data result. Its exact fields are in
`references/csv-schema.md`; agent prose is not data.

Return a final JSON object with exactly:

- `status`: `success`, `partial`, or `failed`
- `target_count`: manifest target count
- `completed_count`: targets with accessible product rows
- `failed_keys`: unfinished `item_code:kind_code` values
- `csv_path`: absolute raw CSV path

Preserve failures honestly. Never fabricate or manually rewrite product rows.
