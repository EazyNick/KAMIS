# Raw Naver Shopping accessibility CSV

Each row represents one result exposed by Chrome's Windows accessibility tree. The collector
writes UTF-8 CSV with these columns in order:

| Column | Contract |
|---|---|
| `run_id` | Manifest run ID. |
| `observed_date` | Manifest date (`YYYY-MM-DD`). |
| `collected_at` | ISO 8601 timestamp with offset. |
| `platform` | Always `naver`. |
| `item_code` | KAMIS item code. |
| `kind_code` | KAMIS kind code. |
| `query` | Search phrase submitted through the accessible input. |
| `product_id` | Stable SHA-256-derived ID based on the exposed product URL. |
| `title` | First accessible result line. |
| `url` | Required HTTPS URL on `naver.com` or one of its subdomains. |
| `displayed_price` | Digits-only public price when recognized. |
| `shipping_fee` | Digits-only fee; `0` only for explicit free shipping. |
| `member_price` | Digits-only member price when recognized. |
| `member_discount_scope` | `all_members`, `restricted`, `none`, or `unknown`. |
| `quantity` | Numeric package quantity when recognized. |
| `unit` | Recognized package unit, otherwise empty. |
| `unit_price_text` | Original unit-price phrase. |
| `advertisement` | `true` only when explicitly marked as advertising. |
| `availability` | `available`, `sold_out`, or `unknown`. |
| `raw_accessible_name` | Full accessible result name used by downstream validation. |
| `selected_option` | Currently selected product detail option, unmodified. |
| `quantity_evidence` | Same selected option text establishing total pieces/fish. |
| `price_evidence` | Original labeled public sale price in the same purchase area. |
| `detail_accessible_name` | Accessible text of that local purchase area. |
| `detail_product_title` | Product detail document title, checked against the requested item. |
| `evidence_source` | `product_detail` for detail evidence, otherwise empty. |
| `order_quantity` | Explicit selected order quantity; must be `1` for count evidence. |

Unknown values remain empty or `unknown`; never guess. Escape spreadsheet-formula prefixes.

## Quantity evidence

`quantity` and `unit` must refer to the same unambiguous offer as `displayed_price`.
Explicit fruit counts in 과 normalize to 개; fish counts in 미 normalize to 마리.
Multiple option quantities, ranges, per-unit prices, and unclear multipacks do not
establish a package quantity. Preserve the original text in `raw_accessible_name`.
Unknown quantities stay empty and are excluded by validation. Never infer pieces
from kg, use the requested comparison size, or treat one box as one fruit.

For count targets, the detail evidence above and an HTTPS product URL are required.
`2마리 × 3팩` supplies `quantity=6, unit=마리`; `10과` supplies `10,개`.
Price, shipping and count come from the same selected detail offer. No card fallback.
Older CSVs remain readable, but count rows without detail evidence are excluded.
Normalized offers also retain `offered_quantity`/`offered_unit` before KAMIS scaling.

Raw rejected candidates may exceed the usable-offer quota; they are retained for
diagnosis, not included in the average. `validation-report.json` records validation
errors and counts; it is not a substitute for raw CSV evidence.
