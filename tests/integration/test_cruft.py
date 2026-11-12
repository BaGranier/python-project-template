"""All Cruft contexts plus representative update cycles and legacy migrations."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import test_template as template
import yaml
from test_template import (
    ROOT,
    command,
    initialize,
)

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("provider", ["codex", "claude", "both", "custom", "none"])
def test_cruft_create_check_diff(tmp_path: Path, provider: str) -> None:
    source = tmp_path / "template"
    source.mkdir()
    for name in ("cookiecutter.json", "README.md"):
        shutil.copyfile(ROOT / name, source / name)
    for name in ("hooks", "{{cookiecutter.project_slug}}"):
        shutil.copytree(ROOT / name, source / name)
    initialize(source)
    destination = tmp_path / "output"
    command(
        ROOT,
        sys.executable,
        "-m",
        "cruft",
        "create",
        str(source),
        "--no-input",
        "--extra-context",
        json.dumps({"coding_agent": provider}),
        "--output-dir",
        str(destination),
    )
    project = destination / "my-python-project"
    assert json.loads((project / ".cruft.json").read_text())["commit"]
    context = json.loads((project / ".cruft.json").read_text())["context"]["cookiecutter"]
    assert context["coding_agent"] == provider
    assert (project / "scripts/agent.py").exists() == (provider != "none")
    # All contexts still use real Cruft create. Full check/diff/update is shared
    # by the dual-harness and agent-free cases; migration tests cover real changes.
    if provider in {"both", "none"}:
        command(project, sys.executable, "-m", "cruft", "check")
        command(project, sys.executable, "-m", "cruft", "diff")
        command(project, sys.executable, "-m", "cruft", "update", "--skip-apply-ask")


@pytest.mark.parametrize("legacy_enabled,provider", [("yes", "codex"), ("no", "none")])
def test_cruft_legacy_context_upgrade(tmp_path: Path, legacy_enabled: str, provider: str) -> None:
    # A real old-schema template commit, followed by the current template commit.
    # Self-contained so CI does not require historical Git objects or a deep checkout.
    source = tmp_path / "template"
    source.mkdir()
    config = json.loads((ROOT / "cookiecutter.json").read_text())
    config.pop("coding_agent")
    config["enable_agent"] = ["yes", "no"]
    (source / "cookiecutter.json").write_text(json.dumps(config))
    legacy = source / "{{cookiecutter.project_slug}}"
    legacy.mkdir()
    (legacy / "README.md").write_text("# {{cookiecutter.project_name}}\n")
    initialize(source)
    command(
        ROOT,
        sys.executable,
        "-m",
        "cruft",
        "create",
        str(source),
        "--no-input",
        "--extra-context",
        json.dumps({"enable_agent": legacy_enabled}),
        "--output-dir",
        str(tmp_path / "output"),
    )
    project = tmp_path / "output/my-python-project"
    old_context = json.loads((project / ".cruft.json").read_text())["context"]["cookiecutter"]
    assert old_context["enable_agent"] == legacy_enabled and "coding_agent" not in old_context
    initialize(project)
    shutil.rmtree(legacy)
    shutil.copytree(ROOT / "{{cookiecutter.project_slug}}", legacy)
    shutil.copytree(ROOT / "hooks", source / "hooks")
    shutil.copyfile(ROOT / "cookiecutter.json", source / "cookiecutter.json")
    command(source, "git", "add", ".")
    command(source, "git", "commit", "-m", "add coding_agent")
    outdated = subprocess.run(
        [sys.executable, "-m", "cruft", "check"], cwd=project, capture_output=True, check=False
    )
    assert outdated.returncode != 0
    command(project, sys.executable, "-m", "cruft", "diff")
    command(
        project,
        sys.executable,
        "-m",
        "cruft",
        "update",
        "--skip-apply-ask",
        "--variables-to-update",
        json.dumps({"coding_agent": provider}),
    )
    state = json.loads((project / ".cruft.json").read_text())
    assert state["context"]["cookiecutter"]["coding_agent"] == provider
    assert (project / "scripts/agent.py").exists() == (provider != "none")
    assert not list(project.glob("*.rej"))
    command(project, sys.executable, "-m", "cruft", "check")
    command(project, "make", "check")


def test_cruft_codex_to_both_preserves_volume_name(tmp_path: Path) -> None:
    source = tmp_path / "template"
    source.mkdir()
    for name in ("cookiecutter.json", "README.md"):
        shutil.copyfile(template.ROOT / name, source / name)
    for name in ("hooks", "{{cookiecutter.project_slug}}"):
        shutil.copytree(template.ROOT / name, source / name)
    template.initialize(source)
    template.command(
        template.ROOT,
        sys.executable,
        "-m",
        "cruft",
        "create",
        str(source),
        "--no-input",
        "--output-dir",
        str(tmp_path / "output"),
    )
    project = tmp_path / "output/my-python-project"
    template.initialize(project)
    old_helper = template.configure_agent(project)
    old_helper.prepare()
    before = yaml.safe_load((project / "containers/compose.agent.yaml").read_text())
    volume = before["volumes"]["agent-codex-home"]["name"]
    template.command(
        project,
        sys.executable,
        "-m",
        "cruft",
        "update",
        "--skip-apply-ask",
        "--variables-to-update",
        json.dumps({"coding_agent": "both"}),
    )
    template.command(project, sys.executable, "-m", "cruft", "check")
    template.command(project, sys.executable, "-m", "cruft", "diff")
    assert (
        json.loads((project / ".cruft.json").read_text())["context"]["cookiecutter"]["coding_agent"]
        == "both"
    )
    after = yaml.safe_load((project / "containers/compose.agent.yaml").read_text())
    assert after["volumes"]["agent-codex-home"]["name"] == volume
    assert "agent-claude-home" in after["volumes"]
    assert (project / "AGENTS.md").read_text() == (project / "CLAUDE.md").read_text()
    updated_helper = template.configure_agent(project)
    with pytest.raises(ValueError, match="provider differs"):
        updated_helper.state()
    template.command(project, "make", "check")
