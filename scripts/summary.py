import csv
import json
from pathlib import Path

MIB = 2**20


def _read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _num(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def _fmt(value: float | None, digits: int = 0) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _span(row: dict, key: str, digits: int) -> str:
    med, lo, hi = (_num(row[f"{key}_{k}"]) for k in ("median", "min", "max"))
    return f"{_fmt(med, digits)} ({_fmt(lo, digits)} to {_fmt(hi, digits)})"


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def query_section(results: Path) -> str:
    summary = _read_csv(results / "query_summary.csv")
    runs = _read_csv(results / "query_runs.csv")
    rows_of = {r["query"]: r["rows"] for r in runs if r["rep"] == "1"}
    body = []
    for r in summary:
        body.append(
            [
                r["query"],
                rows_of[r["query"]],
                _fmt(_num(r["bytes_processed_median"])),
                _fmt(_num(r["bytes_billed_median"]) / MIB, 0) + " MiB",
                _span(r, "slot_ms", 0),
                _span(r, "server_s", 3),
                _span(r, "wall_s", 2),
                r["runs_per_free_tib"],
            ]
        )
    head = [
        "query",
        "rows returned",
        "bytes processed",
        "bytes billed",
        "slot-ms, median (min to max)",
        "job seconds, median (min to max)",
        "wall seconds, median (min to max)",
        "runs per free TiB",
    ]
    return table(head, body)


def pipeline_section(results: Path) -> str:
    rows = _read_csv(results / "pipeline_summary.csv")
    body = [
        [
            r["stage"],
            r["reps"],
            r["failed"],
            _span(r, "seconds", 1),
        ]
        for r in rows
    ]
    return table(["stage", "runs", "failed", "seconds, median (min to max)"], body)


def dataform_section(results: Path) -> str:
    rows = _read_csv(results / "dataform_actions.csv")
    reps = sorted({r["rep"] for r in rows})
    lines = []
    for rep in reps:
        mine = [r for r in rows if r["rep"] == rep]
        total = sum(int(r["bytes_billed"]) for r in mine)
        biggest = max(mine, key=lambda r: int(r["bytes_billed"]))
        bad = sum(1 for r in mine if r["status"] != "ok")
        lines.append(
            f"- run {rep}: {len(mine)} actions, {bad} not ok, {total} bytes billed "
            f"({_fmt(total / MIB)} MiB), largest {biggest['action']} with "
            f"{_fmt(int(biggest['bytes_billed']) / MIB)} MiB"
        )
    return "\n".join(lines)


def facts_section(results: Path) -> str:
    facts = json.loads((results / "data_facts.json").read_text(encoding="utf-8"))
    j = facts["county_join"]
    lines = [
        table(
            ["table", "rows", "bytes"],
            [[t["table"], str(t["rows"]), str(t["bytes"])] for t in facts["tables"]],
        ),
        "",
        f"- schools: {j['schools']}, distinct ids: {j['distinct_school_ids']}",
        f"- matched to a county by the polygon join: {j['matched_to_a_county']}",
        f"- polygon county equal to the county NCES lists: {j['county_agrees_with_nces']}",
        f"- counties in wi_counties: {j['counties_total']}, "
        f"counties with at least one school: {j['counties_with_schools']}",
    ]
    ing = facts.get("ingest")
    if ing:
        lines += [
            f"- NCES file: {ing['rows_seen']} rows, {ing['rows_other_states']} in other states, "
            f"{ing['rows_kept']} kept, {ing['rows_rejected']} rejected",
            f"- Parquet: {ing['parquet_bytes']} bytes; object in GCS: "
            f"{ing['uploaded_size_bytes']} bytes, modified {ing['uploaded_mtime_ns']} ns",
        ]
    ok = sum(a["passes"] for a in facts["assertions"])
    lines.append(f"- assertion views with zero violating rows: {ok} of {len(facts['assertions'])}")
    return "\n".join(lines)


def build(results: Path) -> str:
    info = json.loads((results / "run_info.json").read_text(encoding="utf-8"))
    env, cost = info["environment"], info["cost_estimate"]
    m = env["machine"]
    out = [
        "# Measured results",
        "",
        f"Queries measured {env['date_utc']} (UTC) at commit {env['git_commit']}"
        f"{' (uncommitted changes present)' if env['git_dirty'] else ''}.",
        f"Client: {m['os']}, {m['cpu']}, {m['logical_cpus']} logical CPUs, {m['memory_gib']} GiB, "
        f"Python {m['python']}, {env['client']}. The client ran outside Google Cloud.",
        f"BigQuery location {env['bigquery_location']}, query cache {env['query_cache']}, "
        f"{env['reps_per_query']} runs per query.",
        "",
        "## Queries",
        "",
        query_section(results),
        "",
        f"The cache was off for every run. {cost['runs']} runs billed {cost['bytes_billed_total']} "
        f"bytes in total ({cost['tib_billed']:.6f} TiB), about "
        f"{cost['usd_at_list_price']} USD at the list price of {cost['usd_per_tib_list_price']} "
        "USD per TiB before the free tier.",
    ]
    for name, stab in info.get("ai_label_stability", {}).items():
        out += [
            "",
            f"{name}: model {env['ai_endpoint']}, {stab['schools']} schools classified per run, "
            f"{stab['same_label_in_every_rep']} of them got the same label in all "
            f"{stab['repetitions']} runs.",
        ]
    if (results / "pipeline_summary.csv").exists():
        pinfo = json.loads((results / "pipeline_info.json").read_text(encoding="utf-8"))
        out += [
            "",
            "## Pipeline stages",
            "",
            f"Measured {pinfo['date_utc']} (UTC), {pinfo['reps_per_stage']} runs each.",
            "",
            pipeline_section(results),
        ]
        if (results / "dataform_actions.csv").exists():
            out += [
                "",
                "Dataform runs timed above, from their logs:",
                "",
                dataform_section(results),
            ]
    if (results / "data_facts.json").exists():
        out += ["", "## Data facts", "", facts_section(results)]
    return "\n".join(out) + "\n"
