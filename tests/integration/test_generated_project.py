"""Real generated application workflows; structural matrices stay in FAST."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from test_template import (
    command,
    git_identity_environment,
)
from test_template import (
    generate_locked as generate,
)

pytestmark = pytest.mark.integration


def test_custom_names(tmp_path: Path) -> None:
    project = generate(tmp_path, project_name="Flood Extent", package_name="flood_tools")
    assert project.name == "flood-extent"
    assert (project / "src/flood_tools/__init__.py").exists()
    command(project, "uv", "build")


def test_default_execution(tmp_path: Path) -> None:
    project = generate(tmp_path)
    assert (project / "uv.lock").is_file()
    command(project, "make", "setup")
    original = "# preserve local settings\nAGENT_APP_PORT=19000\n"
    (project / ".env").write_text(original)
    # The init idempotence test covers repeated make setup; here repeat only its helper.
    command(project, "uv", "run", "--no-sync", "python", "scripts/setup.py")
    assert (project / ".env").read_text() == original
    command(project, "uv", "sync", "--locked")
    command(project, "make", "help")
    command(project, "make", "check")
    command(project, "make", "build")
    command(project, "make", "docs-build")
    # Notebook round-trip reuses this already synchronized, independently owned environment.
    script = project / "notebooks/01_example.py"
    command(project, "uv", "run", "jupytext", "--to", "ipynb", str(script))
    command(project, "uv", "run", "jupytext", "--sync", str(script.with_suffix(".ipynb")))
    command(project, "uv", "run", "python", str(script))
    wheel = next((project / "dist").glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "my_python_project/__init__.py" in archive.namelist()
    assert list((project / "dist").glob("*.tar.gz"))
    command(project, "uv", "run", "python", "-m", "my_python_project")
    (project / "data/raw/keep.txt").write_text("precious")
    (project / "artifacts/keep.txt").write_text("precious")
    command(project, "make", "clean")
    assert (project / "data/raw/keep.txt").read_text() == "precious"
    assert (project / "artifacts/keep.txt").read_text() == "precious"


# Codex alone has the default smoke; both covers both official harnesses, custom
# has distinct empty-AGENTS code, and none/minimal covers disabled docs/notebooks.
# All five providers and all option rows still have independent structural tests.
@pytest.mark.parametrize(
    ("provider", "options"),
    [
        ("both", {}),
        ("custom", {}),
        (
            "none",
            {
                "dev_container_runtime": "none",
                "enable_docs": "no",
                "enable_notebooks": "no",
                "ci_provider": "none",
            },
        ),
    ],
)
def test_provider_workflow(tmp_path: Path, provider: str, options: dict[str, str]) -> None:
    project = generate(tmp_path, coding_agent=provider, **options)
    # init already calls setup; do not synchronize the same environment twice.
    command(project, "make", "init", env=git_identity_environment(tmp_path))
    command(project, "make", "check")
    command(project, "make", "build")
    if options.get("enable_docs", "yes") == "yes":
        command(project, "make", "docs-build")
