"""Exercise rendered repositories; template text alone is not the deliverable."""

from __future__ import annotations

import ast
import errno
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from types import ModuleType
from unittest.mock import patch

import jupytext
import pytest
import yaml
from cookiecutter.exceptions import FailedHookException
from cookiecutter.main import cookiecutter

ROOT = Path(__file__).resolve().parents[1]


def command(
    path: Path, *args: str, env: dict[str, str] | None = None, timeout: float | None = None
) -> str:
    # A sandbox uses /opt/venv for the generator itself. Child projects must
    # never synchronize into that environment and uninstall the running tools.
    env = dict(os.environ if env is None else env)
    if path != ROOT and (path / "pyproject.toml").exists():
        env["UV_PROJECT_ENVIRONMENT"] = str(path / ".venv")
    result = subprocess.run(
        list(args), cwd=path, env=env, text=True, capture_output=True, check=False, timeout=timeout
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _generate(destination: Path, options: dict[str, str], *, lock: bool) -> Path:
    # The real pre/post hooks still validate and prune the rendered project.
    # An empty PATH exercises the supported uv-absent hook path, avoiding network
    # resolution for structural tests. Integration/runtime use real uv locking.
    with patch.dict(os.environ, {} if lock else {"PATH": ""}):
        return Path(
            cookiecutter(
                str(ROOT), no_input=True, output_dir=str(destination), extra_context=options
            )
        )


@cache
def _render_root() -> TemporaryDirectory[str]:
    return TemporaryDirectory(prefix="template-render-")


@cache
def _rendered_skeleton(options: tuple[tuple[str, str], ...]) -> Path:
    directory = Path(mkdtemp(dir=_render_root().name))
    return _generate(directory, dict(options), lock=False)


def generate(destination: Path, **options: str) -> Path:
    # Cache only immutable render output, never a Git repository or environment.
    # Every caller receives its own copy so changes cannot contaminate other tests.
    skeleton = _rendered_skeleton(tuple(sorted(options.items())))
    destination.mkdir(parents=True, exist_ok=True)
    return Path(shutil.copytree(skeleton, destination / skeleton.name))


def generate_locked(destination: Path, **options: str) -> Path:
    return _generate(destination, options, lock=True)


def validate_rendered(project: Path) -> None:
    for path in project.rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path))
    tomllib.loads((project / "pyproject.toml").read_text())
    for pattern in ("*.yaml", "*.yml"):
        for path in project.rglob(pattern):
            yaml.safe_load(path.read_text())


@pytest.fixture(scope="session")
def default_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate(tmp_path_factory.mktemp("default"))


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_default_structure(default_project: Path) -> None:
    for name in (
        "src/my_python_project/__init__.py",
        "tests/unit/test_package.py",
        "tests/integration/test_cli.py",
        "docs/agent-security.md",
        "docs/podman.md",
        "scripts/init_project.py",
        "notebooks/01_example.py",
        "containers/Containerfile",
        "containers/compose.yaml",
        "containers/compose.agent.yaml",
        "scripts/agent.py",
        "AGENTS.md",
        ".github/workflows/ci.yml",
        ".github/workflows/pages.yml",
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
        {"coding_agent": "none"},
        {"dev_container_runtime": "docker", "coding_agent": "none"},
        {"enable_notebooks": "no"},
        {"enable_docs": "no"},
        {"ci_provider": "gitlab"},
        {"ci_provider": "none"},
        {
            "dev_container_runtime": "none",
            "coding_agent": "none",
            "enable_docs": "no",
            "enable_notebooks": "no",
            "ci_provider": "none",
        },
    ],
)
def test_option_matrix(tmp_path: Path, options: dict[str, str]) -> None:
    project = generate(tmp_path, **options)
    agent = options.get("coding_agent", "codex") != "none"
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
    assert (project / "docs/podman.md").exists() == (docs and (agent or runtime == "podman"))
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
    # Complete quality/build/docs workflows live in integration for default,
    # both, custom and none/minimal. Every option still gets syntax/config validation.
    validate_rendered(project)


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


def test_jupytext(default_project: Path) -> None:
    script = default_project / "notebooks/01_example.py"
    notebook = jupytext.read(script)
    assert notebook.metadata["jupytext"]["text_representation"]["format_name"] == "percent"
    assert len(notebook.cells) >= 2
    ast.parse(script.read_text())
    # CLI conversion/sync/execution reuses the integration smoke's environment.


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_environment(shell: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} unavailable")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    helper = load_module(ROOT / "{{cookiecutter.project_slug}}/scripts/shell.py", "shell_helper")
    bin_dir = tmp_path / ".venv/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").touch()
    monkeypatch.delenv("UV_PROJECT_ENVIRONMENT", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "previous-venv"))
    monkeypatch.setenv("PYTHONHOME", "/unused-python-home")
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(bin_dir), str(tmp_path / "previous-venv/bin"), os.environ["PATH"]]),
    )
    parent = dict(os.environ)
    executable, env = helper.shell_environment(tmp_path, shell)
    assert executable == shutil.which(shell)
    assert env["VIRTUAL_ENV"] == str(tmp_path / ".venv")
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert env["PATH"].split(os.pathsep).count(str(bin_dir)) == 1
    assert str(tmp_path / "previous-venv/bin") not in env["PATH"].split(os.pathsep)
    assert "PYTHONHOME" not in env
    assert dict(os.environ) == parent
    with monkeypatch.context() as nested_environment:
        for key, value in env.items():
            nested_environment.setenv(key, value)
        _, nested = helper.shell_environment(tmp_path, shell)
    assert nested["PATH"] == env["PATH"]
    assert nested["VIRTUAL_ENV"] == env["VIRTUAL_ENV"]
    with pytest.raises(ValueError, match="bash or zsh"):
        helper.shell_environment(tmp_path, "sh")


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_rc_loading(shell: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} unavailable")
    project = tmp_path / "project"
    project.mkdir()
    # Shell activation needs a Python executable, not application dependencies.
    command(project, "uv", "venv", "--python", sys.executable)
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    helper = load_module(ROOT / "{{cookiecutter.project_slug}}/scripts/shell.py", "shell_rc_helper")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("ZDOTDIR", str(tmp_path))
    sentinel = tmp_path / (".zshrc" if shell == "zsh" else ".bashrc")
    contents = 'export TEMPLATE_RC_LOADED=1\nalias template_alias="echo alias-loaded"\n'
    sentinel.write_text(contents)
    executable, env = helper.shell_environment(project, shell)
    # -i loads RC files; -c gives the shell a finite command instead of a piped REPL.
    output = command(
        project,
        executable,
        "-i",
        "-c",
        'printf "RC=%s\\nVENV=%s\\n" "$TEMPLATE_RC_LOADED" "$VIRTUAL_ENV"; '
        "command -v python; alias template_alias",
        env=env,
        timeout=10,
    )
    assert "RC=1" in output.splitlines()
    assert f"VENV={project / '.venv'}" in output.splitlines()
    assert str(project / ".venv/bin/python") in output.splitlines()
    assert "alias-loaded" in output
    assert sentinel.read_text() == contents


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_interactive_dispatch(
    shell: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    helper = load_module(
        ROOT / "{{cookiecutter.project_slug}}/scripts/shell.py", "shell_main_helper"
    )
    executable = f"/usr/bin/{shell}"
    env = {"VIRTUAL_ENV": str(tmp_path / ".venv"), "PATH": "prepared-path"}
    monkeypatch.setenv("SHELL", executable)
    monkeypatch.chdir(tmp_path)

    def prepare(root: Path, selected: str) -> tuple[str, dict[str, str]]:
        assert root == tmp_path and selected == executable
        return executable, env

    class ShellReplacedProcess(Exception):
        pass

    def replace_process(path: str, args: list[str], environment: dict[str, str]) -> None:
        assert path == executable
        assert args == [executable, "-i"]
        assert environment == env
        raise ShellReplacedProcess

    monkeypatch.setattr(helper, "shell_environment", prepare)
    monkeypatch.setattr(helper.os, "execve", replace_process)
    with pytest.raises(ShellReplacedProcess):
        helper.main()


def initialize(project: Path) -> None:
    command(project, "git", "init", "-b", "main")
    command(project, "git", "config", "user.email", "test@example.invalid")
    command(project, "git", "config", "user.name", "Template Test")
    command(project, "git", "add", ".")
    command(project, "git", "-c", "core.hooksPath=/dev/null", "commit", "-m", "initial")


def configure_agent(project: Path) -> ModuleType:
    helper = load_module(project / "scripts/agent.py", "agent_helper")
    return helper


def git_identity_environment(directory: Path, configured: bool = True) -> dict[str, str]:
    config = directory / "identity.gitconfig"
    config.write_text(
        "[user]\nname = Template Test\nemail = test@example.invalid\n" if configured else ""
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1")
    return env


def test_init_preserves_existing_unborn_repository(tmp_path: Path) -> None:
    project = generate(tmp_path)
    command(project, "git", "init", "-b", "main")
    (project / "user-work.txt").write_text("do not commit implicitly")
    result = subprocess.run(
        ["make", "init"],
        cwd=project,
        capture_output=True,
        text=True,
        env=git_identity_environment(tmp_path),
        check=False,
    )
    assert result.returncode != 0
    assert "Existing work will not be committed automatically" in result.stderr
    assert command(project, "git", "diff", "--cached", "--name-only").strip() == ""


def test_agent_requires_initial_commit(tmp_path: Path) -> None:
    project = generate(tmp_path)
    helper = configure_agent(project)
    with pytest.raises(ValueError, match="make init"):
        helper.prepare()
    command(project, "git", "init", "-b", "main")
    with pytest.raises(ValueError, match="at least one commit.*make init"):
        helper.prepare()


@pytest.mark.parametrize("provider", ["codex", "claude", "both", "custom"])
def test_git_isolation_and_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    project = generate(tmp_path, coding_agent=provider)
    initialize(project)
    helper = configure_agent(project)
    monkeypatch.setattr(helper, "running_containers", lambda: False)
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
    helper.apply()
    assert "AGENT_CHANGE" in (project / file).read_text()
    assert command(project, "git", "status", "--porcelain").strip() == ""


def test_git_safety_refusals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    monkeypatch.setattr(helper, "running_containers", lambda: False)
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


def test_yaml_configuration(default_project: Path) -> None:
    for pattern in ("*.yml", "*.yaml"):
        for path in default_project.rglob(pattern):
            if ".venv" not in path.parts:
                assert yaml.safe_load(path.read_text()) is not None


def test_bootstrap_documentation(default_project: Path) -> None:
    guide = (default_project / "docs/podman.md").read_text()
    for text in (
        "uidmap",
        "fuse-overlayfs",
        "passt",
        "/etc/subuid",
        "/etc/subgid",
        "systemctl --user enable --now podman.socket",
        "podman compose version",
        "podman ps",
        "https://example.com",
        "127.0.0.1:18080:80",
        "wsl --shutdown",
        "ss -ltnp",
        "{{.Host.Security.Rootless}}",
    ):
        assert text in guide
    assert "podman.md" in (default_project / "mkdocs.yml").read_text()
    assert "make init" in (default_project / "docs/getting-started.md").read_text()
    assert "make init" in (default_project / "README.md").read_text()
    assert "jetable" in (ROOT / "README.md").read_text()


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


def dynamic_ports(prefix: str) -> dict[str, str]:
    """Reserve distinct ephemeral loopback ports together, then release for Compose."""
    with ExitStack() as stack:
        ports = {}
        for name in ("APP", "JUPYTER", "DOCS"):
            sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            sock.bind(("127.0.0.1", 0))
            ports[f"{prefix}_{name}_PORT"] = str(sock.getsockname()[1])
        return ports


def test_agent_port_reservations(default_project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    helper = configure_agent(default_project)
    preferences = {
        helper.service_name(key): int(port) for key, port in dynamic_ports("AGENT").items()
    }
    with helper.reserve_ports(preferences) as effective:
        assert effective == preferences
        for port in effective.values():
            with socket.socket() as competing:
                with pytest.raises(OSError) as caught:
                    competing.bind(("127.0.0.1", port))
                assert caught.value.errno == errno.EADDRINUSE
    assert capsys.readouterr().out == ""
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", preferences["app"]))
        occupied.listen()
        with helper.reserve_ports(preferences) as effective:
            assert effective["app"] != preferences["app"]
            assert effective["jupyter"] == preferences["jupyter"]
            assert effective["docs"] == preferences["docs"]
            assert len(set(effective.values())) == 3
        message = capsys.readouterr().out
        assert f"Preferred agent port {preferences['app']} is already in use" in message


def test_agent_ports_restart_and_changed_preferences(default_project: Path) -> None:
    helper = configure_agent(default_project)
    choices = list(dynamic_ports("AGENT").values())
    preferred, previous, changed = map(int, choices)
    with helper.reserve_ports({"app": preferred}, {"app": previous}) as effective:
        assert effective == {"app": previous}
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", previous))
        with helper.reserve_ports({"app": preferred}, {"app": previous}) as effective:
            assert effective == {"app": preferred}
    with helper.reserve_ports({"app": changed}, {"app": previous}, {"app": preferred}) as effective:
        assert effective == {"app": changed}
    with helper.reserve_ports(dict.fromkeys(("app", "jupyter", "docs"), preferred)) as effective:
        assert len(set(effective.values())) == 3
    # All reservations are released on context exit.
    for port in effective.values():
        with socket.socket() as available:
            available.bind(("127.0.0.1", port))


def test_agent_port_selector_propagates_other_errors(
    default_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper = configure_agent(default_project)

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError(errno.EACCES, "denied")

    monkeypatch.setattr(helper.socket, "socket", denied)
    with pytest.raises(PermissionError):
        with helper.reserve_ports({"app": 18000}):
            pass


@pytest.mark.parametrize(
    "invalid",
    [
        {"app": "18000"},
        {"app": 0},
        {"app": True},
        {"ssh": 18000},
        {"app": 18000, "docs": 18000},
    ],
)
def test_agent_rejects_invalid_saved_ports(
    tmp_path: Path,
    default_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: dict[str, object],
) -> None:
    helper = configure_agent(default_project)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"provider": "codex", "ports": invalid}))
    monkeypatch.setattr(helper, "STATE", state_file)
    with pytest.raises(ValueError, match="ports"):
        helper.read_state()


@pytest.mark.parametrize("failure", ["address already in use", "network permission denied"])
def test_agent_start_ports_state_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    session = helper.prepare()
    preferences = {
        helper.service_name(key): int(port) for key, port in dynamic_ports("AGENT").items()
    }
    for key in helper.PORTS:
        monkeypatch.setenv(key, str(preferences[helper.service_name(key)]))
    live: dict[str, object] | None = None
    attempts: list[dict[str, int]] = []
    monkeypatch.setattr(helper, "agent_container", lambda: live)
    with socket.socket() as occupied, socket.socket() as race:
        occupied.bind(("127.0.0.1", preferences["app"]))

        def fake_compose(
            *args: str, capture: bool = False, ports: dict[str, int] | None = None
        ) -> str:
            nonlocal live
            if args[0] != "up":
                return ""
            assert ports is not None
            attempts.append(dict(ports))
            if len(attempts) == 1:
                race.bind(("127.0.0.1", ports["app"]))
                raise subprocess.CalledProcessError(125, ["podman"], stderr=failure)
            live = {
                "State": {"Running": True},
                "NetworkSettings": {
                    "Ports": {
                        f"{helper.SERVICE_PORTS[name]}/tcp": [
                            {"HostIp": "127.0.0.1", "HostPort": str(port)}
                        ]
                        for name, port in ports.items()
                    }
                },
            }
            return ""

        monkeypatch.setattr(helper, "compose", fake_compose)
        if failure != "address already in use":
            with pytest.raises(subprocess.CalledProcessError):
                helper.start_stack(session)
            assert len(attempts) == 1
            assert "ports" not in json.loads(helper.STATE.read_text())
            return
        helper.start_stack(session)
        assert len(attempts) == 2
        assert attempts[0]["app"] != attempts[1]["app"]
        saved = json.loads(helper.STATE.read_text())
        assert saved["ports"] == attempts[-1]
        assert saved["preferred_ports"] == preferences
        assert helper.environment()["AGENT_APP_PORT"] == str(saved["ports"]["app"])
        assert helper.environment(preferred=True)["AGENT_APP_PORT"] == str(preferences["app"])
        # Already running: keep actual ports even though they are notionally busy.
        helper.start_stack(session)
        assert attempts[-1] == attempts[-2]
        original_run = helper.run

        def fake_run(args: list[str], **kwargs: object) -> str:
            if args[0] == "podman":
                return "rootless=true"
            result: str = original_run(args, **kwargs)
            return result

        monkeypatch.setattr(helper, "run", fake_run)
        capsys.readouterr()
        helper.status()
        output = capsys.readouterr().out
        assert "Agent: running" in output
        for port in saved["ports"].values():
            assert f"http://127.0.0.1:{port}" in output
        assert f"http://127.0.0.1:{preferences['app']}" not in output
        assert "preferred_ports" not in output


def test_published_ports_reject_nonlocal_bind(default_project: Path) -> None:
    helper = configure_agent(default_project)
    with pytest.raises(ValueError, match="localhost-only"):
        helper.published_ports(
            {
                "NetworkSettings": {
                    "Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "18000"}]}
                }
            }
        )


@pytest.mark.parametrize("provider", ["codex", "claude", "both", "custom", "none"])
def test_selected_provider_project(tmp_path: Path, provider: str) -> None:
    project = generate(tmp_path, coding_agent=provider)
    containerfile = (project / "containers/Containerfile").read_text()
    help_text = command(project, "make", "help")
    instructions = {"codex": "AGENTS.md", "claude": "CLAUDE.md"}
    for choice, name in instructions.items():
        assert (project / name).exists() == (provider == choice or provider == "both")
    if provider == "none":
        assert not (project / "scripts/agent.py").exists()
        assert not (project / "containers/compose.agent.yaml").exists()
        assert not (project / "docs/agent.md").exists()
        assert "agent-" not in help_text
        assert "@openai" not in containerfile and "@anthropic" not in containerfile
        assert "agent-check" not in (project / "docs/podman.md").read_text()
    else:
        config = yaml.safe_load((project / "containers/compose.agent.yaml").read_text())
        service = config["services"]["agent"]
        assert service["user"] == "1000:1000"
        assert service["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert not service.get("privileged") and service.get("network_mode") != "host"
        assert all(port.startswith("127.0.0.1:") for port in service["ports"])
        installed = (
            {"codex", "claude"}
            if provider == "both"
            else ({provider} if provider != "custom" else set())
        )
        for name, package in {
            "codex": "@openai/codex",
            "claude": "@anthropic-ai/claude-code",
        }.items():
            assert (package in containerfile) == (name in installed)
            assert (f"agent-{name}-home:/home/agent/.{name}" in service["volumes"]) == (
                name in installed
            )
        assert "FROM node:22." in containerfile
        assert "agent-rebuild" in help_text
        for target in ("agent-refresh", "agent-rebase", "agent-archive"):
            assert target in help_text
        helper = configure_agent(project)
        assert set(helper.AGENTS) == installed
        if provider == "custom":
            assert "agent-login" not in help_text
            assert "agent-tools:/home/agent/.local" in service["volumes"]
            assert "agent-config:/home/agent/.config" in service["volumes"]
            assert (project / "containers/agent-custom-install.sh").is_file()
            command(project, "bash", "-n", "containers/agent-custom-install.sh")
            assert helper.selected_agent() is None
        else:
            assert "agent-login" in help_text
            assert helper.selected_agent().login == (
                ("claude", "auth", "login")
                if provider == "claude"
                else ("codex", "login", "--device-auth")
            )
        if provider == "both":
            for target in (
                "agent-codex",
                "agent-claude",
                "agent-login-codex",
                "agent-login-claude",
            ):
                assert target in help_text
    validate_rendered(project)


def test_instructions_share_one_source(tmp_path: Path) -> None:
    codex = generate(tmp_path / "codex", coding_agent="codex")
    claude = generate(tmp_path / "claude", coding_agent="claude")
    assert (codex / "AGENTS.md").read_text() == (claude / "CLAUDE.md").read_text()
    assert "enable_agent" not in json.loads((ROOT / "cookiecutter.json").read_text())


def test_provider_state_mismatch(tmp_path: Path) -> None:
    project = generate(tmp_path)
    initialize(project)
    helper = configure_agent(project)
    saved = helper.prepare()
    assert saved["provider"] == "codex"
    saved.pop("provider")
    helper.STATE.write_text(json.dumps(saved))
    assert helper.state()["provider"] == "codex"
    saved["provider"] = "claude"
    helper.STATE.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="provider differs"):
        helper.state()


@pytest.mark.parametrize("provider", ["codex", "claude"])
def test_login_and_launch_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    project = generate(tmp_path, coding_agent=provider)
    helper = configure_agent(project)
    expected_launch = (
        (
            "codex",
            "--no-daemon",
            "--dangerously-bypass-approvals-and-sandbox",
            "-c",
            "check_for_update_on_startup=false",
        )
        if provider == "codex"
        else ("claude", "--dangerously-skip-permissions")
    )
    assert helper.selected_agent().launch == expected_launch
    assert helper.selected_agent().launch.count("--no-daemon") == (provider == "codex")
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(helper, "start", lambda: calls.append(("start",)))
    monkeypatch.setattr(helper, "compose", lambda *args: calls.append(args))
    monkeypatch.setattr(sys, "argv", ["agent.py", "login"])
    helper.main()
    assert calls == [("start",), ("exec", "agent", *helper.selected_agent().login)]
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["agent.py", "run"])
    helper.main()
    assert calls == [("start",), ("exec", "agent", *helper.selected_agent().launch)]


def test_compose_selection_and_warning(
    default_project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    helper = configure_agent(default_project)
    monkeypatch.setattr(
        helper.shutil,
        "which",
        lambda value: "/usr/bin/podman-compose" if value == "podman-compose" else "/usr/bin/podman",
    )
    monkeypatch.setenv("PODMAN_COMPOSE_PROVIDER", "/usr/bin/docker-compose")
    assert helper.environment()["PODMAN_COMPOSE_PROVIDER"] == "/usr/bin/podman-compose"
    helper.diagnose_wsl("there is no systemd user session available")
    assert "Warning:" in capsys.readouterr().err
    monkeypatch.setattr(helper.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="podman-compose is unavailable"):
        helper.compose("config")
    docs = (default_project / "docs/podman.md").read_text()
    section = docs[docs.index("### Podman says there is no systemd user session") :]
    assert section.index("wsl --shutdown") < section.index("loginctl user-status")


@contextmanager
def runtime_cleanup(cleanup: Callable[[], object]) -> Iterator[None]:
    original: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        original = exc
        raise
    finally:
        try:
            cleanup()
        except Exception as exc:
            if original is None:
                raise
            original.add_note(f"Container cleanup also failed: {exc}")


def test_dynamic_ports_with_common_port_occupied() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        try:
            occupied.bind(("127.0.0.1", 8000))
            occupied.listen()
        except OSError as exc:
            import errno

            if exc.errno != errno.EADDRINUSE:
                raise
            # Another service already owns 8000: this is exactly the case under test.
        for prefix in ("DEV", "AGENT"):
            ports = dynamic_ports(prefix)
            assert len(set(ports.values())) == 3
            for value in ports.values():
                assert int(value) != 8000
                with socket.socket() as available:
                    available.bind(("127.0.0.1", int(value)))


def test_cleanup_preserves_original_failure() -> None:
    def failing_cleanup() -> None:
        raise RuntimeError("cleanup failed")

    with pytest.raises(AssertionError, match="original failure") as caught:
        with runtime_cleanup(failing_cleanup):
            raise AssertionError("original failure")
    assert "cleanup failed" in caught.value.__notes__[0]
    with pytest.raises(RuntimeError, match="cleanup failed"):
        with runtime_cleanup(failing_cleanup):
            pass


def test_structural_render_does_not_create_environment(tmp_path: Path) -> None:
    project = generate(tmp_path)
    assert (project / "pyproject.toml").is_file()
    assert not (project / "uv.lock").exists()
    assert not (project / ".venv").exists()
    validate_rendered(project)


def test_render_cache_returns_independent_projects(tmp_path: Path) -> None:
    first = generate(tmp_path / "first")
    original = (first / "README.md").read_text()
    (first / "README.md").write_text("changed by one test")
    initialize(first)
    second = generate(tmp_path / "second")
    assert (second / "README.md").read_text() == original
    assert not (second / ".git").exists()
    assert first != second
