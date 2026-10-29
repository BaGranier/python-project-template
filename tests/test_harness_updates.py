"""Exercise update transactions with real Git state and a simulated engine boundary."""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from urllib.error import URLError

import pytest
from test_agent_sessions import commit, session
from test_master_agent import master_helper
from test_template import ROOT, command, configure_agent, generate


@pytest.mark.parametrize("value", ["0.0.0", "1.2.3", "999999.0.1"])
def test_valid_versions(tmp_path: Path, value: str) -> None:
    assert master_helper(tmp_path).validate_version(value) == value


@pytest.mark.parametrize(
    "value", ["", "latest", "1.2", "v1.2.3", "01.2.3", "1.2.3-beta.1", "1.2.3\n", "$(id)", ";id"]
)
def test_invalid_versions(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="Invalid harness version"):
        master_helper(tmp_path).validate_version(value)


def transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str = "both"
) -> tuple[ModuleType, list[list[str]], list[tuple[str, ...]]]:
    helper = session(tmp_path, monkeypatch, profile)
    commit(helper.WORKSPACE, "agent-work.txt", "keep committed work\n")
    original_pins = helper.harness_versions() if helper.AGENTS else {}
    engine: list[list[str]] = []
    compose: list[tuple[str, ...]] = []
    helper.__dict__["candidate_pins"] = {}
    helper.__dict__["fail_build"] = False
    helper.__dict__["wrong_version"] = False
    helper.__dict__["fail_activation"] = False
    helper.__dict__["running"] = False
    monkeypatch.setattr(helper, "check", lambda **kwargs: None)
    monkeypatch.setattr(helper, "agent_container", lambda: {"State": {"Running": helper.running}})

    def external(args: list[str], **kwargs: Any) -> SimpleNamespace:
        assert args[:3] in (["podman", "image", "exists"], ["podman", "untag", args[2]])
        engine.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", external)
    original_run = helper.run

    def run(args: list[str], **kwargs: Any) -> str:
        if args[0] != "podman":
            result: str = original_run(args, **kwargs)
            return result
        engine.append(args)
        if args[1] == "build":
            assert (helper.harness_versions() if helper.AGENTS else {}) == original_pins
            if helper.fail_build:
                raise subprocess.CalledProcessError(125, args)
            helper.__dict__["candidate_pins"] = dict(
                item.split("=", 1)
                for item in args
                if item.startswith(tuple(helper.VERSION_KEYS.values()))
            )
        if args[1:3] == ["image", "inspect"]:
            return "sha256:previous-image"
        if args[1] == "run":
            assert "--network=none" in args and "--user" in args
            assert "--cap-drop=ALL" in args and "--security-opt=no-new-privileges" in args
            assert "--volume" not in args and "-v" not in args
            name = args[-2]
            value = helper.candidate_pins[helper.VERSION_KEYS[name]]
            if helper.wrong_version:
                value = "0.0.0"
            return f"codex-cli {value}" if name == "codex" else f"{value} (Claude Code)"
        return ""

    def composition(*args: str, **kwargs: Any) -> str:
        compose.append(args)
        if args[0] == "exec":
            if helper.fail_activation:
                helper.__dict__["fail_activation"] = False
                raise subprocess.CalledProcessError(125, list(args))
            name = args[-2]
            value = helper.harness_versions()[helper.VERSION_KEYS[name]]
            return f"codex-cli {value}" if name == "codex" else f"{value} (Claude Code)"
        return ""

    monkeypatch.setattr(helper, "run", run)
    monkeypatch.setattr(helper, "compose", composition)
    return helper, engine, compose


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom"])
def test_rebuild_preserves_git_and_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    helper, engine, composition = transaction(tmp_path, monkeypatch, profile)
    # An untracked file and the complete object database must survive unchanged.
    (helper.WORKSPACE / "untracked.txt").write_text("keep me\n")
    before = {
        p.relative_to(helper.WORKSPACE): p.read_bytes()
        for p in helper.WORKSPACE.rglob("*")
        if p.is_file()
    }
    state = helper.STATE.read_bytes()
    helper.rebuild()
    after = {
        p.relative_to(helper.WORKSPACE): p.read_bytes()
        for p in helper.WORKSPACE.rglob("*")
        if p.is_file()
    }
    assert after == before
    assert helper.STATE.read_bytes() == state
    assert composition[0] == ("up", "-d", "--no-build", "--force-recreate", "agent")
    assert composition[-1] == ("stop", "agent")
    assert all("--volumes" not in args for args in composition)
    assert any(args[:2] == ["podman", "build"] for args in engine)


@pytest.mark.parametrize("provider,target", [("codex", "0.165.0"), ("claude", "2.1.311")])
def test_explicit_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, target: str
) -> None:
    helper, engine, _ = transaction(tmp_path, monkeypatch)
    before = helper.harness_versions()
    helper.update(provider, target)
    after = helper.harness_versions()
    key = helper.VERSION_KEYS[provider]
    assert after == before | {key: target}
    build = next(args for args in engine if args[1] == "build")
    assert f"{key}={target}" in build
    assert engine.index(build) < next(i for i, args in enumerate(engine) if args[1] == "tag")


@pytest.mark.parametrize("failure", ["fail_build", "wrong_version", "fail_activation"])
def test_failed_update_restores_pins_and_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    helper, engine, composition = transaction(tmp_path, monkeypatch)
    before = helper.VERSIONS_FILE.read_bytes()
    state = helper.STATE.read_bytes()
    monkeypatch.setattr(helper, failure, True)
    with pytest.raises((subprocess.CalledProcessError, ValueError)):
        helper.update("codex", "999999.0.0")
    assert helper.VERSIONS_FILE.read_bytes() == before
    assert helper.STATE.read_bytes() == state
    tags = [args for args in engine if args[1] == "tag"]
    if failure == "fail_activation":
        assert tags[-1] == ["podman", "tag", "sha256:previous-image", helper.IMAGE]
        assert composition[-1] == ("stop", "agent")
    else:
        assert not tags and not composition


def test_latest_resolution_and_network_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, _, _ = transaction(tmp_path, monkeypatch)
    monkeypatch.setattr(
        helper, "urlopen", lambda *args, **kwargs: io.BytesIO(b'{"version":"3.0.0"}')
    )
    helper.update(None, None)
    assert set(helper.harness_versions().values()) == {"3.0.0"}
    before = helper.VERSIONS_FILE.read_bytes()

    def offline(*args: Any, **kwargs: Any) -> None:
        raise URLError("offline")

    monkeypatch.setattr(helper, "urlopen", offline)
    with pytest.raises(URLError):
        helper.update_check()
    with pytest.raises(URLError):
        helper.update("codex", None)
    assert helper.VERSIONS_FILE.read_bytes() == before


def test_update_refuses_active_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper, engine, composition = transaction(tmp_path, monkeypatch)
    monkeypatch.setattr(helper, "running", True)
    with pytest.raises(ValueError, match="make agent-stop"):
        helper.update("codex", "1.2.3")
    assert engine == []
    assert composition == []


def test_versions_without_engine_and_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = session(tmp_path, monkeypatch)
    monkeypatch.setattr(helper.shutil, "which", lambda _: None)
    helper.versions()
    assert "configured: 0." in capsys.readouterr().out
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/usr/bin/podman")
    monkeypatch.setattr(helper, "agent_container", lambda: {"State": {"Running": True}})
    monkeypatch.setattr(
        helper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    monkeypatch.setattr(
        helper,
        "compose",
        lambda *args, **kwargs: "codex-cli 0.0.0" if "codex" in args else "0.0.0 (Claude Code)",
    )
    helper.versions()
    assert "make agent-rebuild" in capsys.readouterr().out


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom", "none"])
def test_generated_update_interface(tmp_path: Path, profile: str) -> None:
    project = generate(tmp_path, coding_agent=profile)
    help_text = command(project, "make", "help")
    managed = profile not in {"none", "custom"}
    assert ("agent-update-check" in help_text) == managed
    assert ("agent-update-codex" in help_text) == (profile in {"codex", "both"})
    assert ("agent-update-claude" in help_text) == (profile in {"claude", "both"})
    assert (project / "containers/harness-versions.env").exists() == managed
    if managed:
        helper = configure_agent(project)
        assert helper.harness_versions() == master_helper(ROOT).harness_versions()
        containerfile = (project / "containers/Containerfile").read_text()
        for key in helper.harness_versions():
            assert f"ARG {key}=" not in containerfile
        if "codex" in helper.AGENTS:
            assert "--no-daemon" in helper.AGENTS["codex"].launch
            assert "check_for_update_on_startup=false" in helper.AGENTS["codex"].launch


def test_master_versions_share_source() -> None:
    path = ROOT / "containers/harness-versions.env"
    assert path.is_symlink()
    assert path.resolve() == ROOT / "{{cookiecutter.project_slug}}/containers/harness-versions.env"


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom"])
def test_master_update_help(profile: str) -> None:
    help_text = command(ROOT, "make", "help", f"AGENT_PROFILE={profile}")
    assert ("agent-update-check" in help_text) == (profile != "custom")
    assert ("agent-update-codex" in help_text) == (profile in {"codex", "both"})
    assert ("agent-update-claude" in help_text) == (profile in {"claude", "both"})


def test_atomic_pin_write_preserves_shared_link(tmp_path: Path) -> None:
    helper = master_helper(tmp_path)
    source = tmp_path / "shared.env"
    source.write_text("CODEX_VERSION=1.0.0\n")
    helper.VERSIONS_FILE.parent.mkdir()
    helper.VERSIONS_FILE.symlink_to(source)
    helper.write_pins("CODEX_VERSION=2.0.0\n")
    assert helper.VERSIONS_FILE.is_symlink()
    assert source.read_text() == "CODEX_VERSION=2.0.0\n"


@pytest.mark.parametrize("value", ["", "1.2.3; touch injected-file", "$(touch injected-file)"])
def test_make_version_is_not_shell_code(tmp_path: Path, value: str) -> None:
    project = generate(tmp_path)
    result = subprocess.run(
        ["make", "agent-update-codex", f"VERSION={value}"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
    )
    # The default single-provider project exposes its own update target.
    assert result.returncode != 0
    assert "Invalid harness version" in result.stderr
    assert not (project / "injected-file").exists()


def test_reports_do_not_create_agent_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from test_master_agent import temporary_master

    helper = master_helper(temporary_master(tmp_path / "master"))
    monkeypatch.setattr(helper.shutil, "which", lambda _: None)
    monkeypatch.setattr(helper, "latest_version", lambda _: "1.0.0")
    for report in ("versions", "update-check"):
        monkeypatch.setattr(sys, "argv", ["agent.py", report])
        helper.main()
        assert not helper.STATE_DIR.exists()


def test_pin_environment_cannot_override_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_master_agent import temporary_master

    helper = master_helper(temporary_master(tmp_path / "master"))
    monkeypatch.setenv("CODEX_VERSION", "latest")
    monkeypatch.setenv("CLAUDE_CODE_VERSION", "$(id)")
    (helper.ROOT / ".env").write_text("CODEX_VERSION=9.9.9\nCLAUDE_CODE_VERSION=9.9.9\n")
    env = helper.environment()
    for key, value in helper.harness_versions().items():
        assert env[key] == value


def test_new_session_during_build_prevents_activation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, engine, composition = transaction(tmp_path, monkeypatch)
    before = helper.VERSIONS_FILE.read_bytes()
    real_probe = helper.image_version

    def probe(image: str, name: str) -> str:
        value: str = real_probe(image, name)
        helper.__dict__["running"] = True
        return value

    monkeypatch.setattr(helper, "image_version", probe)
    with pytest.raises(ValueError, match="currently in use"):
        helper.update("codex", "1.2.3")
    assert helper.VERSIONS_FILE.read_bytes() == before
    assert not any(args[1] == "tag" for args in engine)
    assert not composition


def test_unwritable_pin_does_not_activate_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, engine, composition = transaction(tmp_path, monkeypatch)
    before = helper.VERSIONS_FILE.read_bytes()

    def unwritable(content: str) -> None:
        raise PermissionError("cannot write pins")

    monkeypatch.setattr(helper, "write_pins", unwritable)
    with pytest.raises(PermissionError):
        helper.update("codex", "1.2.3")
    assert helper.VERSIONS_FILE.read_bytes() == before
    assert not any(args[1] == "tag" for args in engine)
    assert not composition
