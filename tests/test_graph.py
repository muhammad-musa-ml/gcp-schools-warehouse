import pytest

from scripts import dataform, graph
from scripts.config import ConfigError


def target(schema, name):
    return {"database": "p", "schema": schema, "name": name}


COMPILED = {
    "declarations": [{"target": target("pub", "counties")}],
    "tables": [
        {"target": target("wh", "counties"), "dependencyTargets": [target("pub", "counties")]},
        {
            "target": target("wh", "joined"),
            "dependencyTargets": [target("raw", "schools"), target("wh", "counties")],
        },
    ],
    "operations": [{"target": target("raw", "schools")}],
    "assertions": [
        {"target": target("chk", "joined_ok"), "dependencyTargets": [target("wh", "joined")]}
    ],
}


def test_graph_lists_every_kind_of_action_with_sorted_dependencies():
    assert graph.dependency_graph(COMPILED) == {
        "chk.joined_ok": ["wh.joined"],
        "pub.counties": [],
        "raw.schools": [],
        "wh.counties": ["pub.counties"],
        "wh.joined": ["raw.schools", "wh.counties"],
    }


def test_same_name_in_two_datasets_stays_two_entries():
    g = graph.dependency_graph(COMPILED)
    assert "pub.counties" in g and "wh.counties" in g


def test_graph_of_an_empty_project_is_empty():
    assert graph.dependency_graph({}) == {}


def test_compile_without_a_stack_uses_the_placeholders(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx")
    argv = dataform.command("compile", None, extra=["--json"])
    assert argv[-1] == "--json"
    assert "--default-database" not in argv
    assert "--vars" not in " ".join(argv)


def test_a_run_without_a_stack_is_refused(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/npx")
    with pytest.raises(ValueError, match="stack"):
        dataform.command("run", None)


def test_missing_node_is_reported(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ConfigError, match="Node"):
        dataform.command("compile", None)
