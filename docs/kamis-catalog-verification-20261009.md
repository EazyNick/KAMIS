# KAMIS catalog corrections verified 2026-10-09

Source: bundled code workbook, distribution-channel rows; live period API probes for 2026-09-01 through 2026-09-30 and seasonal follow-up for 2025-11-01 through 2025-11-30, convert_kg=N. Only responses with official-average prices were accepted. Existing combinations are retained because an empty recent response cannot disprove historical or seasonal availability.

| Item | Kind | Channel | Rank | Observations |
|---|---|---|---|---|
| 144 | 01 | wholesale | 05 | 20 |
| 248 | 00 | retail | 04 | 20 |
| 248 | 01 | retail | 04 | 20 |
| 313 | 01 | wholesale | 04 | 20 |
| 313 | 01 | wholesale | 05 | 20 |
| 313 | 02 | wholesale | 05 | 20 |
| 318 | 00 | retail | 05 | 20 |
| 319 | 00 | retail | 05 | 20 |
| 430 | 00 | retail | 04 | 20 |
| 614 | 06 | retail | 21 | 20 |
| 614 | 06 | retail | 22 | 20 |
| 614 | 07 | retail | 21 | 20 |
| 641 | 00 | wholesale | 05 | 20 |
| 642 | 00 | wholesale | 04 | 20 |
| 653 | 00 | wholesale | 05 | 20 |
| 654 | 01 | wholesale | 05 | 20 |
| 658 | 02 | wholesale | 04 | 20 |
| 660 | 01 | wholesale | 04 | 20 |

| 216 | 00 | retail | 04 | 20 |
| 614 | 05 | retail | 21 | 20 |
| 614 | 05 | retail | 22 | 20 |
| 644 | 00 | wholesale | 04 | 20 |
| 659 | 01 | wholesale | 04 | 20 |

## Eco prices

Eco prices use periodEcoPriceList, documented for April 2020 onward. They are stored with price_type=eco and displayed separately as kamis_eco. Dates returned without a year use the request year; cross-year requests are split first. They are never relabeled as ordinary retail prices.

Official API reference: https://www.kamis.or.kr/customer/reference/openapi_list.do?action=detail&boardno=12

The verified override file is config/kamis_verified_catalog_overrides.json. It is applied whenever productInfo is fetched. Units are taken from the matching distribution-channel code-table row; they do not establish that survey units were constant over all historical years.
