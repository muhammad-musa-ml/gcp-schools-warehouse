# Measured results

Queries measured 2026-10-12T19:34:52+00:00 (UTC) at commit 836b8b82260c65f8c134f0a424a39728fd97e745.
Client: Windows 11 AMD64, 13th Gen Intel(R) Core(TM) i7-13700HX, 24 logical CPUs, 29.7 GiB, Python 3.13.5, google-cloud-bigquery 3.46.1. The client ran outside Google Cloud.
BigQuery location US, query cache disabled, 5 runs per query.

## Queries

| query | rows returned | bytes processed | bytes billed | slot-ms, median (min to max) | job seconds, median (min to max) | wall seconds, median (min to max) | runs per free TiB |
|---|---|---|---|---|---|---|---|
| schools_per_county | 72 | 59091 | 10 MiB | 7 (4 to 9) | 0.193 (0.174 to 0.268) | 0.99 (0.86 to 2.70) | 104857 |
| school_density | 72 | 17347 | 20 MiB | 11 (9 to 13) | 0.172 (0.165 to 0.359) | 1.18 (0.92 to 2.10) | 52428 |
| cities_with_many_schools | 63 | 44042 | 10 MiB | 140 (54 to 164) | 0.372 (0.241 to 0.490) | 1.02 (0.90 to 1.18) | 104857 |
| nearest_schools | 10 | 182971 | 10 MiB | 26 (21 to 37) | 0.222 (0.182 to 0.241) | 0.91 (0.77 to 1.01) | 104857 |
| nearest_neighbour_by_locale | 4 | 135577 | 10 MiB | 6772 (5663 to 10195) | 0.636 (0.555 to 0.665) | 1.22 (1.18 to 1.42) | 104857 |
| schools_within_radius | 5 | 133322 | 10 MiB | 70 (34 to 86) | 0.254 (0.214 to 0.367) | 0.95 (0.89 to 1.77) | 104857 |
| classify_name_origin | 30 | 73314 | 10 MiB | 7015 (6219 to 8872) | 2.655 (2.187 to 3.913) | 3.52 (3.23 to 5.10) | 104857 |

The cache was off for every run. 35 runs billed 419430400 bytes in total (0.000381 TiB), about 0.0024 USD at the list price of 6.25 USD per TiB before the free tier.

classify_name_origin: model gemini-3.5-flash-lite, 30 schools classified per run, 28 of them got the same label in all 5 runs.

## Pipeline stages

Measured 2026-10-12T19:35:08+00:00 (UTC), 3 runs each.

| stage | runs | failed | seconds, median (min to max) |
|---|---|---|---|
| ingest | 3 | 0 | 25.4 (25.1 to 28.0) |
| transform | 3 | 0 | 28.0 (19.6 to 77.4) |
| all | 3 | 0 | 87.0 (82.8 to 91.4) |

Dataform runs timed above, from their logs:

- run 1: 11 actions, 0 not ok, 286261248 bytes billed (273 MiB), largest schools_warehouse.wi_counties with 183 MiB
- run 2: 11 actions, 0 not ok, 286261248 bytes billed (273 MiB), largest schools_warehouse.wi_counties with 183 MiB
- run 3: 11 actions, 0 not ok, 286261248 bytes billed (273 MiB), largest schools_warehouse.wi_counties with 183 MiB

## Data facts

| table | rows | bytes |
|---|---|---|
| schools_raw.schools | 2232 | 506907 |
| schools_warehouse.wi_counties | 72 | 2543539 |
| schools_warehouse.wi_county_schools | 2232 | 634420 |

- schools: 2232, distinct ids: 2232
- matched to a county by the polygon join: 2232
- polygon county equal to the county NCES lists: 2232
- counties in wi_counties: 72, counties with at least one school: 72
- NCES file: 102178 rows, 99946 in other states, 2232 kept, 0 rejected
- Parquet: 140913 bytes; object in GCS: 140913 bytes, modified 1791834131712000000 ns
- assertion views with zero violating rows: 8 of 8
