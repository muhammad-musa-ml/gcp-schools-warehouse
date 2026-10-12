"""Static checks on the Terraform and Dataform files, the parts CI can see without credentials."""

import re
from pathlib import Path

import pytest

from scripts.config import DATAFORM_DIR, PLACEHOLDER_PROJECT, REPO, TERRAFORM_DIR

DEFS = DATAFORM_DIR / "definitions"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_terraform_project_id_has_no_default():
    block = re.search(
        r'variable "project_id" \{(.*?)\n\}', read(TERRAFORM_DIR / "variables.tf"), re.S
    )
    assert block and "default" not in block.group(1)


def test_every_terraform_output_the_scripts_read_exists():
    declared = set(re.findall(r'output "(\w+)"', read(TERRAFORM_DIR / "outputs.tf")))
    needed = {
        "project_id",
        "location",
        "bucket",
        "raw_dataset",
        "warehouse_dataset",
        "assertions_dataset",
        "ai_connection",
    }
    assert needed <= declared


def test_bucket_is_private():
    main = read(TERRAFORM_DIR / "main.tf")
    assert 'public_access_prevention    = "enforced"' in main
    assert "uniform_bucket_level_access = true" in main


def test_workflow_settings_use_the_same_placeholder_as_env_example():
    settings = read(DATAFORM_DIR / "workflow_settings.yaml")
    assert f"defaultProject: {PLACEHOLDER_PROJECT}" in settings
    assert f"GCP_PROJECT_ID={PLACEHOLDER_PROJECT}" in read(REPO / ".env.example")


def test_schools_load_is_an_operation_with_output():
    sqlx = read(DEFS / "schools.sqlx")
    assert 'type: "operations"' in sqlx
    assert "hasOutput: true" in sqlx
    assert "LOAD DATA OVERWRITE" in sqlx
    assert "dataform.projectConfig.vars.raw_bucket" in sqlx


def test_county_join_uses_refs_and_a_spatial_predicate():
    sqlx = read(DEFS / "wi_county_schools.sqlx")
    assert '${ref("schools")}' in sqlx
    assert '${ref("wi_counties")}' in sqlx
    assert "ST_GEOGPOINT" in sqlx
    assert "ST_CONTAINS" in sqlx
    assert "LEFT JOIN" in sqlx, "an inner join would hide schools that match no county"


def test_counties_come_from_the_public_boundaries_through_a_declaration():
    decl = read(DEFS / "sources" / "us_counties.sqlx")
    assert 'database: "bigquery-public-data"' in decl
    assert 'schema: "geo_us_boundaries"' in decl
    assert "state_fips_code = '55'" in read(DEFS / "wi_counties.sqlx")


@pytest.mark.parametrize(
    "name",
    ["assert_every_school_has_one_county", "assert_row_counts", "assert_schools_keys"],
)
def test_manual_assertions_exist(name):
    found = [p for p in (DEFS / "assertions").glob("*.sqlx") if f'name: "{name}"' in read(p)]
    assert len(found) == 1
    assert 'type: "assertion"' in read(found[0])


def test_built_in_assertions_cover_keys_on_both_tables():
    for table in ("wi_counties", "wi_county_schools"):
        sqlx = read(DEFS / f"{table}.sqlx")
        assert "uniqueKey" in sqlx and "nonNull" in sqlx
