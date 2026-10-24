"""Exercise rendered repositories; template text alone is not the deliverable."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType

import jupytext
import pytest
import yaml
from cookiecutter.exceptions import FailedHookException
from cookiecutter.main import cookiecutter

ROOT = Path(__file__).resolve().parents[1]


def command(path: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        list(args), cwd=path, env=env, text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def generate(destination: Path, **options: str) -> Path:
    return Path(
        cookiecutter(str(ROOT), no_input=True, output_dir=str(destination), extra_context=options)
    )


@pytest.fixture(scope="session")
def default_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(tmp_path_factory.mktemp("default"))


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_structure(default_project: Path) -> None:
    for name in (
        "src/my_python_project/__init__.py",
        "tests/unit/test_package.py",
        "tests/integration/test_cli.py",
        "docs/agent-security.md",
        "notebooks/01_example.py",
        "containers/Containerfile",
        "containers/compose.yaml",
        "containers/compose.agent.yaml",
        "scripts/agent.py",
        "AGENTS.md",
        ".github/workflows/ci.yml",
        ".github/workflows/pages.yml",
        "uv.lock",
    ):
        assert (default_project / name).is_file(), name
    metadata = tomllib.loads((default_project / "pyproject.toml").read_text())
    assert metadata["build-system"]["build-backend"] == "uv_build"
    assert set(metadata["dependency-groups"]) == {"test", "lint", "notebook", "docs", "dev"}
    for path in default_project.rglob("*"):
        if path.is_file():
            assert "{{cookiecutter" not in path.read_text()
    for path in default_project.rglob("*.py"):
        ast.parse(path.read_text())


@pytest.mark.parametrize(
    "options",
    [
        {"dev_container_runtime": "docker"},
        {"dev_container_runtime": "none"},
        {"enable_agent": "no"},
        {"enable_notebooks": "no"},
        {"enable_docs": "no"},
        {"ci_provider": "gitlab"},
        {"ci_provider": "none"},
        {
            "dev_container_runtime": "none",
            "enable_agent": "no",
            "enable_docs": "no",
            "enable_notebooks": "no",
            "ci_provider": "none",
        },
    ],
)
def test_option_matrix(tmp_path: Path, options: dict[str, str]) -> None:
    project = generate(tmp_path, **options)
    agent = options.get("enable_agent", "yes") == "yes"
    docs = options.get("enable_docs", "yes") == "yes"
    notebooks = options.get("enable_notebooks", "yes") == "yes"
    runtime = options.get("dev_container_runtime", "podman")
    ci = options.get("ci_provider", "github")
    assert (project / "scripts/agent.py").exists() == agent
    assert (project / "containers/compose.agent.yaml").exists() == agent
    assert (project / "containers/compose.yaml").exists() == (runtime != "none")
    assert (project / "containers").exists() == (agent or runtime != "none")
    assert (project / "docs").exists() == docs
    assert (project / "mkdocs.yml").exists() == docs
    assert (project / "notebooks").exists() == notebooks
    assert (project / "jupytext.toml").exists() == notebooks
    assert (project / ".github").exists() == (ci == "github")
    assert (project / ".gitlab-ci.yml").exists() == (ci == "gitlab")
    help_text = command(project, "make", "help")
    assert ("agent-start" in help_text) == agent
    assert ("docs-build" in help_text) == docs
    assert ("notebook " in help_text) == notebooks
    assert ("dev-up" in help_text) == (runtime != "none")
    if runtime != "none":
        assert f"RUNTIME := {runtime}" in (project / "Makefile").read_text()
    if not agent:
        assert (
            "AS agent" not in (project / "containers/Containerfile").read_text()
            if (project / "containers/Containerfile").exists()
            else True
        )
    command(project, "uv", "run", "ruff", "check", ".")
    command(project, "uv", "run", "ruff", "format", "--check", ".")
    command(project, "uv", "run", "mypy")
    if docs:
        command(project, "make", "docs-build")


@pytest.mark.parametrize(
    "options",
    [
        {"project_slug": "../../escape"},
        {"project_slug": "bad;command"},
        {"package_name": "class"},
        {"package_name": "bad-name"},
        {"python_version": "3.11"},
        {"python_version": "3.12;command"},
        {"author_name": "bad\nname"},
        {"description": "'''); raise RuntimeError('injection'); #"},
    ],
)
def test_invalid_input(tmp_path: Path, options: dict[str, str]) -> None:
    with pytest.raises(FailedHookException):
        generate(tmp_path, **options)
    assert not list(tmp_path.iterdir())


def test_custom_names(tmp_path: Path) -> None:
    project = generate(tmp_path, project_name="Flood Extent", package_name="flood_tools")
    assert project.name == "flood-extent"
    assert (project / "src/flood_tools/__init__.py").exists()
    command(project, "uv", "build")


def test_default_execution(default_project: Path) -> None:
    project = default_project
    command(project, "make", "setup")
    original = "# preserve local settings\nAGENT_APP_PORT=19000\n"
    (project / ".env").write_text(original)
    command(project, "make", "setup")
    assert (project / ".env").read_text() == original
    command(project, "uv", "sync", "--locked")
    command(project, "make", "help")
    command(project, "make", "check")
    command(project, "make", "build")
    command(project, "make", "docs-build")
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


def test_jupytext(default_project: Path) -> None:
    script = default_project / "notebooks/01_example.py"
    notebook = jupytext.read(script)
    assert notebook.metadata["jupytext"]["text_representation"]["format_name"] == "percent"
    assert len(notebook.cells) >= 2
    ast.parse(script.read_text())
    command(default_project, "uv", "run", "jupytext", "--to", "ipynb", str(script))
    command(default_project, "uv", "run", "jupytext", "--sync", str(script.with_suffix(".ipynb")))
    command(default_project, "uv", "run", "python", str(script))


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_environment(
    default_project: Path, shell: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} unavailable")
    command(default_project, "uv", "sync")
    helper = load_module(default_project / "scripts/shell.py", "shell_helper")
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    executable, env = helper.shell_environment(default_project, shell)
    assert env["VIRTUAL_ENV"] == str(default_project / ".venv")
    assert env["PATH"].split(os.pathsep)[0] == str(default_project / ".venv/bin")
    flags = ["--norc", "--noprofile"] if shell == "bash" else ["-f"]
    result = command(default_project, executable, *flags, "-c", "command -v python", env=env)
    assert result.strip() == str(default_project / ".venv/bin/python")
    with pytest.raises(ValueError, match="bash or zsh"):
        helper.shell_environment(default_project, "sh")


def initialize(project: Path) -> None:
    command(project, "git", "init", "-b", "main")
    command(project, "git", "config", "user.email", "test@example.invalid")
    command(project, "git", "config", "user.name", "Template Test")
    command(project, "git", "add", ".")
    command(project, "git", "-c", "core.hooksPath=/dev/null", "commit", "-m", "initial")


def configure_agent(project: Path) -> ModuleType:
    helper = load_module(project / "scripts/agent.py", "agent_helper")
    return helper


def test_git_isolation_and_apply(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    result = helper.prepare()
    clone = Path(result["workspace"])
    assert (project / ".git").is_dir() and (clone / ".git").is_dir()
    assert not (clone / ".git/objects/info/alternates").exists()
    assert command(clone, "git", "remote").strip() == ""
    main_objects = {p.name: p.stat().st_ino for p in (project / ".git/objects").glob("*/*")}
    for path in (clone / ".git/objects").glob("*/*"):
        if path.is_file() and path.name in main_objects:
            assert path.stat().st_ino != main_objects[path.name]
    file = "src/my_python_project/__init__.py"
    original = (project / file).read_text()
    (clone / file).unlink()
    assert (project / file).read_text() == original
    (clone / file).write_text(original + '\nAGENT_CHANGE = "reviewed"\n')
    command(clone, "git", "add", ".")
    command(clone, "git", "commit", "-m", "feat: agent example")
    diff = command(project, "make", "agent-diff")
    assert "feat: agent example" in diff and "AGENT_CHANGE" in diff
    command(project, "make", "agent-apply")
    assert "AGENT_CHANGE" in (project / file).read_text()
    assert command(project, "git", "status", "--porcelain").strip() == ""


def test_git_safety_refusals(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    (project / "dirty.txt").write_text("unsaved")
    with pytest.raises(ValueError, match="Uncommitted"):
        helper.prepare()
    (project / "dirty.txt").unlink()
    helper.prepare()
    with pytest.raises(ValueError, match="No agent commits"):
        helper.apply()
    (helper.WORKSPACE / "dirty.txt").write_text("unsaved")
    with pytest.raises(ValueError, match="Uncommitted"):
        helper.apply()
    (helper.WORKSPACE / "dirty.txt").unlink()
    command(project, "git", "commit", "--allow-empty", "-m", "primary advanced")
    with pytest.raises(ValueError, match="Primary HEAD"):
        helper.apply()
    assert (helper.WORKSPACE / ".git").is_dir()


def test_security_configuration(default_project: Path) -> None:
    service = yaml.safe_load((default_project / "containers/compose.agent.yaml").read_text())[
        "services"
    ]["agent"]
    assert service["user"] == "1000:1000"
    assert service["userns_mode"].startswith("keep-id")
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert not service.get("privileged")
    assert service.get("network_mode") != "host"
    assert all(port.startswith("127.0.0.1:") for port in service["ports"])
    binds = [volume for volume in service["volumes"] if ":/workspace" in volume]
    assert len(binds) == 1 and "AGENT_WORKSPACE" in binds[0]
    assert all(".sock" not in volume and "$HOME" not in volume for volume in service["volumes"])
    helper = configure_agent(default_project)
    env = helper.environment()
    assert "OPENAI_API_KEY" not in env
    assert env["AGENT_WORKSPACE"] == str(default_project / ".agent/workspace")


def test_hostile_git_config_not_executed(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    helper.prepare()
    marker = project / "must-not-exist"
    command(helper.WORKSPACE, "git", "config", "core.fsmonitor", f"touch {marker}")
    helper.diff()
    assert not marker.exists()
    (helper.WORKSPACE / ".git/evil-link").symlink_to(project / ".git")
    with pytest.raises(ValueError, match="symlinks"):
        helper.state()


def test_hook_without_uv(tmp_path: Path) -> None:
    # Render the hook in isolation with a deliberately empty PATH.
    from jinja2 import Environment

    context = json.loads((ROOT / "cookiecutter.json").read_text())
    context.update({key: value[0] for key, value in context.items() if isinstance(value, list)})
    text = (
        Environment()
        .from_string((ROOT / "hooks/post_gen_project.py").read_text())
        .render(cookiecutter=context)
    )
    script = tmp_path / "hook.py"
    script.write_text(text)
    result = command(tmp_path, sys.executable, str(script), env={"PATH": ""})
    assert "uv lock was not generated." in result
    assert "make setup" in result


def test_agent_rootless_rejection(default_project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    helper = configure_agent(default_project)
    monkeypatch.setattr(helper.shutil, "which", lambda _: "/usr/bin/podman")
    monkeypatch.setattr(
        helper, "run", lambda *args, **kwargs: '{"host":{"security":{"rootless":false}}}'
    )
    with pytest.raises(ValueError, match="Rootless Podman required"):
        helper.check()


def test_setup_installs_git_hook(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    command(project, "make", "setup")
    assert (project / ".git/hooks/pre-commit").is_file()
    command(project, "uv", "run", "pre-commit", "run", "--all-files")
    assert command(project, "git", "status", "--porcelain").strip() == ""


def test_yaml_configuration(default_project: Path) -> None:
    for pattern in ("*.yml", "*.yaml"):
        for path in default_project.rglob(pattern):
            if ".venv" not in path.parts:
                assert yaml.safe_load(path.read_text()) is not None


def test_cruft_create_check_diff(tmp_path: Path) -> None:
    source = tmp_path / "template"
    source.mkdir()
    for name in ("cookiecutter.json", "README.md"):
        shutil.copyfile(ROOT / name, source / name)
    for name in ("hooks", "{{cookiecutter.project_slug}}"):
        shutil.copytree(ROOT / name, source / name)
    initialize(source)
    destination = tmp_path / "output"
    command(
        ROOT,
        sys.executable,
        "-m",
        "cruft",
        "create",
        str(source),
        "--no-input",
        "--output-dir",
        str(destination),
    )
    project = destination / "my-python-project"
    assert json.loads((project / ".cruft.json").read_text())["commit"]
    command(project, sys.executable, "-m", "cruft", "check")
    command(project, sys.executable, "-m", "cruft", "diff")
    command(project, sys.executable, "-m", "cruft", "update", "--skip-apply-ask")


def test_shell_missing_environment(
    tmp_path: Path, default_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = load_module(default_project / "scripts/shell.py", "shell_missing")
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    with pytest.raises(ValueError, match="Virtual environment missing"):
        helper.shell_environment(tmp_path, "bash")


def test_agent_environment_validation(
    default_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = configure_agent(default_project)
    monkeypatch.setenv("OPENAI_API_KEY", "test-value-never-forwarded")
    monkeypatch.setenv("AGENT_WORKSPACE", "/untrusted")
    env = helper.environment()
    assert "OPENAI_API_KEY" not in env
    assert env["AGENT_WORKSPACE"] == str(helper.WORKSPACE)
    monkeypatch.setenv("AGENT_APP_PORT", "0.0.0.0:8000")
    with pytest.raises(ValueError, match="unprivileged port"):
        helper.environment()


def test_dev_container_runtime(tmp_path: Path) -> None:
    runtime = shutil.which("podman") or shutil.which("docker")
    if not runtime:
        pytest.skip("Docker and Podman unavailable: dev build/start/import not executed")
    usable = subprocess.run([runtime, "info"], capture_output=True, check=False)
    if usable.returncode:
        pytest.skip("Container engine installed but unusable in this environment")
    project = generate(tmp_path, dev_container_runtime=Path(runtime).name)
    command(project, "make", "setup")
    try:
        command(project, "make", "dev-up")
        prefix = (runtime, "compose", "--env-file", ".env", "-f", "containers/compose.yaml")
        command(project, *prefix, "exec", "-T", "dev", "uv", "sync", "--locked")
        command(
            project,
            *prefix,
            "exec",
            "-T",
            "dev",
            "uv",
            "run",
            "python",
            "-c",
            "import my_python_project",
        )
        assert command(project, *prefix, "exec", "-T", "dev", "id", "-u").strip() != "0"
    finally:
        command(project, "make", "dev-down")


def test_agent_container_runtime(tmp_path: Path) -> None:
    if not shutil.which("podman"):
        pytest.skip("Podman unavailable: agent/security/HTTP-port runtime tests not executed")
    info = subprocess.run(
        ["podman", "info", "--format", "json"], text=True, capture_output=True, check=False
    )
    if info.returncode or not json.loads(info.stdout).get("host", {}).get("security", {}).get(
        "rootless"
    ):
        pytest.skip("Usable rootless Podman unavailable")
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    try:
        helper.start()
        assert helper.compose("exec", "-T", "agent", "id", "-u", capture=True) == "1000"
        helper.compose("exec", "-T", "agent", "make", "check")
        helper.compose("exec", "-T", "agent", "codex", "--version")
        ids = helper.compose("ps", "-q", capture=True).splitlines()
        inspection = json.loads(command(project, "podman", "inspect", *ids))[0]
        mounts = inspection["Mounts"]
        binds = [mount for mount in mounts if mount["Type"] == "bind"]
        assert len(binds) == 1
        assert Path(binds[0]["Source"]).resolve() == helper.WORKSPACE.resolve()
        assert all(".sock" not in mount["Source"] for mount in mounts)
        for mappings in inspection["NetworkSettings"]["Ports"].values():
            assert all(mapping["HostIp"] == "127.0.0.1" for mapping in mappings)
        sentinel = tmp_path / "host-only"
        sentinel.write_text("preserve")
        result = subprocess.run(
            [
                "podman",
                "compose",
                "--env-file",
                "/dev/null",
                "-f",
                str(project / "containers/compose.agent.yaml"),
                "exec",
                "-T",
                "agent",
                "sh",
                "-c",
                f"echo changed > {sentinel}",
            ],
            cwd=project,
            env=helper.environment(),
            capture_output=True,
            check=False,
        )
        assert result.returncode != 0 and sentinel.read_text() == "preserve"
        helper.compose(
            "exec",
            "-d",
            "agent",
            "uv",
            "run",
            "python",
            "-m",
            "http.server",
            "8000",
            "--bind",
            "0.0.0.0",
        )
        port = helper.environment()["AGENT_APP_PORT"]
        command(
            project,
            "curl",
            "--fail",
            "--retry",
            "10",
            "--retry-connrefused",
            "--retry-delay",
            "1",
            f"http://127.0.0.1:{port}",
        )
    finally:
        helper.compose("down")
