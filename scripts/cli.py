import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from google.cloud import bigquery

from ingest import gcs, pipeline

from . import bench, dataform, queries, report, terraform
from .config import (
    AI_ENDPOINT,
    DATA_DIR,
    RESULTS_DIR,
    SCHOOL_YEAR_CODE,
    ConfigError,
    Settings,
    Stack,
    load_settings,
)

PROG = "python -m scripts"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="Wisconsin schools warehouse on GCP")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("apply", help="terraform apply: APIs, bucket, datasets, AI connection")

    s = sub.add_parser("ingest", help="download, clean and upload the schools Parquet")
    s.add_argument("--year", default=SCHOOL_YEAR_CODE, help="NCES school year code, e.g. 2425")
    s.add_argument("--refresh", action="store_true", help="download the source file again")
    s.add_argument("--no-upload", action="store_true", help="write the Parquet locally only")

    s = sub.add_parser("transform", help="run the Dataform project")
    s.add_argument("--compile-only", action="store_true", help="compile without touching BigQuery")
    s.add_argument("--actions", nargs="+", help="run only these actions")

    s = sub.add_parser("queries", help="run the analysis queries once")
    _query_args(s)
    s.add_argument("--dry-run", action="store_true", help="validate and estimate bytes only")
    s.add_argument("--rows", type=int, default=10, help="rows to print per query")

    s = sub.add_parser("bench", help="repeat each query with the cache off and record the stats")
    _query_args(s)
    s.add_argument("--reps", type=int, default=5)
    s.add_argument("--out", type=Path, default=RESULTS_DIR, help="directory for the CSV files")

    sub.add_parser("report", help="print table sizes, last query results and bytes billed")
    sub.add_parser("status", help="show what exists in the project")

    s = sub.add_parser("all", help="apply, ingest, transform, queries, report in order")
    s.add_argument("--include-ai", action="store_true", help="also run the AI.CLASSIFY query")

    s = sub.add_parser("teardown", help="empty the bucket and terraform destroy")
    s.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    return p


def _query_args(s: argparse.ArgumentParser) -> None:
    s.add_argument("--name", nargs="+", help="only these queries (see queries/manifest.json)")
    s.add_argument("--include-ai", action="store_true", help="include AI.CLASSIFY queries")
    s.add_argument("--endpoint", default=AI_ENDPOINT, help="Gemini model for AI.CLASSIFY")


def _client(stack: Stack) -> bigquery.Client:
    return bigquery.Client(project=stack.project_id, location=stack.location)


def cmd_apply(settings: Settings, args) -> Stack:
    stack = terraform.apply(settings)
    print(f"project {stack.project_id}, bucket {stack.bucket}")
    print(f"datasets {stack.raw_dataset}, {stack.warehouse_dataset}, {stack.assertions_dataset}")
    print(f"ai connection {stack.ai_connection}")
    return stack


def cmd_ingest(settings: Settings, args) -> None:
    stack = None if args.no_upload else terraform.load_stack(settings)
    summary = pipeline.run(
        year_code=args.year,
        data_dir=DATA_DIR,
        bucket=stack.bucket if stack else None,
        refresh=args.refresh,
    )
    print(f"source {summary.source_url} sha256 {summary.zip_sha256[:16]}")
    print(
        f"rows seen {summary.rows_seen}, other states {summary.rows_other_states}, "
        f"kept {summary.rows_kept}, rejected {summary.rows_rejected}"
    )
    print(f"parquet {summary.parquet_path} ({summary.parquet_bytes} bytes)")
    if summary.uploaded:
        u = summary.uploaded
        print(f"uploaded gs://{u.path}: size {u.size} bytes, modified {u.mtime_ns} ns")


def cmd_transform(settings: Settings, args) -> None:
    stack = terraform.load_stack(settings)
    if args.compile_only:
        dataform.run("compile", stack)
        return
    extra = ["--actions", *args.actions] if args.actions else None
    dataform.run("run", stack, extra=extra)


def cmd_queries(settings: Settings, args) -> None:
    stack = terraform.load_stack(settings)
    client = _client(stack)
    specs = queries.select(queries.load_manifest(), args.name, args.include_ai)
    for spec in specs:
        print(f"\n== {spec.name}: {spec.title}")
        if args.dry_run:
            estimate = queries.dry_run(client, spec, stack, args.endpoint)
            print(f"valid, would process {estimate} bytes")
            continue
        rows, stats = queries.run(client, spec, stack, endpoint=args.endpoint)
        print(report.format_table(rows, args.rows))
        print(
            f"-- {stats.rows} rows, {stats.bytes_billed} bytes billed, {stats.slot_ms} slot-ms, "
            f"{stats.wall_s:.2f}s"
        )
        report.save_query_run(spec.name, spec.title, rows, asdict(stats))


def cmd_bench(settings: Settings, args) -> None:
    if args.reps < 1:
        raise ConfigError("--reps must be at least 1")
    stack = terraform.load_stack(settings)
    client = _client(stack)
    specs = queries.select(queries.load_manifest(), args.name, args.include_ai)
    runs = bench.run_all(client, stack, specs, reps=args.reps, endpoint=args.endpoint)
    out = args.out
    env = bench.environment(stack, args.reps, args.endpoint)
    bench.write_results(
        out, runs, bench.table_stats(client, stack), env, bench.project_usage(client, stack)
    )
    cost = bench.estimate_cost(runs)
    print(f"wrote {out}; {cost['bytes_billed_total']} bytes billed over {cost['runs']} runs")


def cmd_report(settings: Settings, args) -> None:
    stack = terraform.load_stack(settings)
    client = _client(stack)
    text = report.markdown(
        stack, bench.table_stats(client, stack), bench.project_usage(client, stack)
    )
    path = RESULTS_DIR / "report.md"
    report.write_markdown(path, text)
    print(text)
    print(f"written to {path}")


def cmd_status(settings: Settings, args) -> None:
    stack = terraform.load_stack(settings)
    print(json.dumps(asdict(stack), indent=2))
    print("bucket top level:", gcs.list_top_level(gcs.gcs_filesystem(), stack.bucket))
    print(report.format_table(bench.table_stats(_client(stack), stack), 50))


def cmd_all(settings: Settings, args) -> None:
    cmd_apply(settings, args)
    cmd_ingest(settings, argparse.Namespace(year=SCHOOL_YEAR_CODE, refresh=False, no_upload=False))
    cmd_transform(settings, argparse.Namespace(compile_only=False, actions=None))
    cmd_queries(
        settings,
        argparse.Namespace(
            name=None, include_ai=args.include_ai, endpoint=AI_ENDPOINT, dry_run=False, rows=10
        ),
    )
    cmd_report(settings, args)


def cmd_teardown(settings: Settings, args) -> None:
    stack = terraform.load_stack(settings)
    if not args.yes:
        if not sys.stdin.isatty():
            raise ConfigError("not a terminal; pass --yes to tear down without asking")
        answer = input(
            f"This deletes the bucket, datasets and connection in {stack.project_id}.\n"
            "Type the project id to continue: "
        )
        if answer.strip() != stack.project_id:
            print("nothing deleted")
            return
    removed = gcs.empty_bucket(gcs.gcs_filesystem(), stack.bucket)
    print(f"deleted {removed} objects from {stack.bucket}")
    terraform.destroy(settings)
    print("destroyed")


COMMANDS = {
    "apply": cmd_apply,
    "ingest": cmd_ingest,
    "transform": cmd_transform,
    "queries": cmd_queries,
    "bench": cmd_bench,
    "report": cmd_report,
    "status": cmd_status,
    "all": cmd_all,
    "teardown": cmd_teardown,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest" and args.no_upload:
            settings = Settings(project_id="not-used")
        else:
            settings = load_settings()
            # Application default credentials often name some other project as the quota project.
            os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] = settings.project_id
        COMMANDS[args.command](settings, args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(
            f"error: {' '.join(map(str, e.cmd[:3]))} ... exited with {e.returncode}",
            file=sys.stderr,
        )
        return 1
    return 0
