import csv
import json
from types import SimpleNamespace

from scripts import bench, facts, summary
from scripts.config import Stack
from scripts.queries import RunStats

STACK = Stack("p-12345", "US", "b", "raw", "wh", "asrt", "p-12345.US.c")


def test_ingest_facts_drops_paths_and_the_bucket_name():
    got = facts.ingest_facts(
        {
            "source_url": "https://x.test/f.zip",
            "zip_sha256": "ab" * 32,
            "rows_seen": 10,
            "rows_other_states": 8,
            "rows_kept": 2,
            "rows_rejected": 0,
            "parquet_path": r"C:\Users\someone\repo\data\wi_schools.parquet",
            "parquet_bytes": 99,
            "uploaded": {"path": "my-bucket/schools/wi_schools.parquet", "size": 99, "mtime_ns": 5},
        }
    )
    assert got["uploaded_object"] == "schools/wi_schools.parquet"
    assert got["uploaded_size_bytes"] == 99
    text = json.dumps(got)
    assert "my-bucket" not in text and "someone" not in text
    assert facts.ingest_facts(None) is None


class FakeClient:
    def __init__(self, counts):
        self.counts = counts
        self.queries = []

    def list_tables(self, dataset):
        return [SimpleNamespace(table_id=name) for name in self.counts]

    def query(self, sql):
        self.queries.append(sql)
        name = sql.split("`")[1].rsplit(".", 1)[1]
        return SimpleNamespace(result=lambda: [{"n": self.counts[name]}])


def test_assertion_results_flag_views_that_return_rows():
    client = FakeClient({"b_assert": 3, "a_assert": 0})
    results = facts.assertion_results(client, STACK)
    assert results == [
        {"assertion": "a_assert", "violating_rows": 0, "passes": True},
        {"assertion": "b_assert", "violating_rows": 3, "passes": False},
    ]
    assert all("p-12345.asrt." in q for q in client.queries)


def write_results_dir(path, with_extras=True):
    runs = [
        RunStats("q1", i, 1.0 + i / 10, 0.5, 100, 10 * 2**20, 7 + i, False, 72, f"j{i}")
        for i in range(1, 4)
    ]
    env = {
        "date_utc": "2026-10-12T20:00:00+00:00",
        "git_commit": "abc123",
        "git_dirty": False,
        "bigquery_location": "US",
        "reps_per_query": 3,
        "query_cache": "disabled",
        "ai_endpoint": "model-x",
        "client": "google-cloud-bigquery 1.0",
        "machine": {
            "os": "TestOS",
            "cpu": "Some CPU",
            "logical_cpus": 8,
            "memory_gib": 16.0,
            "python": "3.13.5",
        },
    }
    bench.write_results(
        path, bench.BenchResult(runs, {}), [{"table": "t", "rows": 1, "bytes": 2}], env, None
    )
    if with_extras:
        with open(path / "pipeline_summary.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["stage", "reps", "failed", "seconds_median", "seconds_min", "seconds_max"])
            w.writerow(["ingest", 3, 0, 12.5, 11.0, 14.3])
        (path / "pipeline_info.json").write_text(
            json.dumps({"date_utc": "2026-10-12T21:00:00+00:00", "reps_per_stage": 3}),
            encoding="utf-8",
        )
        (path / "data_facts.json").write_text(
            json.dumps(
                {
                    "tables": [{"table": "raw.schools", "rows": 5, "bytes": 9}],
                    "county_join": {
                        "schools": 5,
                        "distinct_school_ids": 5,
                        "matched_to_a_county": 5,
                        "county_agrees_with_nces": 4,
                        "counties_with_schools": 2,
                        "counties_total": 72,
                    },
                    "assertions": [
                        {"assertion": "a", "violating_rows": 0, "passes": True},
                        {"assertion": "b", "violating_rows": 2, "passes": False},
                    ],
                    "ingest": None,
                }
            ),
            encoding="utf-8",
        )


def test_summary_quotes_the_files_it_was_given(tmp_path):
    write_results_dir(tmp_path)
    text = summary.build(tmp_path)
    assert "at commit abc123." in text
    assert "| q1 | 72 | 100 | 10 MiB |" in text
    assert "1.20 (1.10 to 1.30)" in text  # wall seconds: median and range of 1.1, 1.2, 1.3
    assert "12.5 (11.0 to 14.3)" in text
    assert "matched to a county by the polygon join: 5" in text
    assert "assertion views with zero violating rows: 1 of 2" in text
    assert "104857" in text  # runs per free TiB at 10 MiB per run


def test_summary_without_the_optional_files_still_builds(tmp_path):
    write_results_dir(tmp_path, with_extras=False)
    text = summary.build(tmp_path)
    assert "## Pipeline stages" not in text
    assert "## Data facts" not in text


def test_summary_reads_dataform_bytes_per_run(tmp_path):
    write_results_dir(tmp_path)
    with open(tmp_path / "dataform_actions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["rep", "action", "status", "bytes_billed"])
        w.writerow([1, "wh.big", "ok", 183 * 2**20])
        w.writerow([1, "chk.a", "ok", 10 * 2**20])
        w.writerow([1, "chk.b", "failed", 0])
    text = summary.build(tmp_path)
    assert "run 1: 3 actions, 1 not ok, 202375168 bytes billed (193 MiB), largest wh.big" in text
