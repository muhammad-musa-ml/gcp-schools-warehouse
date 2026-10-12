# gcp-schools-warehouse

This repo builds a small data warehouse of Wisconsin public schools on Google Cloud and runs a few queries on it. Terraform creates a private GCS bucket, three BigQuery datasets and a connection to Vertex AI. A Python step downloads the federal school location file from NCES, cleans it and uploads it as Parquet. Dataform loads that into BigQuery and joins every school to the county polygon that contains it. A small CLI runs the steps in order and can take everything down again.

It started as a project in CS 544 (Big Data Systems) at UW-Madison. In the course version we started a VM on Google Compute Engine and worked in JupyterLab over an SSH tunnel. We uploaded the course's Parquet file of Wisconsin schools to a bucket we had created by hand in the console, wrote three Dataform SQLX files (Wisconsin counties from BigQuery's public boundary data, a `LOAD DATA` from the bucket, and a geographic join of the two), uploaded them to a Dataform workspace with the Python client and ran them from the web UI, and then answered ten questions in a notebook. One of those was a pipe-syntax query and one was an `AI.CLASSIFY` call.

I rebuilt it from scratch afterwards so that someone with an empty GCP project can reproduce it. The infrastructure is Terraform instead of console clicks. The data comes from NCES and goes through a cleaning step with tests instead of arriving as a file. Dataform runs from its CLI and has assertions that check the result. There is a teardown command, a CI workflow that needs no cloud credentials, and every query has measured cost and latency in `results/`.

## Layout

- `terraform/`: project APIs, the bucket, the datasets, the BigQuery connection and its IAM grant
- `ingest/`: download, cleaning, Parquet and GCS upload
- `dataform/`: the SQLX project and its assertions
- `queries/`: the analysis queries and `manifest.json` with their parameters
- `scripts/`: the CLI (`python -m scripts`), the terraform and dataform wrappers, the benchmark code
- `results/`: raw measurements, the full output of each query, and `summary.md`
- `tests/`

## Running it

You need a GCP project with billing enabled. The account you log in with has to be able to enable APIs, create buckets and datasets, and grant a project role; Owner on a scratch project is the simple way. On your machine:

- Python 3.13 (`pyproject.toml` allows 3.11 and newer, but I have only run 3.13.5)
- Node.js 22 (22.17.0); the Dataform CLI itself, version 3.0.71, is fetched by `npx` the first time
- Terraform 1.16.5 (`versions.tf` asks for 1.9 or newer), or Docker (28.4.0). If there is no `terraform` on the PATH the CLI runs the `hashicorp/terraform:1.16.5` image and mounts your application default credentials into it read-only.
- the gcloud CLI (529.0.0), only to log in

1. Clone the repo and install the Python dependencies.

   ```
   git clone <url of this repo> gcp-schools-warehouse
   cd gcp-schools-warehouse
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements-dev.txt
   ```

2. Point it at your project.

   ```
   cp .env.example .env            # Windows: copy .env.example .env
   ```

   Open `.env` and set `GCP_PROJECT_ID`. Nothing else is required. The bucket is called `<project id>-schools-raw` unless you set `SCHOOLS_BUCKET`, and `TERRAFORM_BIN` can point at a terraform binary that is not on the PATH.

3. Log in.

   ```
   gcloud auth application-default login
   ```

   The credentials file this writes usually names a quota project, and that is often a different project from the one you are using here. The CLI sets `GOOGLE_CLOUD_QUOTA_PROJECT` to your project for everything it starts (terraform, Dataform, the BigQuery client), and the Terraform provider is configured to bill the same project. If you run other tools against the project yourself, set that variable too.

4. Run everything.

   ```
   python -m scripts all
   ```

   This runs the five steps below in order; it took me 87.0 s (median of three runs, see Measurements). A first run on a new machine also downloads the Terraform provider and the Dataform packages, which those timings do not include.

The steps also work one at a time, and this is what each one prints:

- `python -m scripts apply` runs `terraform init` and `terraform apply`, which enables six APIs and creates the bucket, the three datasets (`schools_raw`, `schools_warehouse`, `schools_assertions`), the BigQuery connection `schools-ai` and a `roles/aiplatform.user` grant for that connection's service account. The grant waits 30 seconds after the connection is created, because project IAM does not see the new service account right away, so a first `apply` pauses there. It prints terraform's own output and then three lines with the project, bucket, datasets and connection.
- `python -m scripts ingest` downloads the NCES file (cached under `data/`), keeps the Wisconsin rows, writes `data/wi_schools.parquet` and uploads it to `schools/wi_schools.parquet` in the bucket. It prints four lines: the source and its checksum, the row counts (rows seen, other states, kept, rejected), the local Parquet size, and the size and modification time in nanoseconds that GCS reports for the uploaded object. Rejected rows would be written to `data/wi_schools_rejects.csv`.
- `python -m scripts transform` runs the Dataform project: it loads the Parquet into `schools_raw.schools`, builds `schools_warehouse.wi_counties` from `bigquery-public-data.geo_us_boundaries.counties`, builds `schools_warehouse.wi_county_schools` with a `ST_CONTAINS` join, and evaluates the assertions. For each action it prints whether it succeeded and the bytes billed.
- `python -m scripts queries` runs the six queries that do not call a model and prints the first rows of each with bytes billed and slot-ms. The `AI.CLASSIFY` query costs money per row, so it only runs when you ask for it: `python -m scripts queries --name classify_name_origin`. If it fails with a permission error right after `apply`, wait a minute and try again; IAM grants can take a while to propagate, though I did not run into that.
- `python -m scripts report` prints the table sizes, the results of the last `queries` run and how many bytes the project has billed in the last 30 days, and writes it to `results/report.md` (not committed).

Two more commands are useful while reading the code. `python -m scripts graph` prints which Dataform action depends on which and needs no cloud access. `python -m scripts status` shows what exists in the project.

## Tests

None of these touch the cloud, and the workflow in `.github/workflows/ci.yml` runs the same checks without credentials:

```
ruff check . && ruff format --check .
pytest
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate
npx --yes @dataform/cli@3.0.71 compile dataform
```

The tests cover the cleaning rules (including the rows with a quoted `|` in the name), the download and Parquet steps against a local HTTP server and a local file system standing in for the bucket, the argument handling and error paths of the CLI, how the terraform and Dataform command lines are built, the query manifest, and the benchmark and summary code. Static checks read the Terraform and SQLX files for the things the scripts rely on.

## Taking it down

```
python -m scripts teardown
```

It asks you to type the project id (or pass `--yes`), deletes every object in the bucket because Terraform will not delete a bucket that still has objects in it, and then runs `terraform destroy`. The APIs stay enabled, because other things in the project may use them.

## The queries

Six of the seven are in BigQuery pipe syntax, and one (`nearest_schools`) is standard SQL so the two can be compared. They are in `queries/`, with parameters in `queries/manifest.json`. For example, the counties that have at least two cities with three or more schools each:

```
FROM `{{ project }}.{{ warehouse }}.wi_county_schools`
|> AGGREGATE COUNT(*) AS schools GROUP BY county_name, city
|> WHERE schools >= @min_schools
|> AGGREGATE
     COUNT(*) AS qualifying_cities,
     STRING_AGG(city, ', ' ORDER BY schools DESC, city) AS cities
   GROUP BY county_name
|> WHERE qualifying_cities >= @min_cities
|> ORDER BY qualifying_cities DESC, county_name
```

The others count schools per county and per 100 square km of land, find the schools closest to the State Capitol with `ST_DISTANCE`, count schools within 10 km of it with `ST_DWITHIN`, and compute the distance from each school to the nearest school at a different location, grouped by NCES locale. The full output of each is in `results/query_output/`.

The `AI.CLASSIFY` query takes the elementary schools in Madison, strips the words Elementary and School, and asks the model whether the rest is named after a person, a place or something else. I pin the model with `endpoint => 'gemini-3.5-flash-lite'`. Without an endpoint BigQuery picks a model itself, and then two runs are not comparable. The call goes through the `schools-ai` connection that Terraform creates.

## Measurements

Everything below was measured on 2026-10-12 and every number is in a file under `results/`; `results/summary.md` is generated from them by `python -m scripts summary`. The commands were:

```
python -m scripts bench --reps 5 --include-ai
python -m scripts stages --reps 3
python -m scripts facts
python -m scripts queries --save-dir results/query_output
python -m scripts summary
```

The client was my Windows 11 machine (13th Gen Intel Core i7-13700HX, 24 logical CPUs, 29.7 GiB, Python 3.13.5, google-cloud-bigquery 3.46.1), outside Google Cloud, talking to BigQuery in the US multi-region. It was not quiet. Containers from unrelated projects were running on it: 9 when I started and 19 when I finished, with the CPU 28 to 37 percent busy before and 36 to 52 percent after, and only 1.2 to 1.4 GiB of memory free (`results/machine_state.txt`). I think that mostly affects the stage timings, since the query timings are dominated by round trips, but I did not test that.

### Queries

Five runs per query, query cache off, from `results/query_runs.csv` and `results/query_summary.csv`. Slot-ms is the median with the minimum and maximum in brackets.

| query | rows returned | bytes processed | bytes billed | slot-ms |
|---|---|---|---|---|
| schools_per_county | 72 | 59091 | 10 MiB | 7 (4 to 9) |
| school_density | 72 | 17347 | 20 MiB | 11 (9 to 13) |
| cities_with_many_schools | 63 | 44042 | 10 MiB | 140 (54 to 164) |
| nearest_schools | 10 | 182971 | 10 MiB | 26 (21 to 37) |
| nearest_neighbour_by_locale | 4 | 135577 | 10 MiB | 6772 (5663 to 10195) |
| schools_within_radius | 5 | 133322 | 10 MiB | 70 (34 to 86) |
| classify_name_origin | 30 | 73314 | 10 MiB | 7015 (6219 to 8872) |

| query | job seconds | wall seconds |
|---|---|---|
| schools_per_county | 0.193 (0.174 to 0.268) | 0.99 (0.86 to 2.70) |
| school_density | 0.172 (0.165 to 0.359) | 1.18 (0.92 to 2.10) |
| cities_with_many_schools | 0.372 (0.241 to 0.490) | 1.02 (0.90 to 1.18) |
| nearest_schools | 0.222 (0.182 to 0.241) | 0.91 (0.77 to 1.01) |
| nearest_neighbour_by_locale | 0.636 (0.555 to 0.665) | 1.22 (1.18 to 1.42) |
| schools_within_radius | 0.254 (0.214 to 0.367) | 0.95 (0.89 to 1.77) |
| classify_name_origin | 2.655 (2.187 to 3.913) | 3.52 (3.23 to 5.10) |

Job seconds is the job's own start to end as BigQuery reports it. Wall seconds is measured in my Python process around submitting the query and fetching the rows, so it includes the network. Both are the median with the minimum and maximum in brackets.

These tables are tiny, and that changes how the numbers read. All three together are about 3.7 MB (506907, 2543539 and 634420 bytes in `results/table_rows.csv`). BigQuery bills at least 10 MiB for each table a query touches, so every query bills 10 MiB, or 20 MiB for the one that reads two tables, however little it processes (17 KB to 183 KB here). The pricing page says the same, and that the first 1 TiB per month is free (cloud.google.com/bigquery/pricing, checked 2026-10-12). So the "runs per free TiB" column in `summary.md`, 104857 for a 10 MiB query, tells you about the minimum and not about the query. Bytes processed is the figure to look at. The same goes for latency: a query takes a fraction of a second inside BigQuery and about a second from my machine, and most of the difference is the round trips. With 2,232 rows I would not draw conclusions about how these queries scale. The cross join in `nearest_neighbour_by_locale` compares every school with every other one and is the only SQL query that uses much compute: 6772 slot-ms against 140 or fewer for the other five.

The 35 benchmark runs billed 419430400 bytes in total, 0.000381 TiB, which is about 0.0024 USD at the list price of 6.25 USD per TiB (`results/run_info.json`), before the free tier. That number leaves out storage, the Dataform runs below and the model calls of the `AI.CLASSIFY` query. Vertex AI bills the model calls separately and I did not measure that; the billing console is the place to look.

The `AI.CLASSIFY` query classified the same 30 schools in each of the five runs, with `gemini-3.5-flash-lite`. 28 of the 30 got the same label every time. Huegel Elementary was labelled Other, Person, Other, Other and Place, and Muir Elementary Person four times and Other once (`results/classify_name_origin_labels.csv`). So the output is a plausible guess that changes between runs, and I would not use it as a source of truth.

### Pipeline stages

Three runs each, one process per stage, from `results/pipeline_runs.csv`. The numbers are seconds, median with the minimum and maximum in brackets.

| stage | command | seconds |
|---|---|---|
| ingest | `python -m scripts ingest --refresh` | 25.4 (25.1 to 28.0) |
| transform | `python -m scripts transform` | 28.0 (19.6 to 77.4) |
| all | `python -m scripts all` | 87.0 (82.8 to 91.4) |

`ingest` downloads the file again every time, and the `all` runs started with the downloaded file deleted. The npx cache and the Terraform provider were already there. The first `transform` run took 77.4 s and the next two 28.0 s and 19.6 s. The logs show nothing different between them and I did not find out why; each run installs the Dataform core package into a temporary directory, which is where I would look first. Every `transform` run billed 273 MiB across its 11 actions (`results/dataform_actions.csv`): 183 MiB for reading the public counties table, 20 MiB for building `wi_county_schools`, and 10 MiB for each of seven assertions. The counties query selects the geometry column, and BigQuery bills the whole column even though only the Wisconsin rows are kept.

### What is in the tables

Read from BigQuery after the last run (`results/data_facts.json`). The NCES file has 102178 rows; 99946 are other states and 2232 are Wisconsin, with none rejected by the cleaning. `schools_raw.schools` and `schools_warehouse.wi_county_schools` have 2232 rows, `wi_counties` has 72. All 2232 schools matched exactly one county, the polygon county is the county NCES lists for every one of them, and all 72 counties have at least one school. All eight assertion views return zero rows. The object in the bucket is 140913 bytes, the same size as the local file.

Some of what the queries show, from `results/query_output/`: Milwaukee County has the most schools (280) and the most per 100 square km (44.77, with Waukesha next at 7.94); Dane has 169 in 21 cities; the median distance from a school to the next one at a different location is 0.61 km in towns, 0.69 in cities, 0.92 in suburbs and 2.44 km in rural areas.

## What is not finished or not tested

- The NCES file has no school level, school type or district, so "elementary" in the `AI.CLASSIFY` query means the name contains the word Elementary, and it only looks at Madison. The course's file had those columns. Several schools often share one campus, which would put their distance at zero, so the nearest-neighbour query ignores pairs at identical coordinates. That is a choice, not a fact about the data.
- Only the 2024-25 NCES file, only Wisconsin: the state code, the FIPS code 55 and the coordinate bounding box are fixed in the code and the SQL.
- Terraform state is a local file in `terraform/`. If you lose it you have to import the resources or delete them by hand. The bucket, datasets and connection are all in the US multi-region because the public counties table is.
- Dataform runs with your own credentials from the CLI. There is no service account for it and nothing runs on a schedule.
- All measurements come from one machine that was shared with other work, three runs per pipeline stage and five per query. Wall seconds include my own network connection, which I did not characterise, and the job overhead I describe is inferred from the gap between job seconds and wall seconds.
- I have not measured storage cost or the cost of the model calls.
- Python 3.11, 3.12, Node 18 and 20, and Terraform versions other than 1.16.5 are untested.
