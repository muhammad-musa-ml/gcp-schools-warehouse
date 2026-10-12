import json
from datetime import UTC, datetime
from pathlib import Path

from .config import STATE_DIR, Stack

LAST_QUERIES = STATE_DIR / "last_queries.json"


def format_table(rows: list[dict], limit: int = 10) -> str:
    if not rows:
        return "(no rows)"
    cols = list(rows[0])
    shown = rows[:limit]
    cells = [[_cell(r.get(c)) for c in cols] for r in shown]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(cols)]
    lines = [
        "  ".join(c.ljust(w) for c, w in zip(cols, widths, strict=True)).rstrip(),
        "  ".join("-" * w for w in widths),
    ]
    lines += [
        "  ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)).rstrip() for row in cells
    ]
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows")
    return "\n".join(lines)


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def save_query_run(name: str, title: str, rows: list[dict], stats: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    saved = json.loads(LAST_QUERIES.read_text(encoding="utf-8")) if LAST_QUERIES.exists() else {}
    saved[name] = {"title": title, "rows": rows[:50], "total_rows": len(rows), "stats": stats}
    LAST_QUERIES.write_text(json.dumps(saved, indent=2, default=str) + "\n", encoding="utf-8")


def markdown(stack: Stack, tables: list[dict], usage: dict) -> str:
    out = [
        "# Schools warehouse report",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} for {stack.project_id} "
        f"({stack.location}).",
        "",
        "## Tables",
        "",
        "```",
        format_table(tables, limit=50),
        "```",
    ]
    if LAST_QUERIES.exists():
        out += ["", "## Queries (last run)"]
        for name, item in json.loads(LAST_QUERIES.read_text(encoding="utf-8")).items():
            s = item["stats"]
            out += [
                "",
                f"### {name}: {item['title']}",
                "",
                f"{item['total_rows']} rows, {s['bytes_billed']} bytes billed, "
                f"{s['slot_ms']} slot-ms, cache hit: {s['cache_hit']}",
                "",
                "```",
                format_table(item["rows"], limit=10),
                "```",
            ]
    mib = usage["bytes_billed"] / 2**20
    out += [
        "",
        "## Usage",
        "",
        f"Query jobs in the last {usage['window_days']} days: {usage['query_jobs']}, "
        f"{usage['bytes_billed']} bytes billed ({mib:.1f} MiB).",
        "",
    ]
    return "\n".join(out)


def write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
