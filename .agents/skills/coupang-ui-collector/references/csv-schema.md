# Raw Coupang accessibility CSV

Each row represents one product result exposed by Chrome's Windows accessibility tree.
The collector writes UTF-8 CSV with these columns in this order:

| Column | Contract |
|---|---|
| `run_id` | Must equal the manifest run ID. |
| `observed_date` | Must equal the manifest date (`YYYY-MM-DD`). |
| `collected_at` | ISO 8601 timestamp including an offset. |
| `platform` | Always `coupang`. |
| `item_code` | KAMIS item code from the target. |
| `kind_code` | KAMIS kind code from the target. |
| `query` | Search phrase submitted through the accessible search box. |
| `product_id` | Stable SHA-256-derived ID of the accessible result when no URL ID is exposed. |
| `title` | First line of the accessible result name. |
| `url` | Product URL when accessibility exposes one; otherwise empty. |
| `displayed_price` | Digits-only displayed price when recognized; otherwise empty. |
| `shipping_fee` | Digits-only shipping fee, `0` only when free shipping is explicit, otherwise empty. |
| `member_price` | Digits-only member price when recognized; otherwise empty. |
| `member_discount_scope` | `all_members`, `restricted`, `none`, or `unknown`. |
| `quantity` | Numeric package quantity when recognized; otherwise empty. |
| `unit` | Recognized `kg`, `g`, `개`, and so on; otherwise empty. |
| `unit_price_text` | Original unit-price phrase. |
| `advertisement` | `true` only when the accessible text marks an ad. |
| `availability` | `available`, `sold_out`, or `unknown`. |
| `raw_accessible_name` | Full accessible ListItem name used for downstream validation. |
| `selected_option` | Currently selected product detail option, unmodified. |
| `quantity_evidence` | Same selected option text establishing total pieces/fish. |
| `price_evidence` | Original labeled public sale price in the same purchase area. |
| `detail_accessible_name` | Accessible text of that local purchase area. |
| `detail_product_title` | Product detail document title, checked against the requested item. |
| `evidence_source` | `product_detail` for detail evidence, otherwise empty. |
| `order_quantity` | Explicit selected order quantity; must be `1` for count evidence. |

Unknown values stay empty or `unknown`; they must never be guessed. Spreadsheet-formula
prefixes (`=`, `+`, `-`, `@`) are escaped before CSV serialization.

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
