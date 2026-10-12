# gcp-schools-warehouse

A small data warehouse for Wisconsin K-12 schools on Google Cloud: Terraform builds the
bucket and BigQuery datasets, a Python step loads the public NCES school locations into
GCS as Parquet, Dataform turns that into tables joined to county boundaries, and a handful
of queries (some in pipe syntax, one with AI.CLASSIFY) run on top.

Work in progress: this file only has run instructions so far. Sections still to write are
listed at the bottom.

## Run it

You need a GCP project with billing, and these installed:

- Python 3.11+ (developed on 3.13)
- Node.js 18+ (developed on 22)
- Terraform 1.9+ on PATH, or Docker (the CLI falls back to the `hashicorp/terraform` image)
- the gcloud CLI, only for `gcloud auth application-default login`

```
cp .env.example .env                     # put your project id in GCP_PROJECT_ID
gcloud auth application-default login
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt     # Windows: .venv\Scripts\pip
python -m scripts all
```

`all` runs, in order: `apply` (APIs, bucket, datasets, AI connection), `ingest` (download,
clean, upload the Parquet), `transform` (Dataform run, assertions included), `queries`
and `report`. Each step is also a command of its own, see `python -m scripts --help`.
The AI.CLASSIFY query costs a little per row and is left out unless you pass `--include-ai`.
`python -m scripts graph` prints which Dataform action depends on which and needs no cloud
access.

The account running it needs to be able to enable APIs, create buckets and datasets and
grant a project role; Owner on a scratch project is the easy way.

Tests and linting, none of which touch the cloud:

```
ruff check . && ruff format --check .
pytest
terraform -chdir=terraform fmt -check && terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate
npx --yes @dataform/cli@3.0.71 compile dataform
```

Measurement harness (writes CSV files under `results/`; the cache is off, 5 repetitions
by default):

```
python -m scripts bench --reps 5
```

Tear it all down (empties the bucket, then `terraform destroy`):

```
python -m scripts teardown
```

## Layout

- `terraform/` project APIs, bucket, datasets, BigQuery connection and its IAM grant
- `ingest/` NCES download, cleaning, Parquet, GCS upload (pyarrow, ADC)
- `dataform/` SQLX project: schools load, Wisconsin counties, county join, assertions
- `queries/` analysis queries plus `manifest.json` (parameters, which ones call a model)
- `scripts/` the CLI, the terraform and dataform wrappers, the benchmark harness
- `tests/` unit tests and static checks

## To write in the measurement phase

- [ ] intro and provenance (CS 544 at UW-Madison: what the course version did, what this adds)
- [ ] measured results: bytes processed, slot-ms and latency per query, 5 runs, machine and config, command
- [ ] row counts per table and the cost estimate
- [ ] AI.CLASSIFY: model used (`gemini-3.5-flash-lite` pinned in the query), sample output, what varies between runs
- [ ] limitations: no school level in the NCES file so "elementary" is read from the name,
      local Terraform state, US multi-region only, the counties table scan dominates the Dataform bill
- [ ] decide whether to show a short example of the output of each query
