"""Dual/custom profile behavior without real accounts or interactive harnesses."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import test_template as template
import yaml


@pytest.mark.parametrize("default", ["codex", "claude"])
def test_both_default_and_explicit_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, default: str
) -> None:
    project = template.generate(tmp_path, coding_agent="both")
    helper = template.configure_agent(project)
    assert helper.AGENTS["codex"].launch.count("--no-daemon") == 1
    assert helper.AGENTS["claude"].launch == ("claude", "--dangerously-skip-permissions")
    monkeypatch.setenv("AGENT_DEFAULT_PROVIDER", default)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "start", lambda: calls.append(("start",)))
    monkeypatch.setattr(helper, "compose", lambda *args: calls.append(args))
    for command in ("run", "login"):
        for explicit in (None, "codex", "claude"):
            calls.clear()
            options = ["agent.py", command] + (["--provider", explicit] if explicit else [])
            monkeypatch.setattr(sys, "argv", options)
            helper.main()
            agent = helper.AGENTS[explicit or default]
            argv = agent.launch if command == "run" else agent.login
            assert calls == [("start",), ("exec", "agent", *argv)]
    monkeypatch.setenv("AGENT_DEFAULT_PROVIDER", "not-installed")
    with pytest.raises(ValueError, match="AGENT_DEFAULT_PROVIDER"):
        helper.selected_agent()


def test_both_same_clone_and_instructions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = template.generate(tmp_path, coding_agent="both")
    template.initialize(project)
    helper = template.configure_agent(project)
    first = helper.prepare()
    monkeypatch.setenv("AGENT_DEFAULT_PROVIDER", "claude")
    second = helper.prepare()
    assert first["workspace"] == second["workspace"]
    assert first["branch"] == second["branch"]
    assert first["base"] == second["base"]
    assert second["profile"] == "both" and second["default_provider"] == "claude"
    assert (project / "AGENTS.md").read_text() == (project / "CLAUDE.md").read_text()


def test_custom_blank_and_safe_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = template.generate(tmp_path, coding_agent="custom")
    helper = template.configure_agent(project)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "start", lambda: calls.append(("start",)))
    monkeypatch.setattr(helper, "compose", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["agent.py", "run"])
    helper.main()
    assert calls == [("start",)]
    assert "no harness command is configured" in capsys.readouterr().out
    marker = tmp_path / "must-not-exist"
    monkeypatch.setenv("CUSTOM_AGENT_COMMAND", "fake-harness")
    monkeypatch.setenv("CUSTOM_AGENT_ARGS", f"--value \"two words\" '$(touch {marker})'")
    calls.clear()
    helper.main()
    assert calls[1] == (
        "exec",
        *([] if sys.stdin.isatty() else ["-T"]),
        "agent",
        "fake-harness",
        "--value",
        "two words",
        f"$(touch {marker})",
    )
    assert not marker.exists()
    assert "CUSTOM_AGENT_COMMAND" not in helper.environment()
    assert "CUSTOM_AGENT_ARGS" not in helper.environment()
    with pytest.raises(ValueError, match="not installed"):
        helper.selected_agent("codex")
    monkeypatch.setenv("CUSTOM_AGENT_COMMAND", "")
    with pytest.raises(ValueError, match="CUSTOM_AGENT_COMMAND"):
        helper.custom_command()


def test_custom_state_does_not_store_command_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = template.generate(tmp_path, coding_agent="custom")
    template.initialize(project)
    helper = template.configure_agent(project)
    monkeypatch.setenv("CUSTOM_AGENT_COMMAND", "fake-harness")
    monkeypatch.setenv("CUSTOM_AGENT_ARGS", "private-test-value")
    helper.prepare()
    state = json.loads(helper.STATE.read_text())
    assert state["profile"] == "custom"
    assert "private-test-value" not in helper.STATE.read_text()
    assert "fake-harness" not in helper.STATE.read_text()


def test_custom_failure_does_not_echo_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = template.generate(tmp_path, coding_agent="custom")
    helper = template.configure_agent(project)
    monkeypatch.setenv("CUSTOM_AGENT_COMMAND", "fake-harness")
    monkeypatch.setenv("CUSTOM_AGENT_ARGS", "private-test-argument")
    monkeypatch.setattr(helper, "start", lambda: None)
    monkeypatch.setattr(sys, "argv", ["agent.py", "run"])

    def fail(*args: str) -> None:
        raise subprocess.CalledProcessError(12, list(args))

    monkeypatch.setattr(helper, "compose", fail)
    with pytest.raises(SystemExit) as caught:
        helper.main()
    assert "exit code 12" in str(caught.value)
    assert "private-test-argument" not in str(caught.value)


def test_rebuild_refuses_running_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = template.generate(tmp_path, coding_agent="custom")
    helper = template.configure_agent(project)
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "check", lambda **kwargs: calls.append((str(kwargs),)))
    monkeypatch.setattr(helper, "agent_container", lambda: {"State": {"Running": True}})
    monkeypatch.setattr(helper, "compose", lambda *args: calls.append(args))
    with pytest.raises(ValueError, match="currently in use"):
        helper.rebuild()
    assert calls == [("{'inspect_image': False}",)]


@pytest.mark.parametrize("old,new", [("codex", "both"), ("claude", "both"), ("custom", "codex")])
def test_profile_change_rejects_reuse_but_allows_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old: str, new: str
) -> None:
    project = template.generate(tmp_path, coding_agent=new)
    template.initialize(project)
    helper = template.configure_agent(project)
    state = helper.prepare()
    state.update(profile=old, provider=old)
    helper.STATE.write_text(json.dumps(state))
    with pytest.raises(ValueError, match="provider differs"):
        helper.state()
    assert helper.state(allow_profile_mismatch=True)["profile"] == old
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "compose", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["agent.py", "clean"])
    helper.main()
    assert calls == [("down",)]
    assert json.loads(helper.STATE.read_text())["profile"] == old


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
