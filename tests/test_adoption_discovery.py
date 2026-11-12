"""Discovery sees source/configuration and adopted repositories bypass planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from test_adoption import repository
from test_adoption_output import run, snapshot
from test_template import ROOT, load_module


@pytest.fixture
def adopter() -> ModuleType:
    return load_module(ROOT / "scripts/adopt.py", "adopter_discovery_test")


EXCLUDED = [
    ".git/dependencies",
    ".agent",
    ".template",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".cargo/registry",
    ".cargo/git",
    "target",
    "dist",
    "build",
    "coverage",
    "htmlcov",
    ".generated",
    "generated",
    "vendor",
    "data/output",
    "outputs",
    "artifacts",
    "qa-assets/baseline",
    "qa-assets/baselines",
    "snapshots",
    "cache",
    "tmp",
    "temp",
]
SOURCE = {
    "apps/web/package.json": "{}",
    "apps/desktop/package.json": "{}",
    "apps/desktop/src-tauri/Cargo.toml": '[package]\nname="desktop"\n',
    "services/api/pyproject.toml": '[project]\nname="api"\n',
    ".cargo/config.toml": '[build]\ntarget-dir="target"\n',
    "data/source/package.json": "{}",
    ".github/workflows/ci.yml": "name: source CI\n",
    "compose.yaml": "services: {}\n",
    ".devcontainer/devcontainer.json": "{}",
}


def test_all_discovery_consumers_ignore_dependency_and_output_trees(
    tmp_path: Path, adopter: ModuleType
) -> None:
    repo = repository(tmp_path / "source", SOURCE)
    # Invalid manifests prove the scanner never even parses dependencies.
    for prefix in EXCLUDED:
        for depth in ("", "nested/"):
            base = repo / depth / prefix
            base.mkdir(parents=True, exist_ok=True)
            for name in (
                "Cargo.toml",
                "package.json",
                "pyproject.toml",
                ".gitlab-ci.yml",
                "Dockerfile",
                "compose.yaml",
                "collision.mk",
            ):
                (base / name).write_text("not valid application configuration")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "package.json").write_text("invalid")
    (repo / "linked-dependencies").symlink_to(outside, target_is_directory=True)
    visible = {str(p) for p in adopter.repository_files(repo)}
    assert set(SOURCE) <= visible
    assert not any("collision.mk" in p for p in visible)
    report = adopter.audit(repo)
    assert report["profile"] == "mixed"
    assert set(report["node"]) == {
        "apps/web/package.json",
        "apps/desktop/package.json",
        "data/source/package.json",
    }
    assert set(report["python_sections"]) == {"services/api/pyproject.toml"}
    assert "apps/desktop/src-tauri/Cargo.toml" in report["detected"]
    assert ".gitlab-ci.yml" not in " ".join(report["detected"])
    assert set(report["detected"]) <= set(SOURCE)
    entries = adopter.plan(repo, report, "mixed", "both")
    assert not any(e.blocking for e in entries)
    assert not any("collision.mk" in e.name for e in entries)
    out = run(repo).stdout
    assert "GitHub Actions" in out and "GitLab CI" not in out
    assert ".cargo/registry" not in out
    assert out.count("No files modified.") == 1


@pytest.mark.parametrize("mode", ["adopt-dry-run", "adopt-diff", "adopt"])
@pytest.mark.parametrize("modern", [True, False])
def test_adopted_short_circuit(
    tmp_path: Path,
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    modern: bool,
) -> None:
    metadata = {"template": "python-project-template", "adopted": True}
    if modern:
        metadata.update(
            profile="mixed",
            coding_agent="both",
            infrastructure_version=1,
            template_revision="abc123",
        )
    repo = repository(
        tmp_path / "adopted",
        {
            ".template/adoption.json": json.dumps(metadata),
            "package.json": "invalid; must not be parsed",
            "Makefile": "include uninspected.mk\n$(DYNAMIC):\n",
        },
    )
    before = snapshot(repo)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("adopted repositories must bypass discovery and planning")

    for name in ("audit", "repository_files", "plan", "render", "apply"):
        monkeypatch.setattr(adopter, name, forbidden)
    args = ["adopt", "--repo", str(repo)]
    args += {"adopt-dry-run": ["--dry-run"], "adopt-diff": ["--diff"], "adopt": []}[mode]
    monkeypatch.setattr(sys, "argv", args)
    adopter.main()
    captured = capsys.readouterr()
    assert not captured.err
    assert "already adopted" in captured.out
    assert "working tree: clean" in captured.out
    for text in ("Plan:", "ADD:", "MERGE:", "SKIP:", "BLOCK:"):
        assert text not in captured.out
    assert captured.out.count("No files modified.") == (mode != "adopt")
    assert ("Profile: mixed" in captured.out) == modern
    assert snapshot(repo) == before
    # The public Make interface has the same idempotent, read-only result.
    result = run(repo, mode)
    assert result.returncode == 0, result.stderr
    assert "already adopted" in result.stdout
    assert snapshot(repo) == before


@pytest.mark.parametrize(
    "content",
    [
        "{",
        "[]",
        "{}",
        '{"adopted":false}',
        '{"template":"other","adopted":true}',
        '{"template":"python-project-template","adopted":true,"infrastructure_version":false}',
    ],
)
def test_invalid_metadata_blocks_before_discovery(
    tmp_path: Path,
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: str,
) -> None:
    repo = repository(tmp_path / "invalid", {".template/adoption.json": content})
    before = snapshot(repo)
    monkeypatch.setattr(sys, "argv", ["adopt", "--repo", str(repo), "--dry-run"])
    monkeypatch.setattr(adopter, "audit", lambda _: pytest.fail("must not discover"))
    with pytest.raises(SystemExit) as exc:
        adopter.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Adoption metadata is present but invalid" in err
    assert "Manual review required" in err and "Traceback" not in err
    assert snapshot(repo) == before


@pytest.mark.parametrize("blocked", [True, False])
def test_preview_footer_once(tmp_path: Path, blocked: bool) -> None:
    repo = repository(
        tmp_path / "footer",
        {"scripts/agent.py": "collision"} if blocked else {"README.md": "existing source"},
    )
    result = run(repo)
    assert (result.stdout + result.stderr).count("No files modified.") == 1
    if blocked:
        assert "Adoption blocked" in result.stderr


def test_ignored_trees_are_pruned_before_descent(
    tmp_path: Path,
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path / "pruning", SOURCE)
    for prefix in (".cargo/registry", "node_modules", ".venv"):
        base = repo / prefix
        base.mkdir(parents=True)
        for i in range(1000):
            dependency = base / f"dependency-{i}"
            dependency.mkdir()
            (dependency / "package.json").write_text("{}")
    real_scandir = adopter.os.scandir
    visited = []

    def scandir(path: str) -> object:
        relative = Path(path).relative_to(repo)
        assert not adopter.ignored_directory(relative), f"entered ignored tree: {relative}"
        visited.append(relative)
        return real_scandir(path)

    monkeypatch.setattr(adopter.os, "scandir", scandir)
    assert "apps/desktop/src-tauri/Cargo.toml" in map(str, adopter.repository_files(repo))
    assert len(visited) < 20  # Directory count, not a fragile wall-clock assertion.


def test_unreadable_metadata_requires_review(
    tmp_path: Path,
    adopter: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = repository(tmp_path / "unreadable", {".template/adoption.json": "{}"})

    def unreadable(path: Path) -> str:
        raise PermissionError("unreadable metadata")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(ValueError, match="metadata is present but invalid.*Manual review"):
        adopter.adoption_metadata(repo)


def test_metadata_symlink_is_not_followed(tmp_path: Path, adopter: ModuleType) -> None:
    repo = repository(tmp_path / "symlink", {"README.md": "source"})
    outside = tmp_path / "metadata.json"
    outside.write_text('{"template":"python-project-template","adopted":true}')
    (repo / ".template").mkdir()
    (repo / ".template/adoption.json").symlink_to(outside)
    with pytest.raises(ValueError, match="Unsafe destination"):
        adopter.adoption_metadata(repo)
