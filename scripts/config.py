import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

REPO = Path(__file__).resolve().parent.parent
TERRAFORM_DIR = REPO / "terraform"
DATAFORM_DIR = REPO / "dataform"
QUERIES_DIR = REPO / "queries"
RESULTS_DIR = REPO / "results"
DATA_DIR = REPO / "data"
STATE_DIR = REPO / ".state"
OUTPUTS_FILE = STATE_DIR / "outputs.json"

TERRAFORM_IMAGE = "hashicorp/terraform:1.16.5"
DATAFORM_CLI = "@dataform/cli@3.0.71"
SCHOOL_YEAR_CODE = "2425"

# AI.CLASSIFY picks a model itself when no endpoint is given, which makes runs hard to repeat.
AI_ENDPOINT = "gemini-3.5-flash-lite"

# On-demand analysis price per TiB in the US multi-region; the first TiB each month is free.
BQ_USD_PER_TIB = 6.25

ENV_KEYS = ("GCP_PROJECT_ID", "GCP_LOCATION", "SCHOOLS_BUCKET", "TERRAFORM_BIN")
PLACEHOLDER_PROJECT = "your-gcp-project-id"
_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    project_id: str
    location: str = "US"
    bucket: str | None = None
    terraform_bin: str | None = None


def parse_env_file(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_settings(
    environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> Settings:
    """Values come from the environment first, then from .env."""
    environ = os.environ if environ is None else environ
    env_file = REPO / ".env" if env_file is None else env_file
    values = parse_env_file(env_file.read_text(encoding="utf-8")) if env_file.exists() else {}
    values.update({k: environ[k] for k in ENV_KEYS if environ.get(k)})

    project = values.get("GCP_PROJECT_ID", "")
    if not project or project == PLACEHOLDER_PROJECT:
        raise ConfigError("GCP_PROJECT_ID is not set. Copy .env.example to .env and fill it in.")
    if not _PROJECT_ID.fullmatch(project):
        raise ConfigError(f"GCP_PROJECT_ID {project!r} does not look like a project id")
    return Settings(
        project_id=project,
        location=values.get("GCP_LOCATION") or "US",
        bucket=values.get("SCHOOLS_BUCKET") or None,
        terraform_bin=values.get("TERRAFORM_BIN") or None,
    )


@dataclass(frozen=True)
class Stack:
    """What terraform built; every other step reads names from here."""

    project_id: str
    location: str
    bucket: str
    raw_dataset: str
    warehouse_dataset: str
    assertions_dataset: str
    ai_connection: str

    @classmethod
    def from_terraform_json(cls, text: str) -> Self:
        outputs = json.loads(text)
        try:
            return cls(
                project_id=outputs["project_id"]["value"],
                location=outputs["location"]["value"],
                bucket=outputs["bucket"]["value"],
                raw_dataset=outputs["raw_dataset"]["value"],
                warehouse_dataset=outputs["warehouse_dataset"]["value"],
                assertions_dataset=outputs["assertions_dataset"]["value"],
                ai_connection=outputs["ai_connection"]["value"],
            )
        except KeyError as e:
            raise ConfigError(f"terraform outputs are missing {e}; has apply been run?") from None
