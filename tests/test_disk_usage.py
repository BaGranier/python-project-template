"""Bound temporary retention with real pytest subprocesses; mock only the engine."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest
from test_agent_sessions import commit, session
from test_master_agent import master_helper
from test_template import ROOT, command, generate, load_module


def utility() -> ModuleType:
    return load_module(ROOT / "scripts/disk_usage.py", "disk_utility_test")


def test_retention_configuration(tmp_path: Path) -> None:
    project = generate(tmp_path, coding_agent="none", enable_docs="no", enable_notebooks="no")
    for root in (ROOT, project):
        options = tomllib.loads((root / "pyproject.toml").read_text())["tool"]["pytest"][
            "ini_options"
        ]
        assert options["tmp_path_retention_policy"] == "failed"
        assert options["tmp_path_retention_count"] == "1"
    assert "test-disk-report" in command(project, "make", "help")
    assert "agent-disk" not in command(project, "make", "help")
    assert (project / "tests/conftest.py").read_text() == (ROOT / "tests/conftest.py").read_text()


def test_real_pytest_retention_all_phases(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    shutil.copyfile(ROOT / "pyproject.toml", suite / "pyproject.toml")
    shutil.copyfile(ROOT / "tests/conftest.py", suite / "conftest.py")
    parent = tmp_path / "pytest-parent"
    parent.mkdir()
    env = dict(os.environ, PYTEST_DEBUG_TEMPROOT=str(parent), PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    (suite / "test_retention.py").write_text("""
import json
from pathlib import Path
import pytest

@pytest.fixture
def setup_error(tmp_path):
    (tmp_path / "setup.txt").write_text("keep")
    raise RuntimeError("setup error")

@pytest.fixture
def teardown_error(tmp_path):
    yield
    (tmp_path / "teardown.txt").write_text("keep")
    raise RuntimeError("teardown error")

def test_pass(tmp_path):
    (tmp_path / "blob").write_bytes(b"x" * (8 * 1024 * 1024))
    Path("passed-path.txt").write_text(str(tmp_path))

def test_fail(tmp_path):
    (tmp_path / "failure.txt").write_text("keep")
    Path("failed-path.txt").write_text(str(tmp_path))
    assert False

def test_setup_error(setup_error):
    pass

def test_teardown_error(tmp_path, teardown_error):
    pass
""")

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(suite), *args],
            cwd=suite,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    first = run()
    assert first.returncode == 1, first.stdout + first.stderr
    passed = Path((suite / "passed-path.txt").read_text())
    failed = Path((suite / "failed-path.txt").read_text())
    assert not passed.exists()
    assert (failed / "failure.txt").exists()
    assert list(parent.rglob("setup.txt")) and list(parent.rglob("teardown.txt"))
    first_session = failed.parent
    second = run()
    assert second.returncode == 1, second.stdout + second.stderr
    assert not first_session.exists()
    assert (
        len([p for p in parent.glob("pytest-of-*/pytest-*") if p.is_dir() and not p.is_symlink()])
        == 1
    )
    final = run("-k", "test_pass")
    assert final.returncode == 0, final.stdout + final.stderr
    assert not Path((suite / "passed-path.txt").read_text()).exists()
    assert (Path((suite / "failed-path.txt").read_text()) / "failure.txt").exists()
    # Controlled budget: the successful 8 MiB payload cannot remain; only tiny failed diagnostics.
    assert utility().allocated_size(parent) < 1024 * 1024


@pytest.mark.parametrize("profile", ["codex", "claude", "both", "custom"])
def test_stop_disposes_only_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    helper = session(tmp_path, monkeypatch, profile)
    commit(helper.WORKSPACE, "work.txt", "committed work\n")
    (helper.WORKSPACE / "dirty.txt").write_text("untracked work\n")
    before = helper.STATE.read_bytes()
    head = command(helper.WORKSPACE, "git", "rev-parse", "HEAD")
    monkeypatch.setattr(sys, "argv", ["agent.py", "stop"])
    helper.main()
    assert helper.runtime_calls == [("down",)]
    assert helper.STATE.read_bytes() == before
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD") == head
    assert (helper.WORKSPACE / "dirty.txt").read_text() == "untracked work\n"


def test_disk_without_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = master_helper(tmp_path)
    monkeypatch.setattr(helper.shutil, "which", lambda _: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(helper, "run", lambda args: calls.append(args))
    helper.disk()
    assert "Podman unavailable" in capsys.readouterr().out
    assert calls[0][-1] == str(helper.WORKSPACE)
    assert not helper.STATE_DIR.exists()


def test_size_does_not_follow_symlinks_or_double_count(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    (data / "file").write_bytes(b"x" * 8192)
    before = utility().allocated_size(data)
    (data / "alias").hardlink_to(data / "file")
    assert utility().allocated_size(data) == before
    outside = tmp_path / "outside"
    outside.write_bytes(b"x" * 1024 * 1024)
    (data / "link").symlink_to(outside)
    assert utility().allocated_size(data) < 32 * 1024


def test_cleanup_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = utility()
    monkeypatch.setattr(helper.os, "getuid", lambda: 0)
    with pytest.raises(ValueError, match="only supported inside"):
        helper.clean_temp()
    with pytest.raises(ValueError, match="only supported inside"):
        helper.clean_cache()


def test_cleanup_scoped_and_active_test_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = utility()
    root = tmp_path / "pytest-of-agent"
    root.mkdir()
    current = root / "pytest-1"
    current.mkdir()
    (current / ".lock").write_text(str(os.getpid()))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "credentials").write_text("keep")
    monkeypatch.setattr(helper, "AGENT_TEST_ROOT", root)
    monkeypatch.setattr(helper, "require_agent_runtime", lambda: None)
    with pytest.raises(ValueError, match="may be active"):
        helper.clean_temp()
    (current / ".lock").unlink()
    helper.clean_temp()
    assert not root.exists()
    assert (workspace / "credentials").read_text() == "keep"
    root.symlink_to(workspace)
    with pytest.raises(ValueError, match="symlink"):
        helper.clean_temp()


def test_clean_cache_uses_only_fixed_cache_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = utility()
    monkeypatch.setattr(helper, "require_agent_runtime", lambda: None)
    monkeypatch.setattr(helper, "require_idle_tests", lambda: None)
    calls: list[list[str]] = []
    monkeypatch.setattr(helper.subprocess, "run", lambda args, **kwargs: calls.append(args))
    helper.clean_cache()
    assert calls == [
        ["uv", "cache", "clean", "--cache-dir", "/home/agent/.cache/uv"],
        ["npm", "cache", "clean", "--force", "--cache", "/home/agent/.npm"],
    ]


def test_engine_disk_report_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    helper = master_helper(tmp_path)
    engine: list[list[str]] = []
    composition: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/usr/bin/podman")
    monkeypatch.setattr(
        helper,
        "agent_container",
        lambda: {
            "Id": "this-project-container",
            "State": {"Running": True},
            "Mounts": [
                {
                    "Type": "volume",
                    "Name": "this-project-codex-home",
                    "Destination": "/home/agent/.codex",
                }
            ],
        },
    )
    monkeypatch.setattr(helper, "run", lambda args, **kwargs: engine.append(args))
    monkeypatch.setattr(helper, "compose", lambda *args, **kwargs: composition.append(args))
    monkeypatch.setattr(helper, "storage_command", lambda command: None)
    monkeypatch.setattr(
        helper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0)
    )
    helper.disk()
    assert engine[1][-1] == "this-project-container"
    assert engine[-1] == ["podman", "system", "df", "--verbose"]
    assert composition == [("exec", "-T", "agent", "du", "-sh", "/home/agent/.codex")]
    assert not any("prune" in arg or arg in {"rm", "down"} for args in engine for arg in args)
    assert not helper.STATE_DIR.exists()
