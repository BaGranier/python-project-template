"""Adoption preserves real Git histories and existing application workflows."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from test_template import ROOT, command, generate, load_module


@pytest.fixture
def adopter() -> ModuleType:
    return load_module(ROOT / "scripts/adopt.py", "adopter_test")


def repository(path: Path, files: dict[str, str]) -> Path:
    path.mkdir()
    command(path, "git", "init", "-b", "main")
    command(path, "git", "config", "user.name", "Adoption Test")
    command(path, "git", "config", "user.email", "adoption@example.test")
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    command(path, "git", "add", ".")
    command(path, "git", "commit", "-m", "existing application")
    (path / "history.txt").write_text("second pre-existing commit\n")
    command(path, "git", "add", ".")
    command(path, "git", "commit", "-m", "existing history")
    return path


@pytest.mark.parametrize(
    ("profile", "manifests"),
    [
        ("python", {"pyproject.toml": '[project]\nname="legacy"\nversion="1.0"\n'}),
        (
            "node",
            {
                "package.json": '{"scripts":{"test":"node -e \\"process.exit(0)\\""}}',
                "package-lock.json": "{}",
            },
        ),
        ("mixed", {"backend/pyproject.toml": "[tool.ruff]\n", "frontend/package.json": "{}"}),
        ("generic", {"Cargo.toml": '[package]\nname="existing"\n'}),
    ],
)
def test_profiles_preserve_history_and_application(
    tmp_path: Path, adopter: ModuleType, profile: str, manifests: dict[str, str]
) -> None:
    files = {
        **manifests,
        "src/application.txt": "existing source\n",
        "tests/legacy.txt": "existing tests\n",
        "Makefile": "legacy:\n\t@echo preserved\n",
        ".gitignore": ".env\nlegacy-cache/\n",
        ".env.example": "LEGACY=yes\n",
        "Dockerfile": "FROM scratch\n",
        "compose.yaml": "services: {}\n",
        ".github/workflows/ci.yml": "name: historical\n",
    }
    repo = repository(tmp_path / profile, files)
    history = command(repo, "git", "log", "--format=%H")
    git_before = {
        str(p.relative_to(repo)): p.read_bytes() for p in (repo / ".git").rglob("*") if p.is_file()
    }
    dry = command(ROOT, "make", "adopt-dry-run", f"REPO={repo}")
    assert "Detected stack" in dry
    assert f"profile: {profile}" in dry
    assert "No files modified." in dry
    assert command(repo, "git", "status", "--porcelain") == ""
    assert not (repo / ".template").exists()
    command(ROOT, "make", "adopt", f"REPO={repo}")
    for name, content in files.items():
        if name not in {"Makefile", ".gitignore", ".env.example"}:
            assert (repo / name).read_text() == content
    assert command(repo, "git", "log", "--format=%H") == history
    for name, git_content in git_before.items():
        # Git may refresh its index stat cache; repository objects/refs/config stay identical.
        if name != ".git/index":
            assert (repo / name).read_bytes() == git_content
    assert "preserved" in command(repo, "make", "legacy")
    assert (repo / ".gitignore").read_text().count(".env\n") == 1
    assert ".agent/" in (repo / ".gitignore").read_text()
    assert (repo / ".env.example").read_text().startswith("LEGACY=yes\n")
    metadata = json.loads((repo / ".template/adoption.json").read_text())
    assert metadata["profile"] == profile
    assert metadata["adopted"] is True
    assert not (repo / ".cruft.json").exists()
    if profile != "python":
        assert not (repo / "pyproject.toml").exists()
    helper = load_module(repo / "scripts/agent.py", f"adopted_{profile}")
    assert helper.PROFILE == "both"
    # Commit explicitly as an adopter would: prepare clones committed infrastructure.
    command(repo, "git", "add", ".")
    command(repo, "git", "commit", "-m", "reviewed adoption")
    session = helper.prepare()
    assert (helper.WORKSPACE / ".git").is_dir()
    assert command(helper.WORKSPACE, "git", "rev-parse", "HEAD").strip() == session["base"]
    assert not (helper.WORKSPACE / ".git/objects/info/alternates").exists()
    assert command(repo, "git", "log", "--format=%H").endswith(history)
    assert "No application command" in command(repo, "make", "template-build")


@pytest.mark.parametrize("harness", ["codex", "claude", "both", "custom", "none"])
def test_harness_independence(tmp_path: Path, adopter: ModuleType, harness: str) -> None:
    repo = repository(tmp_path / "app", {"README.md": "legacy\n"})
    report = adopter.audit(repo)
    entries = adopter.plan(repo, report, "generic", harness)
    adopter.apply(repo, entries)
    helper = load_module(repo / "scripts/agent.py", f"adopt_harness_{harness}")
    assert helper.PROFILE == harness
    assert helper.selected_agent() is None if harness in {"custom", "none"} else helper.AGENTS
    assert "No application command" in command(repo, "make", "check")
    assert "--no-project" in command(repo, "make", "-n", "agent-check")


@pytest.mark.parametrize(
    ("conflict", "value"),
    [
        ("scripts/agent.py", "existing helper"),
        (".env.example", "AGENT_APP_PORT=19000\n"),
        ("Makefile", "agent:\n\t@echo old\n"),
    ],
)
def test_conflicts_are_transactional(
    tmp_path: Path, adopter: ModuleType, conflict: str, value: str
) -> None:
    repo = repository(tmp_path / "app", {conflict: value})
    entries = adopter.plan(repo, adopter.audit(repo), "generic", "both")
    assert any(e.blocking and e.action == "REVIEW" for e in entries)
    with pytest.raises(ValueError, match="Blocking conflicts"):
        adopter.apply(repo, entries)
    assert (repo / conflict).read_text() == value
    assert command(repo, "git", "status", "--porcelain") == ""


def test_dirty_and_invalid_repositories(tmp_path: Path, adopter: ModuleType) -> None:
    repo = repository(tmp_path / "app", {"README.md": "legacy"})
    entries = adopter.plan(repo, adopter.audit(repo), "generic", "both")
    (repo / "README.md").write_text("dirty")
    with pytest.raises(ValueError, match="Commit or stash"):
        adopter.apply(repo, entries)
    assert not (repo / ".template").exists()
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        adopter.audit(tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        adopter.audit(tmp_path / "missing")


def test_symlinks_and_instruction_candidates(tmp_path: Path, adopter: ModuleType) -> None:
    repo = repository(tmp_path / "app", {"AGENTS.md": "existing instructions"})
    entries = adopter.plan(repo, adopter.audit(repo), "generic", "codex")
    adopter.apply(repo, entries)
    assert (repo / "AGENTS.md").read_text() == "existing instructions"
    assert (repo / "AGENTS.template.md").is_file()
    (repo / "scripts/agent.py").unlink()
    (repo / "scripts/agent.py").symlink_to(tmp_path / "external")
    with pytest.raises(ValueError, match="Unsafe destination"):
        adopter.plan(repo, adopter.audit(repo), "generic", "codex")


def test_rollback_on_write_failure(
    tmp_path: Path, adopter: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = repository(tmp_path / "app", {"README.md": "legacy"})
    entries = adopter.plan(repo, adopter.audit(repo), "generic", "both")
    original = Path.open

    def fail(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path.name == "project.py" and args == ("xb",):
            raise OSError("simulated disk failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError, match="simulated"):
        adopter.apply(repo, entries)
    assert command(repo, "git", "status", "--porcelain") == ""
    assert not (repo / "scripts").exists()


@pytest.mark.parametrize("profile", ["node", "mixed", "generic", "auto"])
@pytest.mark.parametrize("agent", ["both", "none"])
def test_new_nonpython_projects(tmp_path: Path, profile: str, agent: str) -> None:
    project = generate(tmp_path, project_profile=profile, coding_agent=agent)
    assert not (project / "pyproject.toml").exists()
    assert not (project / "uv.lock").exists()
    for target in ("setup", "check", "build", "docs-build"):
        assert "No application command" in command(project, "make", target)
    assert (project / "scripts/agent.py").exists() == (agent != "none")


def test_node_commands_and_safe_argv(tmp_path: Path, adopter: ModuleType) -> None:
    repo = repository(
        tmp_path / "app",
        {
            "package.json": '{"scripts":{"lint":"echo lint"},"packageManager":"pnpm@9.0.0"}',
            "pnpm-lock.yaml": "lockfileVersion: 9",
        },
    )
    report = adopter.audit(repo)
    configured = adopter.commands(report, "node")
    assert configured["lint"] == [{"argv": ["pnpm", "run", "lint"]}]
    assert "test" not in configured
    assert configured["setup"] == [{"argv": ["pnpm", "install"]}]
    assert adopter.commands(report, "mixed") == {}
    adopter.apply(repo, adopter.plan(repo, report, "node", "none"))
    runner = load_module(repo / "scripts/project.py", "project_command_runner")
    # Shell punctuation stays literal argv, and cwd must remain in the repository.
    (repo / ".template/project.json").write_text(
        json.dumps({"commands": {"test": [{"argv": ["touch", "literal;file"]}]}})
    )
    runner.execute("test")
    assert (repo / "literal;file").is_file()
    (repo / ".template/project.json").write_text(
        json.dumps({"commands": {"test": [{"argv": ["touch", "escape"], "cwd": ".."}]}})
    )
    with pytest.raises(ValueError, match="inside the repository"):
        runner.execute("test")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize("profile", ["python", "node", "mixed", "generic"])
def test_adopted_start_does_not_sync_application(
    tmp_path: Path, adopter: ModuleType, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    repo = repository(tmp_path / "app", {"README.md": "legacy"})
    adopter.apply(repo, adopter.plan(repo, adopter.audit(repo), profile, "none"))
    helper = load_module(repo / "scripts/agent.py", f"start_adopted_{profile}")
    calls = []
    monkeypatch.setattr(helper, "check", lambda: None)
    monkeypatch.setattr(helper, "prepare", lambda: {})
    monkeypatch.setattr(helper, "start_stack", lambda _: None)
    monkeypatch.setattr(
        helper.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess([], 0)
    )

    def compose(*args: str, **kwargs: object) -> str:
        calls.append(args)
        return "1000" if args[-2:] == ("id", "-u") else ""

    monkeypatch.setattr(helper, "compose", compose)
    helper.start()
    assert not any("sync" in call for call in calls)
    assert any("node" in call for call in calls) == (profile in {"node", "mixed"})


@pytest.mark.parametrize("make_name", ["Makefile", "makefile", "GNUmakefile"])
def test_historical_check_and_default_are_preserved(
    tmp_path: Path, adopter: ModuleType, make_name: str
) -> None:
    content = b"# historical\r\ncheck:\r\n\t@echo original-check\r\n"
    repo = repository(tmp_path / "app", {make_name: content.decode()})
    # Write literal CRLF before the final existing-history commit.
    (repo / make_name).write_bytes(content)
    command(repo, "git", "add", ".")
    command(repo, "git", "commit", "--allow-empty", "-m", "preserve make bytes")
    adopter.apply(repo, adopter.plan(repo, adopter.audit(repo), "generic", "both"))
    assert (repo / make_name).read_bytes().startswith(content)
    assert "original-check" in command(repo, "make")
    assert "original-check" in command(repo, "make", "check")
    assert "No application command" in command(repo, "make", "template-check")


def test_dynamic_make_requires_review(tmp_path: Path, adopter: ModuleType) -> None:
    repo = repository(
        tmp_path / "app", {"Makefile": "TARGET := agent\n$(TARGET):\n\t@echo historical\n"}
    )
    entries = adopter.plan(repo, adopter.audit(repo), "generic", "both")
    with pytest.raises(ValueError, match="Blocking conflicts"):
        adopter.apply(repo, entries)
    assert command(repo, "git", "status", "--porcelain") == ""


@pytest.mark.parametrize(
    "manifest", ["requirements.txt", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "pdm.lock"]
)
def test_legacy_python_detection(tmp_path: Path, adopter: ModuleType, manifest: str) -> None:
    repo = repository(tmp_path / "app", {f"backend/{manifest}": "# legacy\n"})
    assert adopter.audit(repo)["profile"] == "python"
