import io
import json
import os
import subprocess

import pytest

from scripts import cli
from scripts.config import ConfigError, Settings, Stack

STACK = Stack("p-12345", "US", "b", "raw", "wh", "asrt", "p-12345.US.c")


@pytest.fixture(autouse=True)
def restore_quota_project(monkeypatch):
    # main() sets this variable; setting it here first makes monkeypatch undo whatever main does
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "set-by-the-test-fixture")


@pytest.fixture(autouse=True)
def keep_real_ingest_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.facts, "INGEST_SUMMARY", tmp_path / "ingest_summary.json")


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(cli, "load_settings", lambda: Settings(project_id="p-12345"))
    monkeypatch.setattr(cli.terraform, "load_stack", lambda settings: STACK)


def test_parser_reads_query_options():
    args = cli.build_parser().parse_args(
        ["queries", "--name", "a", "b", "--include-ai", "--dry-run", "--rows", "3"]
    )
    assert (args.command, args.name, args.include_ai, args.dry_run, args.rows) == (
        "queries",
        ["a", "b"],
        True,
        True,
        3,
    )
    assert args.endpoint == "gemini-3.5-flash-lite"


def test_parser_bench_defaults_to_five_reps_and_results_dir():
    args = cli.build_parser().parse_args(["bench"])
    assert args.reps == 5
    assert args.out == cli.RESULTS_DIR
    assert args.include_ai is False


def test_parser_refuses_unknown_and_missing_commands(capsys):
    for argv in ([], ["deploy"], ["bench", "--reps", "many"]):
        with pytest.raises(SystemExit) as e:
            cli.build_parser().parse_args(argv)
        assert e.value.code == 2
    capsys.readouterr()


def test_missing_project_is_reported_not_raised(monkeypatch, capsys):
    def missing():
        raise ConfigError("GCP_PROJECT_ID is not set. Copy .env.example to .env and fill it in.")

    monkeypatch.setattr(cli, "load_settings", missing)
    assert cli.main(["status"]) == 2
    assert "GCP_PROJECT_ID is not set" in capsys.readouterr().err


def test_bench_rejects_zero_reps(configured, capsys):
    assert cli.main(["bench", "--reps", "0"]) == 2
    assert "--reps" in capsys.readouterr().err


def test_unknown_query_name_is_reported(configured, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_client", lambda stack: None)
    assert cli.main(["queries", "--name", "nope", "--dry-run"]) == 2
    assert "unknown query nope" in capsys.readouterr().err


def test_failed_subprocess_gives_exit_code_one(configured, monkeypatch, capsys):
    def boom(action, stack, extra=None):
        raise subprocess.CalledProcessError(3, ["npx", "--yes", "dataform", "run"])

    monkeypatch.setattr(cli.dataform, "run", boom)
    assert cli.main(["transform"]) == 1
    assert "exited with 3" in capsys.readouterr().err


def test_transform_passes_actions_through(configured, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cli.dataform,
        "run",
        lambda action, stack, extra=None: seen.update(action=action, extra=extra),
    )
    assert cli.main(["transform", "--actions", "wi_counties", "schools"]) == 0
    assert seen == {"action": "run", "extra": ["--actions", "wi_counties", "schools"]}
    assert cli.main(["transform", "--compile-only"]) == 0
    assert seen["action"] == "compile"


def test_local_ingest_needs_no_project(monkeypatch, capsys):
    def no_settings():
        raise ConfigError("should not be asked")

    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return cli.pipeline.IngestSummary("url", "a" * 64, 10, 8, 2, 0, "x.parquet", 5, None)

    monkeypatch.setattr(cli, "load_settings", no_settings)
    monkeypatch.setattr(cli.pipeline, "run", fake_run)
    assert cli.main(["ingest", "--no-upload"]) == 0
    assert seen["bucket"] is None
    assert seen["data_dir"] == cli.DATA_DIR
    assert "kept 2" in capsys.readouterr().out


def test_ingest_prints_what_gcs_reports(configured, monkeypatch, capsys):
    uploaded = cli.gcs.ObjectInfo("b/schools/wi_schools.parquet", 140913, 1791830246756000000)
    monkeypatch.setattr(
        cli.pipeline,
        "run",
        lambda **kw: cli.pipeline.IngestSummary("url", "a" * 64, 10, 8, 2, 0, "x", 5, uploaded),
    )
    assert cli.main(["ingest"]) == 0
    out = capsys.readouterr().out
    assert "size 140913 bytes" in out
    assert "modified 1791830246756000000 ns" in out


def test_teardown_asks_first_and_deletes_nothing_without_a_terminal(
    configured, monkeypatch, capsys
):
    def never(*a, **k):
        raise AssertionError("must not delete")

    monkeypatch.setattr(cli.gcs, "empty_bucket", never)
    monkeypatch.setattr(cli.terraform, "destroy", never)
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # not a tty
    assert cli.main(["teardown"]) == 2
    assert "--yes" in capsys.readouterr().err


def test_teardown_empties_the_bucket_before_destroying(configured, monkeypatch, capsys):
    order = []
    monkeypatch.setattr(cli.gcs, "gcs_filesystem", lambda: "fs")
    monkeypatch.setattr(
        cli.gcs, "empty_bucket", lambda fs, bucket: order.append(("empty", bucket)) or 4
    )
    monkeypatch.setattr(cli.terraform, "destroy", lambda settings: order.append(("destroy",)))
    assert cli.main(["teardown", "--yes"]) == 0
    assert order == [("empty", "b"), ("destroy",)]
    assert "deleted 4 objects" in capsys.readouterr().out


def test_quota_project_is_pointed_at_the_target_project(configured, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_QUOTA_PROJECT", "some-other-project")
    monkeypatch.setattr(cli.dataform, "run", lambda *a, **k: None)
    cli.main(["transform", "--compile-only"])
    assert os.environ["GOOGLE_CLOUD_QUOTA_PROJECT"] == "p-12345"


def test_stages_rejects_zero_reps_and_unknown_stage(configured, capsys):
    assert cli.main(["stages", "--reps", "0"]) == 2
    assert "--reps" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(["stages", "--only", "deploy"])
    assert e.value.code == 2
    capsys.readouterr()


def test_ingest_leaves_a_summary_for_the_facts_step(configured, monkeypatch):
    monkeypatch.setattr(
        cli.pipeline,
        "run",
        lambda **kw: cli.pipeline.IngestSummary("url", "a" * 64, 10, 8, 2, 0, "x", 5, None),
    )
    assert cli.main(["ingest"]) == 0
    saved = json.loads(cli.facts.INGEST_SUMMARY.read_text(encoding="utf-8"))
    assert saved["rows_kept"] == 2


def test_summary_command_needs_no_project(monkeypatch, tmp_path, capsys):
    def no_settings():
        raise ConfigError("should not be asked")

    monkeypatch.setattr(cli, "load_settings", no_settings)
    monkeypatch.setattr(cli.summary, "build", lambda results: "# text\n")
    assert cli.main(["summary", "--results", str(tmp_path)]) == 0
    assert (tmp_path / "summary.md").read_text(encoding="utf-8") == "# text\n"
