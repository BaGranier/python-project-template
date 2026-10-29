"""Dogfooding safety without giving the sandbox access to a host engine."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import yaml
from test_template import ROOT, command, initialize, load_module, runtime_cleanup


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


def test_master_container_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not shutil.which("podman"):
        pytest.skip(
            "Host-only dogfooding: Podman engine intentionally unavailable in agent/bootstrap"
        )
    import subprocess

    info = subprocess.run(["podman", "info", "--format", "json"], capture_output=True, text=True)
    if info.returncode or not json.loads(info.stdout)["host"]["security"]["rootless"]:
        pytest.skip("Host-only dogfooding requires usable rootless Podman")
    # Never start a lifecycle against the real template checkout in a test.
    project = tmp_path / "master"
    shutil.copytree(
        ROOT,
        project,
        ignore=shutil.ignore_patterns(
            ".git",
            ".agent",
            ".venv",
            ".env",
            "generated",
            "__pycache__",
            ".*cache",
            "Dockerfile.dev",
            "docker-compose.yaml",
        ),
    )
    initialize(project)
    helper = master_helper(project)
    # A host may already have the real master sandbox running. Never share its
    # Compose project, image or credentials, even when testing a copied master.
    slug = f"master-runtime-{uuid4().hex[:12]}"
    manifest = project / "containers/compose.agent.yaml"
    manifest.write_text(manifest.read_text().replace("python-project-template", slug))
    monkeypatch.setattr(helper, "IMAGE", helper.IMAGE.replace("python-project-template", slug))
    command(project, "git", "add", ".")
    command(project, "git", "commit", "-m", "test: isolate runtime resources")
    monkeypatch.setenv("AGENT_APP_PORT", "18000")
    with runtime_cleanup(lambda: helper.compose("down", "--volumes")):
        helper.start()
        assert helper.compose("exec", "-T", "agent", "id", "-u", capture=True) == "1000"
        helper.compose("exec", "-T", "agent", "make", "check")
        for agent in helper.AGENTS.values():
            helper.compose("exec", "-T", "agent", "touch", agent.config_dir + "/sentinel")
        helper.compose("stop")
        (helper.WORKSPACE / "harness-work.txt").write_text("preserve workspace\n")
        saved_state = helper.STATE.read_bytes()
        pins = helper.harness_versions()
        helper.update("codex", pins["CODEX_VERSION"])
        assert helper.STATE.read_bytes() == saved_state
        assert (helper.WORKSPACE / "harness-work.txt").read_text() == "preserve workspace\n"
        before = helper.VERSIONS_FILE.read_bytes()
        with pytest.raises(subprocess.CalledProcessError):
            helper.update("codex", "999999.0.0")
        assert helper.VERSIONS_FILE.read_bytes() == before
        assert helper.STATE.read_bytes() == saved_state
        helper.start()
        for name, agent in helper.AGENTS.items():
            actual = helper.compose("exec", "-T", "agent", agent.cli, "--version", capture=True)
            assert helper.parsed_version(name, actual) == pins[helper.VERSION_KEYS[name]]
        helper.compose(
            "exec",
            "-T",
            "agent",
            "python",
            "-c",
            "import os; assert not os.access('/usr/local/bin', os.W_OK); "
            "assert not os.access('/usr/local/lib/node_modules', os.W_OK)",
        )
        for agent in helper.AGENTS.values():
            helper.compose("exec", "-T", "agent", "test", "-f", agent.config_dir + "/sentinel")
        helper.compose("exec", "-T", "agent", "curl", "--fail", "-I", "https://example.com")
        helper.compose(
            "exec",
            "-T",
            "agent",
            "python",
            "-c",
            "import os; assert os.environ['HOME'] == '/home/agent'; "
            "assert not os.path.exists('/var/run/docker.sock'); "
            "assert not os.path.exists('/run/podman/podman.sock')",
        )
        container = helper.agent_container()
        assert container is not None
        binds = [mount for mount in container["Mounts"] if mount["Type"] == "bind"]
        assert len(binds) == 1 and Path(binds[0]["Source"]).resolve() == helper.WORKSPACE
        assert set(helper.published_ports(container)) == {"app"}
