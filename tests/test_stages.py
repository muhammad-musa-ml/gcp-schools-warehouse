import types

import pytest

from scripts import dataform, machine, stages

DATAFORM_LOG = (
    "Compiling...\n\n\x1b[32mCompiled successfully.\n\x1b[0m\nRunning...\n\n"
    "\x1b[32mTable created: \x1b[0m \x1b[36mschools_warehouse.wi_counties\x1b[0m [table] \n"
    " \t jobId: dataform-1,\n \t Bytes billed: 183.00 MiB\n"
    "\x1b[32mOperation completed successfully: \x1b[0m \x1b[36mschools_raw.schools\x1b[0m \n"
    " \t jobId: dataform-2,\n \t Bytes billed: 0 B\n"
    "\x1b[32mAssertion passed: \x1b[0m \x1b[36mschools_assertions.assert_row_counts\x1b[0m \n"
    " \t jobId: dataform-3, dataform-4,\n \t Bytes billed: 0 B, 10.00 MiB\n"
    "\x1b[91mAssertion failed: \x1b[0m \x1b[36mschools_assertions.assert_schools_keys\x1b[0m \n"
    " \t jobId: dataform-5,\n \t Bytes billed: 10.00 MiB\n"
)


def test_parse_run_log_reads_actions_status_and_bytes():
    assert dataform.parse_run_log(DATAFORM_LOG) == [
        {"action": "schools_warehouse.wi_counties", "status": "ok", "bytes_billed": 183 * 2**20},
        {"action": "schools_raw.schools", "status": "ok", "bytes_billed": 0},
        {
            "action": "schools_assertions.assert_row_counts",
            "status": "ok",
            "bytes_billed": 10 * 2**20,
        },
        {
            "action": "schools_assertions.assert_schools_keys",
            "status": "failed",
            "bytes_billed": 10 * 2**20,
        },
    ]


def test_parse_run_log_of_a_crash_is_empty():
    assert dataform.parse_run_log("Error: boom\n") == []


class FakeRunner:
    def __init__(self, codes=None):
        self.calls = []
        self.codes = codes or {}

    def __call__(self, argv, stdout, stderr):
        self.calls.append(argv)
        stdout.write("some output\n")
        code = self.codes.get(len(self.calls), 0)
        return types.SimpleNamespace(returncode=code)


def make_clock(step=2.0):
    state = {"t": 0.0}

    def clock():
        state["t"] += step
        return state["t"]

    return clock


def test_run_stage_times_the_process_and_keeps_its_output(tmp_path):
    runner = FakeRunner()
    run = stages.run_stage(
        "ingest", 2, python="py", runner=runner, clock=make_clock(), log_dir=tmp_path
    )
    assert runner.calls == [["py", "-m", "scripts", "ingest", "--refresh"]]
    assert (run.stage, run.rep, run.seconds, run.exit_code) == ("ingest", 2, 2.0, 0)
    assert (tmp_path / "ingest-2.log").read_text(encoding="utf-8") == "some output\n"


def test_the_all_stage_starts_without_the_cached_download(monkeypatch, tmp_path):
    monkeypatch.setattr(stages, "DATA_DIR", tmp_path)
    zip_path = stages.pipeline.cached_zip(tmp_path, stages.SCHOOL_YEAR_CODE)
    zip_path.write_bytes(b"x")
    stages.run_stage("ingest", 1, runner=FakeRunner(), log_dir=tmp_path / "logs")
    assert zip_path.exists()
    stages.run_stage("all", 1, runner=FakeRunner(), log_dir=tmp_path / "logs")
    assert not zip_path.exists()


def test_run_all_goes_repetition_by_repetition(tmp_path):
    runs = stages.run_all(
        2, ["ingest", "transform"], log=lambda *_: None, runner=FakeRunner(), log_dir=tmp_path
    )
    assert [(r.rep, r.stage) for r in runs] == [
        (1, "ingest"),
        (1, "transform"),
        (2, "ingest"),
        (2, "transform"),
    ]


def test_unknown_stage_is_refused():
    with pytest.raises(ValueError, match="deploy"):
        stages.run_all(1, ["deploy"])


def test_failures_are_counted_and_left_out_of_the_timings():
    runs = [
        stages.StageRun("ingest", 1, 10.0, 0),
        stages.StageRun("ingest", 2, 99.0, 1),
        stages.StageRun("ingest", 3, 14.0, 0),
        stages.StageRun("all", 1, 5.0, 3),
    ]
    by_stage = {r["stage"]: r for r in stages.summarize(runs)}
    assert by_stage["ingest"] == {
        "stage": "ingest",
        "reps": 3,
        "failed": 1,
        "seconds_median": 12.0,
        "seconds_min": 10.0,
        "seconds_max": 14.0,
    }
    assert by_stage["all"]["failed"] == 1
    assert by_stage["all"]["seconds_median"] is None


def test_dataform_actions_come_from_the_transform_logs(tmp_path):
    (tmp_path / "transform-1.log").write_text(DATAFORM_LOG, encoding="utf-8")
    runs = [stages.StageRun("transform", 1, 30.0, 0), stages.StageRun("ingest", 1, 9.0, 0)]
    rows = stages.dataform_actions(runs, log_dir=tmp_path)
    assert len(rows) == 4
    assert {r["rep"] for r in rows} == {1}


def test_write_results_makes_the_files(tmp_path):
    runs = [stages.StageRun("ingest", 1, 10.0, 0)]
    stages.write_results(tmp_path / "r", runs, [], {"reps_per_stage": 1})
    assert (tmp_path / "r" / "pipeline_runs.csv").read_text(encoding="utf-8").splitlines() == [
        "stage,rep,seconds,exit_code",
        "ingest,1,10.0,0",
    ]
    assert (tmp_path / "r" / "pipeline_summary.csv").exists()
    assert not (tmp_path / "r" / "dataform_actions.csv").exists()


def test_machine_parsers(monkeypatch):
    monkeypatch.setattr(machine, "cpu_model", lambda: "Some CPU")
    monkeypatch.setattr(machine, "memory_gib", lambda: 16.0)
    cpuinfo = "processor\t: 0\nmodel name\t: Some CPU @ 3.00GHz\ncpu MHz\t: 3000\n"
    assert machine.parse_cpuinfo(cpuinfo) == "Some CPU @ 3.00GHz"
    assert machine.parse_cpuinfo("nothing here") is None
    assert machine.parse_meminfo_gib("MemTotal:       16777216 kB\n") == 16.0
    assert machine.parse_meminfo_gib("") is None
    assert {"os", "cpu", "logical_cpus", "memory_gib", "python"} <= set(machine.describe())
