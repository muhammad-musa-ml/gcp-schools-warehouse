import csv
import json

from scripts import bench, queries, report
from scripts.config import Stack
from scripts.queries import RunStats

STACK = Stack("p-12345", "US", "b", "raw", "wh", "asrt", "p-12345.US.c")


def stat(query, rep, wall, slot, billed, hit=False):
    return RunStats(query, rep, wall, wall / 2, billed, billed, slot, hit, 3, f"job_{query}_{rep}")


RUNS = [
    stat("a", 1, 1.0, 100, 10 * 2**20),
    stat("a", 2, 3.0, 300, 10 * 2**20),
    stat("a", 3, 2.0, 200, 10 * 2**20),
    stat("b", 1, 0.5, 7, 2**30),
]


def test_summary_uses_median_min_max():
    rows = {r["query"]: r for r in bench.summarize(RUNS)}
    a = rows["a"]
    assert a["reps"] == 3
    assert (a["wall_s_median"], a["wall_s_min"], a["wall_s_max"]) == (2.0, 1.0, 3.0)
    assert a["slot_ms_median"] == 200
    assert a["cache_hits"] == 0
    assert a["runs_per_free_tib"] == 2**40 // (10 * 2**20)
    assert rows["b"]["runs_per_free_tib"] == 1024


def test_summary_counts_cache_hits_and_tolerates_missing_stats():
    runs = [stat("c", 1, 1.0, None, None, hit=True)]
    row = bench.summarize(runs)[0]
    assert row["cache_hits"] == 1
    assert row["bytes_billed_median"] is None
    assert row["runs_per_free_tib"] is None


def test_cost_estimate_is_bytes_times_list_price():
    est = bench.estimate_cost(RUNS)
    total = 3 * 10 * 2**20 + 2**30
    assert est["bytes_billed_total"] == total
    assert est["usd_at_list_price"] == round(total / 2**40 * 6.25, 4)
    assert est["runs"] == 4


def test_run_all_repeats_each_query_with_the_cache_off(monkeypatch):
    calls = []

    def fake_run(client, spec, stack, *, rep, use_cache, endpoint):
        calls.append((spec.name, rep, use_cache, endpoint))
        return [], stat(spec.name, rep, 0.1, 1, 1)

    monkeypatch.setattr(queries, "run", fake_run)
    specs = queries.select(queries.load_manifest(), ["schools_per_county", "school_density"], False)
    runs = bench.run_all(None, STACK, specs, reps=5, endpoint="m", log=lambda *_: None)
    assert len(runs) == 10
    assert {c[2] for c in calls} == {False}
    assert [c[1] for c in calls if c[0] == "school_density"] == [1, 2, 3, 4, 5]


def test_write_results_creates_the_csv_files(tmp_path):
    tables = [{"table": "raw.schools", "rows": 5, "bytes": 99}]
    env = {"reps_per_query": 3}
    bench.write_results(tmp_path / "out", RUNS, tables, env, {"query_jobs": 1})
    out = tmp_path / "out"
    with open(out / "query_runs.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    assert rows[0]["job_id"] == "job_a_1"
    assert list(rows[0]) == [
        "query", "rep", "wall_s", "server_s", "bytes_processed", "bytes_billed",
        "slot_ms", "cache_hit", "rows", "job_id",
    ]  # fmt: skip
    with open(out / "query_summary.csv", newline="", encoding="utf-8") as f:
        assert [r["query"] for r in csv.DictReader(f)] == ["a", "b"]
    info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
    assert info["cost_estimate"]["runs"] == 4
    assert info["environment"] == env
    assert (out / "table_rows.csv").exists()


def test_format_table_aligns_truncates_and_handles_empty():
    rows = [{"name": "Dane", "n": 169}, {"name": "Rock", "n": 62}, {"name": "Vilas", "n": None}]
    text = report.format_table(rows, limit=2)
    lines = text.splitlines()
    assert lines[0].split() == ["name", "n"]
    assert lines[2].startswith("Dane")
    assert lines[-1] == "... 1 more rows"
    assert report.format_table([]) == "(no rows)"


def test_markdown_includes_saved_query_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(report, "STATE_DIR", tmp_path)
    monkeypatch.setattr(report, "LAST_QUERIES", tmp_path / "last.json")
    report.save_query_run(
        "q1",
        "Title one",
        [{"x": 1}],
        {"bytes_billed": 10, "slot_ms": 5, "cache_hit": False},
    )
    text = report.markdown(
        STACK,
        [{"table": "raw.schools", "rows": 2, "bytes": 9}],
        {"window_days": 30, "query_jobs": 4, "bytes_billed": 2**20},
    )
    assert "### q1: Title one" in text
    assert "1.0 MiB" in text
    assert "raw.schools" in text
