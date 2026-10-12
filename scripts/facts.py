import json
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery

from . import bench
from .config import DATA_DIR, Stack

INGEST_SUMMARY = DATA_DIR / "ingest_summary.json"

JOIN_FACTS_SQL = """
SELECT
  COUNT(*) AS schools,
  COUNT(DISTINCT ncessch) AS distinct_school_ids,
  COUNTIF(county_geo_id IS NOT NULL) AS matched_to_a_county,
  COUNTIF(county_matches_nces) AS county_agrees_with_nces,
  COUNT(DISTINCT county_geo_id) AS counties_with_schools,
  (SELECT COUNT(*) FROM `{project}.{warehouse}.wi_counties`) AS counties_total
FROM `{project}.{warehouse}.wi_county_schools`
"""


def ingest_facts(summary: dict | None) -> dict | None:
    """The parts of the ingest summary worth keeping; no local paths, no bucket name."""
    if summary is None:
        return None
    uploaded = summary.get("uploaded") or {}
    return {
        "source_url": summary["source_url"],
        "source_zip_sha256": summary["zip_sha256"],
        "rows_seen": summary["rows_seen"],
        "rows_other_states": summary["rows_other_states"],
        "rows_kept": summary["rows_kept"],
        "rows_rejected": summary["rows_rejected"],
        "parquet_bytes": summary["parquet_bytes"],
        "uploaded_object": uploaded.get("path", "").split("/", 1)[-1] or None,
        "uploaded_size_bytes": uploaded.get("size"),
        "uploaded_mtime_ns": uploaded.get("mtime_ns"),
    }


def assertion_results(client: bigquery.Client, stack: Stack) -> list[dict]:
    """Evaluate every Dataform assertion view now; a view that returns rows is a failure."""
    results = []
    dataset = f"{stack.project_id}.{stack.assertions_dataset}"
    for table in sorted(client.list_tables(dataset), key=lambda t: t.table_id):
        sql = f"SELECT COUNT(*) AS n FROM `{dataset}.{table.table_id}`"
        n = next(iter(client.query(sql).result()))["n"]
        results.append({"assertion": table.table_id, "violating_rows": n, "passes": n == 0})
    return results


def collect(client: bigquery.Client, stack: Stack, ingest_summary: dict | None) -> dict:
    sql = JOIN_FACTS_SQL.format(project=stack.project_id, warehouse=stack.warehouse_dataset)
    join = dict(next(iter(client.query(sql).result())))
    return {
        "measured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": bench.table_stats(client, stack),
        "county_join": join,
        "assertions": assertion_results(client, stack),
        "ingest": ingest_facts(ingest_summary),
    }


def load_ingest_summary(path: Path = INGEST_SUMMARY) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
