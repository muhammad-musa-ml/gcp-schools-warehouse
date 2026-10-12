import csv
import json
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ingest import pipeline

from . import dataform, machine
from .config import DATA_DIR, SCHOOL_YEAR_CODE, STATE_DIR

# The CLI arguments of each stage. ingest re-downloads the file every time, which is the
# slow part of a first run; `all` also starts from a deleted download for the same reason.
STAGES = {
    "ingest": ["ingest", "--refresh"],
    "transform": ["transform"],
    "all": ["all"],
}
LOG_DIR = STATE_DIR / "stages"


@dataclass(frozen=True)
class StageRun:
    stage: str
    rep: int
    seconds: float
    exit_code: int


def run_stage(
    stage: str,
    rep: int,
    *,
    python: str = sys.executable,
    runner: Callable = subprocess.run,
    clock: Callable[[], float] = time.perf_counter,
    log_dir: Path = LOG_DIR,
) -> StageRun:
    log_dir.mkdir(parents=True, exist_ok=True)
    if stage == "all":
        pipeline.cached_zip(DATA_DIR, SCHOOL_YEAR_CODE).unlink(missing_ok=True)
    started = clock()
    with open(log_dir / f"{stage}-{rep}.log", "w", encoding="utf-8") as log:
        done = runner(
            [python, "-m", "scripts", *STAGES[stage]], stdout=log, stderr=subprocess.STDOUT
        )
    return StageRun(stage, rep, round(clock() - started, 3), done.returncode)


def run_all(reps: int, stages: list[str] | None = None, *, log=print, **kwargs) -> list[StageRun]:
    """Repetition by repetition, so a slow minute on the network hits every stage alike."""
    names = stages or list(STAGES)
    unknown = [s for s in names if s not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage {', '.join(unknown)}; known: {', '.join(STAGES)}")
    runs = []
    for rep in range(1, reps + 1):
        for stage in names:
            run = run_stage(stage, rep, **kwargs)
            runs.append(run)
            log(f"{stage} rep {rep}/{reps}: {run.seconds:.1f}s, exit {run.exit_code}")
    return runs


def summarize(runs: list[StageRun]) -> list[dict]:
    out = []
    for stage in dict.fromkeys(r.stage for r in runs):
        ok = [r.seconds for r in runs if r.stage == stage and r.exit_code == 0]
        failed = sum(1 for r in runs if r.stage == stage and r.exit_code != 0)
        out.append(
            {
                "stage": stage,
                "reps": len(ok) + failed,
                "failed": failed,
                "seconds_median": round(statistics.median(ok), 3) if ok else None,
                "seconds_min": min(ok) if ok else None,
                "seconds_max": max(ok) if ok else None,
            }
        )
    return out


def dataform_actions(runs: list[StageRun], log_dir: Path = LOG_DIR) -> list[dict]:
    """What each timed `transform` run did, read back from its log."""
    rows = []
    for run in runs:
        if run.stage != "transform":
            continue
        text = (log_dir / f"transform-{run.rep}.log").read_text(encoding="utf-8", errors="replace")
        for action in dataform.parse_run_log(text):
            rows.append({"rep": run.rep, **action})
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_results(out_dir: Path, runs: list[StageRun], actions: list[dict], env: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "pipeline_runs.csv", [asdict(r) for r in runs])
    _write_csv(out_dir / "pipeline_summary.csv", summarize(runs))
    if actions:
        _write_csv(out_dir / "dataform_actions.csv", actions)
    (out_dir / "pipeline_info.json").write_text(json.dumps(env, indent=2) + "\n", encoding="utf-8")


def describe_environment(reps: int, started_utc: str) -> dict:
    return {
        "date_utc": started_utc,
        "reps_per_stage": reps,
        "machine": machine.describe(),
        "stages": {name: "python -m scripts " + " ".join(args) for name, args in STAGES.items()},
        "note": (
            "Each stage runs as its own process, so interpreter, npx and terraform start-up "
            "are included. The npx and terraform provider caches were warm. The `all` stage "
            "starts with the NCES download deleted and runs terraform apply, ingest, dataform "
            "run, the six non-AI queries and the report."
        ),
    }
