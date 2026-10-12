import csv
import json
import platform
import statistics
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, fields
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from google.cloud import bigquery

from . import queries
from .config import AI_ENDPOINT, BQ_USD_PER_TIB, REPO, Stack
from .queries import QuerySpec, RunStats

TIB = 2**40


def run_all(
    client: bigquery.Client,
    stack: Stack,
    specs: list[QuerySpec],
    *,
    reps: int,
    endpoint: str = AI_ENDPOINT,
    log=print,
) -> list[RunStats]:
    """Every query reps times, query cache off, so each run does the real work."""
    runs = []
    for spec in specs:
        for rep in range(1, reps + 1):
            _, stats = queries.run(client, spec, stack, rep=rep, use_cache=False, endpoint=endpoint)
            runs.append(stats)
            log(
                f"{spec.name} rep {rep}/{reps}: {stats.wall_s:.2f}s wall, "
                f"{stats.slot_ms} slot-ms, {stats.bytes_billed} bytes billed"
            )
    return runs


def _spread(
    values: Iterable[float | int | None],
) -> tuple[float | None, float | None, float | None]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None, None
    return statistics.median(vals), min(vals), max(vals)


def summarize(runs: list[RunStats]) -> list[dict]:
    out = []
    for name in dict.fromkeys(r.query for r in runs):
        mine = [r for r in runs if r.query == name]
        row = {"query": name, "reps": len(mine), "cache_hits": sum(r.cache_hit for r in mine)}
        for label, values in (
            ("wall_s", [r.wall_s for r in mine]),
            ("server_s", [r.server_s for r in mine]),
            ("slot_ms", [r.slot_ms for r in mine]),
            ("bytes_processed", [r.bytes_processed for r in mine]),
            ("bytes_billed", [r.bytes_billed for r in mine]),
        ):
            med, lo, hi = _spread(values)
            row[f"{label}_median"], row[f"{label}_min"], row[f"{label}_max"] = med, lo, hi
        billed = row["bytes_billed_median"]
        row["runs_per_free_tib"] = int(TIB // billed) if billed else None
        out.append(row)
    return out


def estimate_cost(runs: list[RunStats]) -> dict:
    total = sum(r.bytes_billed or 0 for r in runs)
    return {
        "runs": len(runs),
        "bytes_billed_total": total,
        "tib_billed": total / TIB,
        "usd_per_tib_list_price": BQ_USD_PER_TIB,
        "usd_at_list_price": round(total / TIB * BQ_USD_PER_TIB, 4),
        "note": (
            "Analysis cost only, before the monthly 1 TiB free tier. Storage, the Dataform "
            "build and AI.CLASSIFY model calls are not included."
        ),
    }


def table_stats(client: bigquery.Client, stack: Stack) -> list[dict]:
    out = []
    for dataset, table in (
        (stack.raw_dataset, "schools"),
        (stack.warehouse_dataset, "wi_counties"),
        (stack.warehouse_dataset, "wi_county_schools"),
    ):
        t = client.get_table(f"{stack.project_id}.{dataset}.{table}")
        out.append({"table": f"{dataset}.{table}", "rows": t.num_rows, "bytes": t.num_bytes})
    return out


def project_usage(client: bigquery.Client, stack: Stack, days: int = 30) -> dict:
    """Bytes billed by every query job in the project, Dataform and bench runs included."""
    region = f"region-{stack.location.lower()}"
    sql = f"""
        SELECT COUNT(*) AS jobs, IFNULL(SUM(total_bytes_billed), 0) AS bytes_billed,
               IFNULL(SUM(total_slot_ms), 0) AS slot_ms
        FROM `{region}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
        WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {int(days)} DAY)
          AND job_type = 'QUERY' AND state = 'DONE' AND error_result IS NULL
    """
    row = next(iter(client.query(sql).result()))
    return {
        "window_days": days,
        "query_jobs": row["jobs"],
        "bytes_billed": row["bytes_billed"],
        "slot_ms": row["slot_ms"],
    }


def environment(stack: Stack, reps: int, endpoint: str) -> dict:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {
        "date_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": commit,
        "bigquery_location": stack.location,
        "reps_per_query": reps,
        "query_cache": "disabled",
        "ai_endpoint": endpoint,
        "client": f"google-cloud-bigquery {metadata.version('google-cloud-bigquery')}",
        "python": platform.python_version(),
        "os": f"{platform.system()} {platform.release()} {platform.machine()}",
        "note": (
            "wall_s is measured on the client around job submit and result fetch, so it "
            "includes the network path from this machine; server_s is the job's own start to end."
        ),
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_results(
    out_dir: Path, runs: list[RunStats], tables: list[dict], env: dict, usage: dict | None
) -> None:
    run_fields = [f.name for f in fields(RunStats)]
    _write_csv(out_dir / "query_runs.csv", [{k: asdict(r)[k] for k in run_fields} for r in runs])
    _write_csv(out_dir / "query_summary.csv", summarize(runs))
    _write_csv(out_dir / "table_rows.csv", tables)
    report = {"environment": env, "cost_estimate": estimate_cost(runs), "project_usage": usage}
    (out_dir / "run_info.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
