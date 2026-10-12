import json
import re

import pytest

from scripts import queries
from scripts.config import QUERIES_DIR, ConfigError, Stack

STACK = Stack(
    project_id="demo-project-1",
    location="US",
    bucket="demo-bucket",
    raw_dataset="raw_ds",
    warehouse_dataset="wh_ds",
    assertions_dataset="assert_ds",
    ai_connection="demo-project-1.US.conn",
)
KNOWN_PLACEHOLDERS = set(queries.template_values(STACK))
SPECS = queries.load_manifest()


def code_of(sql: str) -> str:
    return re.sub(r"--.*", "", sql)


def test_manifest_names_are_unique_and_files_exist():
    names = [s.name for s in SPECS]
    assert len(names) == len(set(names))
    on_disk = {p.name for p in QUERIES_DIR.glob("*.sql")}
    assert {s.file for s in SPECS} == on_disk


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_placeholders_and_parameters_line_up(spec):
    code = code_of(spec.path.read_text(encoding="utf-8"))
    assert set(re.findall(r"\{\{\s*(\w+)\s*\}\}", code)) <= KNOWN_PLACEHOLDERS
    assert set(re.findall(r"(?<![\w@])@(\w+)", code)) == set(spec.params)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_ai_flag_matches_the_sql(spec):
    code = code_of(spec.path.read_text(encoding="utf-8"))
    assert spec.ai == ("AI.CLASSIFY" in code)


def test_rendered_sql_has_no_placeholders_left():
    for spec in SPECS:
        sql = queries.rendered_sql(spec, STACK)
        assert "{{" not in sql
        assert "demo-project-1.wh_ds.wi_county_schools" in sql or "wi_counties" in sql


def test_the_set_covers_what_the_project_promises():
    code = {s.name: code_of(s.path.read_text(encoding="utf-8")) for s in SPECS}
    pipe = [n for n, c in code.items() if "|>" in c]
    assert len(pipe) >= 5
    assert any("ST_DISTANCE" in c for c in code.values())
    assert any("ST_DWITHIN" in c for c in code.values())
    assert any("|>" not in c for c in code.values()), "keep one standard-SQL query to compare"


def test_ai_query_pins_model_and_connection():
    ai = [s for s in SPECS if s.ai]
    assert len(ai) == 1
    sql = queries.rendered_sql(ai[0], STACK, endpoint="gemini-test-model")
    assert "endpoint => 'gemini-test-model'" in sql
    assert "connection_id => 'demo-project-1.US.conn'" in sql


def test_render_rejects_unknown_placeholder():
    with pytest.raises(ConfigError, match="nope"):
        queries.render("select {{ nope }}", {"project": "p"})
    assert queries.render("select '{{project}}' , '{{ project }}'", {"project": "p"}) == (
        "select 'p' , 'p'"
    )


def test_select_filters_names_and_ai():
    default = queries.select(SPECS, None, include_ai=False)
    assert default and not any(s.ai for s in default)
    assert any(s.ai for s in queries.select(SPECS, None, include_ai=True))
    one = queries.select(SPECS, ["schools_per_county"], include_ai=False)
    assert [s.name for s in one] == ["schools_per_county"]
    with pytest.raises(ConfigError, match="no_such_query"):
        queries.select(SPECS, ["no_such_query"], include_ai=False)


def test_job_config_carries_parameters_and_flags():
    spec = next(s for s in SPECS if s.name == "nearest_schools")
    cfg = queries.job_config(spec, use_cache=False, dry_run=True)
    got = {p.name: (p.type_, p.value) for p in cfg.query_parameters}
    assert got["limit"] == ("INT64", 10)
    assert got["lat"][0] == "FLOAT64"
    assert cfg.use_query_cache is False
    assert cfg.dry_run is True


def test_manifest_with_unsupported_parameter_type_is_refused(tmp_path):
    bad = tmp_path / "manifest.json"
    bad.write_text(
        json.dumps([{"name": "q", "file": "q.sql", "title": "t", "params": {"x": ["BYTES", "a"]}}]),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="BYTES"):
        queries.load_manifest(bad)
