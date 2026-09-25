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

## Output contract

The script writes only the raw CSV named by `output_csv`; its columns are defined in
`references/csv-schema.md`. Treat the CSV as the data result, not any prose in the agent reply.

Return a final JSON object with exactly these fields:

- `status`: `success`, `partial`, or `failed`
- `target_count`: number of manifest targets
- `completed_count`: targets for which accessible product rows were written
- `failed_keys`: array of `item_code:kind_code` values not completed
- `csv_path`: absolute output path

If the script fails, preserve its failure honestly in the final JSON. Do not fabricate rows or
manually rewrite the CSV.
