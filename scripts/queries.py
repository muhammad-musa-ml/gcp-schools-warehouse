import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from .config import AI_ENDPOINT, QUERIES_DIR, ConfigError, Stack

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_PARAM_TYPES = {"INT64", "FLOAT64", "STRING", "BOOL"}


@dataclass(frozen=True)
class QuerySpec:
    name: str
    file: str
    title: str
    params: Mapping[str, tuple[str, Any]]
    ai: bool = False

    @property
    def path(self) -> Path:
        return QUERIES_DIR / self.file


@dataclass(frozen=True)
class RunStats:
    query: str
    rep: int
    wall_s: float
    server_s: float | None
    bytes_processed: int | None
    bytes_billed: int | None
    slot_ms: int | None
    cache_hit: bool
    rows: int
    job_id: str


def load_manifest(path: Path | None = None) -> list[QuerySpec]:
    path = QUERIES_DIR / "manifest.json" if path is None else path
    specs = []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        params = {}
        for name, (type_, value) in entry.get("params", {}).items():
            if type_ not in _PARAM_TYPES:
                raise ConfigError(f"{entry['name']}: parameter {name} has unsupported type {type_}")
            params[name] = (type_, value)
        specs.append(
            QuerySpec(
                name=entry["name"],
                file=entry["file"],
                title=entry["title"],
                params=params,
                ai=entry.get("ai", False),
            )
        )
    return specs


def select(specs: list[QuerySpec], names: list[str] | None, include_ai: bool) -> list[QuerySpec]:
    if names:
        known = {s.name: s for s in specs}
        missing = [n for n in names if n not in known]
        if missing:
            raise ConfigError(f"unknown query {', '.join(missing)}; known: {', '.join(known)}")
        return [known[n] for n in names]
    return [s for s in specs if include_ai or not s.ai]


def template_values(stack: Stack, endpoint: str = AI_ENDPOINT) -> dict[str, str]:
    return {
        "project": stack.project_id,
        "raw": stack.raw_dataset,
        "warehouse": stack.warehouse_dataset,
        "connection": stack.ai_connection,
        "endpoint": endpoint,
    }


def render(sql: str, values: Mapping[str, str]) -> str:
    def fill(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise ConfigError(f"unknown placeholder {{{{ {key} }}}} in query")
        return values[key]

    return _PLACEHOLDER.sub(fill, sql)


def job_config(
    spec: QuerySpec, *, use_cache: bool = True, dry_run: bool = False
) -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(name, type_, value)
            for name, (type_, value) in spec.params.items()
        ],
        use_query_cache=use_cache,
        dry_run=dry_run,
    )


def rendered_sql(spec: QuerySpec, stack: Stack, endpoint: str = AI_ENDPOINT) -> str:
    return render(spec.path.read_text(encoding="utf-8"), template_values(stack, endpoint))


def dry_run(
    client: bigquery.Client, spec: QuerySpec, stack: Stack, endpoint: str = AI_ENDPOINT
) -> int:
    job = client.query(
        rendered_sql(spec, stack, endpoint),
        job_config=job_config(spec, use_cache=False, dry_run=True),
    )
    return job.total_bytes_processed


def run(
    client: bigquery.Client,
    spec: QuerySpec,
    stack: Stack,
    *,
    rep: int = 1,
    use_cache: bool = True,
    endpoint: str = AI_ENDPOINT,
) -> tuple[list[dict], RunStats]:
    sql = rendered_sql(spec, stack, endpoint)
    started = time.perf_counter()
    job = client.query(sql, job_config=job_config(spec, use_cache=use_cache))
    rows = [dict(r) for r in job.result()]
    wall = time.perf_counter() - started
    server = (job.ended - job.started).total_seconds() if job.started and job.ended else None
    stats = RunStats(
        query=spec.name,
        rep=rep,
        wall_s=round(wall, 4),
        server_s=server,
        bytes_processed=job.total_bytes_processed,
        bytes_billed=job.total_bytes_billed,
        slot_ms=job.slot_millis,
        cache_hit=bool(job.cache_hit),
        rows=len(rows),
        job_id=job.job_id,
    )
    return rows, stats
