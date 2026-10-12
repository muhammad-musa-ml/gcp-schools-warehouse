import json
import os
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


def command(action: str, stack: Stack, *, extra: list[str] | None = None) -> list[str]:
    """argv for `dataform compile` or `dataform run` with this stack's names injected."""
    if action not in ("compile", "run"):
        raise ValueError(f"unsupported dataform action {action!r}")
    npx = shutil.which("npx")
    if not npx:
        raise ConfigError("npx not found; install Node.js 18 or newer")
    vars_arg = ",".join(f"{k}={v}" for k, v in project_vars(stack).items())
    argv = [
        npx, "--yes", DATAFORM_CLI, action, str(DATAFORM_DIR),
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
