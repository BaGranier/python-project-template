"""Dogfooding safety without giving the sandbox access to a host engine."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml
from test_template import ROOT, command, initialize, load_module


def master_helper(project: Path, profile: str = "both") -> ModuleType:
    renderer = load_module(ROOT / "scripts/master_agent.py", "master_renderer_test")
    helper = ModuleType(f"master_runtime_{profile}")
    helper.__file__ = str(project / "scripts/agent.py")
    sys.modules[helper.__name__] = helper
    exec(compile(renderer.runtime_source(profile), helper.__file__, "exec"), helper.__dict__)
    return helper


def temporary_master(path: Path) -> Path:
    path.mkdir()
    (path / ".gitignore").write_text(".agent/\n.venv/\n.env\n")
    (path / "important.txt").write_text("primary checkout\n")
    (path / "containers").mkdir()
    shutil.copyfile(
        ROOT / "containers/harness-versions.env", path / "containers/harness-versions.env"
    )
    initialize(path)
    return path


def test_master_artifacts_are_synchronized() -> None:
    renderer = load_module(ROOT / "scripts/master_agent.py", "master_artifacts_test")
    for name, expected in renderer.artifacts().items():
        assert (ROOT / name).read_text() == expected, f"Run make agent-sync: {name}"
    assert (ROOT / "CLAUDE.md").read_text() == (ROOT / "AGENTS.md").read_text()


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom"])
def test_master_profiles_and_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    helper = master_helper(tmp_path, profile)
    assert helper.ROOT == tmp_path
    assert helper.PROFILE == profile
    if "codex" in helper.AGENTS:
        assert helper.AGENTS["codex"].launch.count("--no-daemon") == 1
        assert "--dangerously-bypass-approvals-and-sandbox" in helper.AGENTS["codex"].launch
    if "claude" in helper.AGENTS:
        assert helper.AGENTS["claude"].launch == ("claude", "--dangerously-skip-permissions")
    assert set(helper.AGENTS) == (
        {"codex", "claude"} if profile == "both" else set() if profile == "custom" else {profile}
    )
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/usr/bin/podman-compose")
    calls: list[list[str]] = []

    def capture_call(args: list[str], **kwargs: object) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(helper, "run", capture_call)
    helper.compose("config")
    filename = "compose.agent.yaml" if profile == "both" else f"compose.agent.{profile}.yaml"
    assert str(tmp_path / "containers" / filename) in calls[0]
    config = yaml.safe_load((ROOT / "containers" / filename).read_text())
    service = config["services"]["agent"]
    assert service["build"]["target"] == profile
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["user"] == "1000:1000"
    assert service.get("network_mode") != "host" and not service.get("privileged")
    binds = [value for value in service["volumes"] if value.startswith("${")]
    assert binds == ["${AGENT_WORKSPACE:?run make agent-start}:/workspace:Z"]
    assert all(port.startswith("127.0.0.1:") for port in service["ports"])
    assert helper.environment()["PODMAN_COMPOSE_PROVIDER"] == "/usr/bin/podman-compose"
    with helper.reserve_ports({"app": 18000}) as ports:
        assert 1024 <= ports["app"] <= 65535
    env = dict(os.environ, AGENT_PROFILE=profile)
    assert "Host-controlled" in command(
        ROOT, "uv", "run", "python", "scripts/agent.py", "--help", env=env
    )


def test_master_destruction_diff_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = temporary_master(tmp_path / "master")
    helper = master_helper(project)
    monkeypatch.setattr(helper, "running_containers", lambda: False)
    saved = helper.prepare()
    assert saved["base"] == command(project, "git", "rev-parse", "HEAD").strip()
    assert saved["profile"] == "both" and saved["default_provider"] == "codex"
    assert saved["branch"].startswith("agent/")
    assert (helper.WORKSPACE / ".git").is_dir()
    assert not (helper.WORKSPACE / ".git").is_symlink()
    assert not (helper.WORKSPACE / ".git/objects/info/alternates").exists()
    primary_objects = {
        str(p.relative_to(project / ".git/objects")): p.stat().st_ino
        for p in (project / ".git/objects").glob("*/*")
        if p.is_file()
    }
    for path in (helper.WORKSPACE / ".git/objects").glob("*/*"):
        relative = str(path.relative_to(helper.WORKSPACE / ".git/objects"))
        if path.is_file() and relative in primary_objects:
            assert path.stat().st_ino != primary_objects[relative]
    (helper.WORKSPACE / "important.txt").unlink()
    assert (project / "important.txt").read_text() == "primary checkout\n"
    command(helper.WORKSPACE, "git", "add", ".")
    command(helper.WORKSPACE, "git", "commit", "-m", "test: isolated deletion")
    helper.diff()
    capsys.readouterr()
    helper.apply()
    assert not (project / "important.txt").exists()
    assert "isolated deletion" in command(project, "git", "log", "-1", "--oneline")
    assert command(project, "git", "status", "--porcelain").strip() == ""


def test_master_refuses_dirty_primary(tmp_path: Path) -> None:
    project = temporary_master(tmp_path / "master")
    helper = master_helper(project)
    (project / "important.txt").write_text("uncommitted user work\n")
    with pytest.raises(ValueError, match="Commit or stash"):
        helper.prepare()
    assert not helper.WORKSPACE.exists()
    assert (project / "important.txt").read_text() == "uncommitted user work\n"


def test_child_project_does_not_sync_generator_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/opt/venv")
    assert command(
        tmp_path, sys.executable, "-c", "import os; print(os.environ['UV_PROJECT_ENVIRONMENT'])"
    ).strip() == str(tmp_path / ".venv")
