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

Unknown values stay empty or `unknown`; they must never be guessed. Spreadsheet-formula
prefixes (`=`, `+`, `-`, `@`) are escaped before CSV serialization.
