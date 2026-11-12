"""Bootstrap/setup and public generator CLI integration, with independent repositories."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from test_template import (
    ROOT,
    command,
    configure_agent,
    git_identity_environment,
    initialize,
)
from test_template import (
    generate_locked as generate,
)

pytestmark = pytest.mark.integration


def test_init_and_idempotence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = generate(tmp_path)
    env = git_identity_environment(tmp_path)
    assert "initialized" in command(project, "make", "init", env=env)
    assert (project / ".git").is_dir()
    assert Path(command(project, "git", "rev-parse", "--show-toplevel").strip()) == project
    assert (
        command(project, "git", "log", "-1", "--format=%s").strip() == "chore: initialize project"
    )
    assert (project / ".venv/bin/python").exists()
    assert (project / ".git/hooks/pre-commit").exists()
    first = command(project, "git", "rev-parse", "HEAD")
    (project / ".env").write_text("KEEP_LOCAL=yes\n")
    (project / "user-change.txt").write_text("do not commit")
    output = command(project, "make", "init", env=env)
    assert "Initial commit: already present" in output
    assert command(project, "git", "rev-parse", "HEAD") == first
    assert (project / ".env").read_text() == "KEEP_LOCAL=yes\n"
    assert "?? user-change.txt" in command(project, "git", "status", "--porcelain")
    (project / "user-change.txt").unlink()
    helper = configure_agent(project)
    monkeypatch.setattr(helper, "running_containers", lambda: False)
    assert helper.prepare()["base"] == first.strip()


def test_init_inside_parent_repository(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / ".gitignore").write_text("my-python-project/\n")
    initialize(parent)
    before = command(parent, "git", "rev-parse", "HEAD")
    index = (parent / ".git/index").read_bytes()
    project = generate(parent)
    helper = configure_agent(project)
    with pytest.raises(ValueError, match="parent Git repository"):
        helper.prepare()
    assert not (project / ".git").exists()
    output = command(project, "make", "init", env=git_identity_environment(tmp_path))
    assert "Parent Git repository detected" in output
    assert Path(command(project, "git", "rev-parse", "--show-toplevel").strip()) == project
    assert (project / ".git").is_dir()
    assert command(parent, "git", "rev-parse", "HEAD") == before
    assert command(parent, "git", "status", "--porcelain").strip() == ""
    assert (parent / ".git/index").read_bytes() == index


def test_init_missing_identity_and_resume(tmp_path: Path) -> None:
    project = generate(tmp_path)
    result = subprocess.run(
        ["make", "init"],
        cwd=project,
        capture_output=True,
        text=True,
        env=git_identity_environment(tmp_path, configured=False),
        check=False,
    )
    assert result.returncode != 0
    assert "Git identity is not configured" in result.stderr
    assert 'git config --global user.name "Your Name"' in result.stderr
    assert "make init" in result.stderr
    assert (project / ".git").is_dir()
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=project, capture_output=True, check=False
    )
    assert head.returncode != 0
    command(project, "make", "init", env=git_identity_environment(tmp_path))
    assert command(project, "git", "rev-list", "--count", "HEAD").strip() == "1"


def test_demo_generation_and_explicit_cleanup(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.mkdir()
    for name in ("Makefile", "cookiecutter.json"):
        shutil.copyfile(ROOT / name, template / name)
    for name in ("hooks", "scripts", "{{cookiecutter.project_slug}}"):
        shutil.copytree(ROOT / name, template / name, ignore=shutil.ignore_patterns("__pycache__"))
    neighbor = tmp_path / "user-project"
    neighbor.mkdir()
    (neighbor / "keep.txt").write_text("preserve")
    output = command(template, "make", "generate-default")
    assert "validation only" in output and "disposable and ignored by Git" in output
    assert "generated/my-python-project" in output
    project = template / "generated/my-python-project"
    assert project.is_dir()
    (project / "user-note.txt").write_text("not silently overwritten")
    repeated = subprocess.run(
        ["make", "generate-default"], cwd=template, capture_output=True, text=True, check=False
    )
    assert repeated.returncode != 0
    assert (project / "user-note.txt").exists()
    command(template, "make", "clean-generated")
    assert not (template / "generated").exists()
    assert (neighbor / "keep.txt").read_text() == "preserve"
    (template / "generated").symlink_to(neighbor, target_is_directory=True)
    refused = subprocess.run(
        ["make", "clean-generated"], cwd=template, capture_output=True, text=True, check=False
    )
    assert refused.returncode != 0
    assert (neighbor / "keep.txt").read_text() == "preserve"


def test_setup_installs_git_hook(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    command(project, "make", "setup")
    assert (project / ".git/hooks/pre-commit").is_file()
    command(project, "uv", "run", "pre-commit", "run", "--all-files")
    assert command(project, "git", "status", "--porcelain").strip() == ""
