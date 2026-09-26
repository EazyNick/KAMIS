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

Unknown values remain empty or `unknown`; never guess. Escape spreadsheet-formula prefixes.
