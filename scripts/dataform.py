import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ingest.gcs import OBJECT_NAME

from .config import DATAFORM_CLI, DATAFORM_DIR, REPO, STATE_DIR, ConfigError, Stack


def project_vars(stack: Stack) -> dict[str, str]:
    return {
        "raw_dataset": stack.raw_dataset,
        "raw_bucket": stack.bucket,
        "schools_object": OBJECT_NAME,
    }


def command(action: str, stack: Stack | None, *, extra: list[str] | None = None) -> list[str]:
    """argv for `dataform compile` or `dataform run`; with a stack its names are injected.

    Without a stack the project compiles with the placeholders from workflow_settings.yaml,
    which is enough to look at the graph.
    """
    if action not in ("compile", "run"):
        raise ValueError(f"unsupported dataform action {action!r}")
    if action == "run" and stack is None:
        raise ValueError("a run needs the terraform stack")
    npx = shutil.which("npx")
    if not npx:
        raise ConfigError("npx not found; install Node.js 18 or newer")
    argv = [npx, "--yes", DATAFORM_CLI, action, str(DATAFORM_DIR)]
    if stack is not None:
        vars_arg = ",".join(f"{k}={v}" for k, v in project_vars(stack).items())
        argv += [
            "--default-database", stack.project_id,
            "--default-location", stack.location,
            "--assertion-schema", stack.assertions_dataset,
            "--default-schema", stack.warehouse_dataset,
            f"--vars={vars_arg}",
        ]  # fmt: skip
    if action == "run":
        argv += ["--credentials", str(credentials_file(stack))]
    return argv + (extra or [])


def credentials_file(stack: Stack) -> Path:
    """The CLI wants a credentials file; with no key in it, it falls back to ADC."""
    STATE_DIR.mkdir(exist_ok=True)
    path = STATE_DIR / "df-credentials.json"
    path.write_text(
        json.dumps({"projectId": stack.project_id, "location": stack.location}) + "\n",
        encoding="utf-8",
    )
    return path


def run(action: str, stack: Stack, *, extra: list[str] | None = None) -> None:
    env = {**os.environ, "GOOGLE_CLOUD_QUOTA_PROJECT": stack.project_id}
    subprocess.run(command(action, stack, extra=extra), cwd=REPO, env=env, check=True)


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ACTION = re.compile(
    r"^(Table created|Operation completed successfully|Assertion passed|Assertion failed)"
    r":\s+(\S+)"
)
_UNITS = {"B": 1, "KiB": 2**10, "MiB": 2**20, "GiB": 2**30, "TiB": 2**40}


def _to_bytes(text: str) -> int:
    total = 0
    for amount, unit in re.findall(r"([\d.]+) (B|KiB|MiB|GiB|TiB)", text):
        total += round(float(amount) * _UNITS[unit])
    return total


def parse_run_log(text: str) -> list[dict]:
    """Actions from the output of `dataform run`: name, status and bytes billed.

    The CLI prints sizes rounded to two decimals and lists several jobs per assertion,
    so the byte counts here are sums of those printed figures.
    """
    actions = []
    for line in _ANSI.sub("", text).splitlines():
        m = _ACTION.match(line.strip())
        if m:
            status = "failed" if m.group(1) == "Assertion failed" else "ok"
            actions.append({"action": m.group(2), "status": status, "bytes_billed": 0})
        elif "Bytes billed:" in line and actions:
            actions[-1]["bytes_billed"] = _to_bytes(line.split("Bytes billed:")[1])
    return actions
