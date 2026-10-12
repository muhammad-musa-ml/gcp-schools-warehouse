import json

import pytest

from scripts import config
from scripts.config import ConfigError, Stack


def test_parse_env_file_skips_comments_and_strips_quotes():
    text = """
# project
GCP_PROJECT_ID = my-project-123
GCP_LOCATION="EU"
SCHOOLS_BUCKET='bkt'
URL=https://x.test/?a=b
not a pair
"""
    assert config.parse_env_file(text) == {
        "GCP_PROJECT_ID": "my-project-123",
        "GCP_LOCATION": "EU",
        "SCHOOLS_BUCKET": "bkt",
        "URL": "https://x.test/?a=b",
    }


def test_settings_prefer_environment_over_file(tmp_path):
    f = tmp_path / ".env"
    f.write_text("GCP_PROJECT_ID=from-file-1\nGCP_LOCATION=EU\n", encoding="utf-8")
    s = config.load_settings({"GCP_PROJECT_ID": "from-env-22"}, f)
    assert s.project_id == "from-env-22"
    assert s.location == "EU"
    assert s.bucket is None


def test_settings_default_location_is_us(tmp_path):
    s = config.load_settings({"GCP_PROJECT_ID": "some-project-1"}, tmp_path / "missing.env")
    assert s.location == "US"


@pytest.mark.parametrize(
    "value", ["", "your-gcp-project-id", "Has_Caps", "x", "ends-with-dash-", "1starts-with-digit"]
)
def test_settings_reject_missing_or_malformed_project(tmp_path, value):
    with pytest.raises(ConfigError):
        config.load_settings({"GCP_PROJECT_ID": value}, tmp_path / "missing.env")


def test_settings_error_points_at_env_example(tmp_path):
    with pytest.raises(ConfigError, match=r"\.env\.example"):
        config.load_settings({}, tmp_path / "missing.env")


def outputs_json(**overrides):
    values = {
        "project_id": "p-12345",
        "location": "US",
        "bucket": "p-12345-schools-raw",
        "raw_dataset": "schools_raw",
        "warehouse_dataset": "schools_warehouse",
        "assertions_dataset": "schools_assertions",
        "ai_connection": "p-12345.US.schools-ai",
        "ai_connection_service_account": "sa@example.test",
    }
    values.update(overrides)
    return json.dumps(
        {k: {"value": v, "type": "string", "sensitive": False} for k, v in values.items()}
    )


def test_stack_reads_terraform_output_json():
    stack = Stack.from_terraform_json(outputs_json())
    assert stack.bucket == "p-12345-schools-raw"
    assert stack.ai_connection == "p-12345.US.schools-ai"


def test_stack_with_missing_output_says_to_apply():
    data = json.loads(outputs_json())
    del data["bucket"]
    with pytest.raises(ConfigError, match="bucket"):
        Stack.from_terraform_json(json.dumps(data))
