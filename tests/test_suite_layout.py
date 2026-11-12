"""Keep designated expensive scenarios out of the unmarked development loop."""

from __future__ import annotations

import ast
import tomllib

from test_template import ROOT

RUNTIME = {
    "test_dev_container_runtime",
    "test_agent_container_runtime",
    "test_agent_multi_project_runtime",
    "test_master_container_runtime",
}
INTEGRATION = {
    "test_custom_names",
    "test_default_execution",
    "test_provider_workflow",
    "test_init_and_idempotence",
    "test_init_inside_parent_repository",
    "test_init_missing_identity_and_resume",
    "test_demo_generation_and_explicit_cleanup",
    "test_setup_installs_git_hook",
    "test_cruft_create_check_diff",
    "test_cruft_legacy_context_upgrade",
    "test_cruft_codex_to_both_preserves_volume_name",
}


def marker(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call):
        node = node.func
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
        and node.value.attr == "mark"
    ):
        return node.attr
    return None


def test_expensive_tests_have_explicit_markers() -> None:
    seen = set()
    for path in (ROOT / "tests").rglob("test_*.py"):
        module = ast.parse(path.read_text())
        module_marks = {
            marker(node.value)
            for node in module.body
            if isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        }
        for node in module.body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            seen.add(node.name)
            marks = module_marks | {marker(decorator) for decorator in node.decorator_list}
            expected = (
                "runtime"
                if node.name in RUNTIME
                or node.name.endswith(("_container_runtime", "_multi_project_runtime"))
                else "integration"
                if node.name in INTEGRATION or node.name.startswith("test_cruft_")
                else path.parent.name
                if path.parent.name in {"integration", "runtime"}
                else None
            )
            if expected:
                assert expected in marks, f"{path.name}::{node.name} must be marked {expected}"
            assert not {"integration", "runtime"} <= marks, node.name
    assert RUNTIME | INTEGRATION <= seen, "An explicitly protected scenario disappeared"
    options = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["pytest"]["ini_options"]
    assert {s.split(":")[0] for s in options["markers"]} >= {"integration", "runtime"}
    assert "--strict-markers" in options["addopts"]
