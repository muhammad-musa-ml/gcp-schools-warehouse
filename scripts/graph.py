import json
import subprocess

from . import dataform
from .config import REPO, Stack

KINDS = ("declarations", "tables", "operations", "assertions")


def compile_json(stack: Stack | None = None) -> dict:
    out = subprocess.run(
        dataform.command("compile", stack, extra=["--json"]),
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)


def dependency_graph(compiled: dict) -> dict[str, list[str]]:
    """{dataset.action: [dataset.action it reads from]} for everything the project defines."""

    def name(target: dict) -> str:
        return f"{target['schema']}.{target['name']}"

    graph = {}
    for kind in KINDS:
        for action in compiled.get(kind, []):
            graph[name(action["target"])] = sorted(
                name(t) for t in action.get("dependencyTargets", [])
            )
    return dict(sorted(graph.items()))
