import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .config import (
    OUTPUTS_FILE,
    REPO,
    STATE_DIR,
    TERRAFORM_DIR,
    TERRAFORM_IMAGE,
    ConfigError,
    Settings,
    Stack,
)


def adc_path(environ: Mapping[str, str], platform: str = sys.platform) -> Path:
    explicit = environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if explicit:
        return Path(explicit)
    if platform == "win32":
        return Path(environ.get("APPDATA", "")) / "gcloud" / "application_default_credentials.json"
    return (
        Path(environ.get("HOME", "~"))
        / ".config"
        / "gcloud"
        / "application_default_credentials.json"
    )


def variable_args(settings: Settings) -> list[str]:
    args = [f"-var=project_id={settings.project_id}", f"-var=location={settings.location}"]
    if settings.bucket:
        args.append(f"-var=bucket_name={settings.bucket}")
    return args


def command(
    args: list[str],
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    tf_dir: Path = TERRAFORM_DIR,
) -> list[str]:
    """Full argv for running terraform: a local binary if there is one, else the Docker image."""
    environ = os.environ if environ is None else environ
    binary = settings.terraform_bin or which("terraform")
    if binary:
        return [binary, *args]
    if not which("docker"):
        raise ConfigError("terraform is not on PATH and docker is not available either")
    adc = adc_path(environ)
    if not adc.exists():
        raise ConfigError(
            f"no application default credentials at {adc}; "
            "run gcloud auth application-default login"
        )
    return [
        "docker", "run", "--rm", "-i",
        "-v", f"{tf_dir}:/work",
        "-w", "/work",
        "-v", f"{adc}:/run/adc.json:ro",
        "-e", "GOOGLE_APPLICATION_CREDENTIALS=/run/adc.json",
        "-e", f"GOOGLE_CLOUD_QUOTA_PROJECT={settings.project_id}",
        "-e", "TF_IN_AUTOMATION=1",
        TERRAFORM_IMAGE,
        *args,
    ]  # fmt: skip


def run(
    args: list[str], settings: Settings, *, capture: bool = False
) -> subprocess.CompletedProcess:
    argv = command(args, settings)
    env = {**os.environ, "GOOGLE_CLOUD_QUOTA_PROJECT": settings.project_id, "TF_IN_AUTOMATION": "1"}
    return subprocess.run(
        argv, cwd=TERRAFORM_DIR, env=env, check=True, text=True, capture_output=capture
    )


def apply(settings: Settings) -> Stack:
    run(["init", "-input=false"], settings)
    run(["apply", "-input=false", "-auto-approve", *variable_args(settings)], settings)
    return refresh_outputs(settings)


def destroy(settings: Settings) -> None:
    run(["init", "-input=false"], settings)
    run(["destroy", "-input=false", "-auto-approve", *variable_args(settings)], settings)
    OUTPUTS_FILE.unlink(missing_ok=True)


def refresh_outputs(settings: Settings) -> Stack:
    text = run(["output", "-json"], settings, capture=True).stdout
    stack = Stack.from_terraform_json(text)
    STATE_DIR.mkdir(exist_ok=True)
    OUTPUTS_FILE.write_text(text, encoding="utf-8")
    return stack


def load_stack(settings: Settings) -> Stack:
    """Names from the last apply; asks terraform if the cache is missing."""
    if OUTPUTS_FILE.exists():
        stack = Stack.from_terraform_json(OUTPUTS_FILE.read_text(encoding="utf-8"))
        if stack.project_id == settings.project_id:
            return stack
    if not (TERRAFORM_DIR / "terraform.tfstate").exists():
        raise ConfigError(
            f"no terraform state in {TERRAFORM_DIR.relative_to(REPO)}; run apply first"
        )
    return refresh_outputs(settings)
