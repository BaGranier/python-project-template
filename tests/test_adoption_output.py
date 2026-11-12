"""Public adoption output levels share the same plan and preserve read-only previews."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from test_adoption import repository
from test_template import ROOT, load_module


@pytest.fixture
def adopter() -> ModuleType:
    return load_module(ROOT / "scripts/adopt.py", "adopter_output_test")


@pytest.fixture
def monorepo(tmp_path: Path) -> Path:
    return repository(
        tmp_path / "monorepo",
        {
            "services/pdf-engine/pyproject.toml": (
                '[project]\nname="legacy"\nversion="0.1"\n[tool.pytest.ini_options]\n[tool.ruff]\n'
            ),
            "apps/web/package.json": (
                '{"packageManager":"pnpm@9.0.0","scripts":{"lint":"echo lint"}}'
            ),
            "apps/web/pnpm-lock.yaml": "lockfileVersion: 9\n",
            "Dockerfile": "FROM scratch\n",
            "docker-compose.yml": "services: {}\n",
            ".github/workflows/ci.yml": "name: existing\n",
            "Makefile": "legacy:\n\t@echo preserved\n",
            ".gitignore": "legacy-cache/\n",
            ".env.example": "LEGACY=yes\n",
        },
    )


def run(
    repo: Path, target: str = "adopt-dry-run", **flags: str
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key not in {"VERBOSE", "DEBUG"}}
    return subprocess.run(
        ["make", target, f"REPO={repo}", *[f"{key}={value}" for key, value in flags.items()]],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def snapshot(repo: Path) -> dict[str, tuple[bytes, int]]:
    return {
        str(path.relative_to(repo)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in repo.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("mode", ["default", "verbose", "debug", "diff"])
def test_preview_levels_are_read_only(monorepo: Path, mode: str) -> None:
    before = snapshot(monorepo)
    flags = {"verbose": {"VERBOSE": "1"}, "debug": {"DEBUG": "1"}}.get(mode, {})
    result = run(monorepo, "adopt-diff" if mode == "diff" else "adopt-dry-run", **flags)
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for text in ("Repository", "Detected stack", "Plan", "ADD", "MERGE", "REVIEW", "Result"):
        assert text in out
    assert "working tree: clean" in out
    assert "HEAD:" in out
    assert "No files modified." in out
    if mode == "default":
        assert len(out.splitlines()) < 200
        assert '"python_sections"' not in out
        assert "--- " not in out and "+++ " not in out
        assert "Host-controlled rootless sandbox" not in out
        assert "make adopt REPO=" in out
        assert "BLOCK: 0" in out and "No blocking conflicts" in out
    if mode in {"verbose", "debug"}:
        assert "services/pdf-engine/pyproject.toml" in out
        assert "package manager: pnpm" in out
        assert "pytest, ruff" in out
        assert "--- a/Makefile" in out
        assert "Preserved; application configuration" in out
    if mode == "verbose":
        assert '"python_sections"' not in out
        assert "Host-controlled rootless sandbox" not in out
    if mode == "debug":
        assert '"python_sections"' in out
        assert '"candidate_plan"' in out
        assert '"sha256"' in out
    if mode == "diff":
        assert "--- /dev/null" in out and "+++ b/scripts/agent.py" in out
        assert "Host-controlled rootless sandbox" in out
    assert snapshot(monorepo) == before
    assert not (monorepo / ".template").exists()


def test_actual_adoption_is_concise(monorepo: Path) -> None:
    result = run(monorepo, "adopt")
    assert result.returncode == 0, result.stderr
    out = result.stdout
    for text in (
        "Adoption completed successfully.",
        "Files added:",
        "Files modified:",
        "Existing files preserved:",
        "REVIEW",
        "git status --short",
        "git diff --cached",
        "make agent-start",
    ):
        assert text in out
    assert len(out.splitlines()) < 200
    assert '"python_sections"' not in out and "+++ " not in out
    assert "No files modified" not in out
    assert (monorepo / ".template/adoption.json").is_file()
    assert (monorepo / "Dockerfile").read_text() == "FROM scratch\n"


def test_dirty_preview_and_application(monorepo: Path) -> None:
    (monorepo / "Dockerfile").write_text("dirty\n")
    before = snapshot(monorepo)
    preview = run(monorepo)
    assert preview.returncode == 0
    assert "working tree: dirty" in preview.stdout
    assert "requires a clean working tree" in preview.stdout
    assert "No files modified." in preview.stdout
    actual = run(monorepo, "adopt")
    assert actual.returncode != 0
    assert "Adoption blocked" in actual.stderr and "Commit or stash" in actual.stderr
    assert "Traceback" not in actual.stderr
    assert snapshot(monorepo) == before


def test_all_blocks_are_visible(monorepo: Path, adopter: ModuleType) -> None:
    entries = adopter.plan(monorepo, adopter.audit(monorepo), "mixed", "both")
    conflicts = [e.name for e in entries if e.action == "ADD"][:12]
    for name in conflicts:
        path = monorepo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("unrelated existing infrastructure\n")
    (monorepo / "Makefile").write_text("agent:\n\t@echo old\n")
    (monorepo / ".env.example").write_text("AGENT_APP_PORT=9000\n")
    subprocess.run(["git", "add", "."], cwd=monorepo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "existing infrastructure"],
        cwd=monorepo,
        check=True,
        capture_output=True,
    )
    before = snapshot(monorepo)
    result = run(monorepo, "adopt")
    assert result.returncode != 0
    for name in [*conflicts, "Makefile", ".env.example"]:
        assert name in result.stderr
    assert "agent" in result.stderr
    assert "existing: 9000" in result.stderr and "template: 18000" in result.stderr
    assert "No files modified." in result.stderr
    assert "Traceback" not in result.stderr
    preview = run(monorepo)
    assert "BLOCK:" in preview.stdout
    assert "Adoption blocked" in preview.stderr
    assert snapshot(monorepo) == before


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_false_flags_are_not_verbose(monorepo: Path, value: str) -> None:
    result = run(monorepo, VERBOSE=value, DEBUG=value)
    assert result.returncode == 0
    assert "Detection details" not in result.stdout
    assert '"candidate_plan"' not in result.stdout


@pytest.mark.parametrize("value", ["1", "true", "yes"])
def test_boolean_flags(value: str, adopter: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERBOSE", value)
    assert adopter.environment_flag("VERBOSE") is True
    monkeypatch.setenv("VERBOSE", "perhaps")
    with pytest.raises(ValueError, match="VERBOSE must be"):
        adopter.environment_flag("VERBOSE")


def test_native_flags_and_node_commands(tmp_path: Path) -> None:
    repo = repository(
        tmp_path / "node",
        {"package.json": '{"scripts":{"lint":"echo lint"}}', "package-lock.json": "{}"},
    )
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/adopt.py"),
            "--repo",
            str(repo),
            "--dry-run",
            "--verbose",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "lint: npm run lint" in result.stdout
    assert "setup: npm ci" in result.stdout


def test_truncation_never_truncates_blocks(
    adopter: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    names = [f"file-{i}" for i in range(20)]
    adopter.render_paths("ADD", names)
    out = capsys.readouterr().out
    assert "file-0" in out and "file-19" not in out and "14 more" in out
    adopter.render_paths("ADD", names, verbose=True)
    assert "file-19" in capsys.readouterr().out
    adopter.render_blocks(
        [adopter.Entry(name, "REVIEW", b"old", b"new", "CONFLICT", True) for name in names]
    )
    err = capsys.readouterr().err
    assert all(name in err for name in names)


@pytest.mark.parametrize("debug", [False, True])
def test_unexpected_errors_only_trace_in_debug(
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    debug: bool,
) -> None:
    repo = repository(tmp_path / "unexpected", {"README.md": "existing source"})
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.delenv("VERBOSE", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["adopt", "--repo", str(repo), "--dry-run"] + (["--debug"] if debug else []),
    )

    def fail(_: Path) -> None:
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr(adopter, "audit", fail)
    with pytest.raises(SystemExit):
        adopter.main()
    err = capsys.readouterr().err
    assert "Adoption failed" in err and "DEBUG=1" in err
    assert ("Traceback" in err) is debug


def test_rollback_is_visible_in_application_output(
    monorepo: Path,
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    before = snapshot(monorepo)
    original = Path.open

    def fail(path: Path, *args: object, **kwargs: object) -> object:
        if path == monorepo / "scripts/project.py" and args == ("xb",):
            raise OSError("simulated write failure")
        return original(path, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(Path, "open", fail)
    monkeypatch.setattr(sys, "argv", ["adopt", "--repo", str(monorepo)])
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.setenv("VERBOSE", "0")
    with pytest.raises(SystemExit):
        adopter.main()
    err = capsys.readouterr().err
    assert "write failure" in err and "rollback completed" in err
    assert "Traceback" not in err
    assert snapshot(monorepo) == before


def test_already_adopted_explains_why_nothing_is_written(monorepo: Path) -> None:
    assert run(monorepo, "adopt").returncode == 0
    subprocess.run(["git", "add", "."], cwd=monorepo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "reviewed adoption"], cwd=monorepo, check=True, capture_output=True
    )
    before = snapshot(monorepo)
    result = run(monorepo, "adopt")
    assert result.returncode == 0
    assert "already adopted" in result.stdout
    assert "No changes applied." in result.stdout
    assert "Adoption blocked" not in result.stderr
    assert snapshot(monorepo) == before


def test_unsafe_symlink_is_a_concise_error(monorepo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (monorepo / "scripts").symlink_to(outside, target_is_directory=True)
    subprocess.run(["git", "add", "."], cwd=monorepo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "existing symlink"], cwd=monorepo, check=True, capture_output=True
    )
    result = run(monorepo, "adopt")
    assert result.returncode != 0
    assert "Unsafe destination" in result.stderr and "Traceback" not in result.stderr
    assert list(outside.iterdir()) == []
    assert (monorepo / "scripts").is_symlink()
    assert not (monorepo / ".template").exists()
