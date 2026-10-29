"""Host-controlled rootless sandbox. Never execute this helper from agent code."""

from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NotRequired, TypedDict
from urllib.request import urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".agent"
WORKSPACE = STATE_DIR / "workspace"
STATE = STATE_DIR / "state.json"
VERSIONS_FILE = ROOT / "containers/harness-versions.env"
BUILD_TARGET = "agent"
PROFILE = "{{ cookiecutter.coding_agent }}"
IMAGE = "localhost/{{ cookiecutter.project_slug }}-agent:template-v2-{{ cookiecutter.coding_agent }}"


@dataclass(frozen=True)
class CodingAgent:
    name: str
    cli: str
    config_dir: str
    login: tuple[str, ...]
    launch: tuple[str, ...]


AGENTS: dict[str, CodingAgent] = {}

{% if cookiecutter.coding_agent in ['codex', 'both'] %}AGENTS["codex"] = CodingAgent(
    "Codex",
    "codex",
    "/home/agent/.codex",
    ("codex", "login", "--device-auth"),
    (
        "codex",
        "--no-daemon",
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        "check_for_update_on_startup=false",
    ),
)
{% endif %}{% if cookiecutter.coding_agent in ['claude', 'both'] %}AGENTS["claude"] = CodingAgent(
    "Claude Code",
    "claude",
    "/home/agent/.claude",
    ("claude", "auth", "login"),
    ("claude", "--dangerously-skip-permissions"),
)
{% endif %}PERSISTENT_PATHS = {name: agent.config_dir for name, agent in AGENTS.items()}
{% if cookiecutter.coding_agent == 'custom' %}PERSISTENT_PATHS.update(tools="/home/agent/.local", config="/home/agent/.config")
{% endif %}

PORTS = {
    "AGENT_APP_PORT": 18000,
{% if cookiecutter.enable_notebooks == 'yes' %}    "AGENT_JUPYTER_PORT": 18888,
{% endif %}{% if cookiecutter.enable_docs == 'yes' %}    "AGENT_DOCS_PORT": 18001,
{% endif %}}

SERVICE_PORTS = {"app": 8000, "jupyter": 8888, "docs": 8001}


def service_name(variable: str) -> str:
    return variable.removeprefix("AGENT_").removesuffix("_PORT").lower()


class AgentState(TypedDict):
    base: str
    branch: str
    workspace: str
    created: str
    provider: str
    profile: NotRequired[str]
    default_provider: NotRequired[str]
    ports: NotRequired[dict[str, int]]
    preferred_ports: NotRequired[dict[str, int]]
    pending_rebase_base: NotRequired[str]


def setting(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    path = ROOT / ".env"
    value = default
    if path.exists():
        for line in path.read_text().splitlines():
            name, sep, candidate = line.partition("=")
            if sep and name.strip() == key:
                value = candidate.strip()
    return value


def default_provider() -> str:
    if PROFILE != "both":
        return PROFILE
    value = setting("AGENT_DEFAULT_PROVIDER", "codex")
    if value not in AGENTS:
        raise ValueError("AGENT_DEFAULT_PROVIDER must be codex or claude for profile both.")
    return value


def selected_agent(provider: str | None = None) -> CodingAgent | None:
    choice = provider or default_provider()
    if choice == "custom" and PROFILE == "custom":
        return None
    if choice not in AGENTS:
        raise ValueError(f"Harness {choice!r} is not installed by profile {PROFILE!r}.")
    return AGENTS[choice]


def custom_command() -> tuple[str, ...]:
    # Parse argv only: never expand shell syntax or execute anything on the host.
    command = shlex.split(setting("CUSTOM_AGENT_COMMAND"))
    args = shlex.split(setting("CUSTOM_AGENT_ARGS"))
    if not command and args:
        raise ValueError("Set CUSTOM_AGENT_COMMAND before CUSTOM_AGENT_ARGS.")
    return tuple([*command, *args])


def report_profile() -> None:
    print(f"Agent profile: {PROFILE}")
    print("Official harnesses: " + (", ".join(agent.name for agent in AGENTS.values()) or "none"))
    if PROFILE == "custom":
        print("Custom harness command: " + ("configured" if custom_command() else "not configured"))
    for name, path in PERSISTENT_PATHS.items():
        suffix = f"{name}-home" if name in AGENTS else name
        print(f"Persistent volume: {{ cookiecutter.project_slug }}-agent-{suffix} -> {path}")


def run(
    args: list[str], cwd: Path = ROOT, capture: bool = False, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if capture and result.stderr:
        if args[0] == "podman":
            diagnose_wsl(result.stderr)
        else:
            print(result.stderr, file=sys.stderr, end="")
    result.check_returncode()
    return result.stdout.strip() if capture else ""


def diagnose_wsl(message: str) -> None:
    print(message, file=sys.stderr, end="" if message.endswith("\n") else "\n")
    if any(
        text in message.lower()
        for text in ("no systemd user session", "cgroupfs", "connect to bus")
    ):
        print(
            "Warning: Podman may fall back from systemd cgroups to cgroupfs. "
            "Execution may still work. If systemd is already enabled, first run "
            "wsl --shutdown from Windows, reopen WSL and retest. See docs/podman.md.",
            file=sys.stderr,
        )


def git(path: Path, *args: str, capture: bool = True, isolated: bool = False) -> str:
    # The agent controls clone-local Git config. Disable executable Git features
    # for host inspection; never run a script from the clone on the host.
    env = dict(os.environ)
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    # An existing /dev/null is still treated as a deprecated graft file by Git.
    # Empty explicitly disables grafts, including clone-local info/grafts.
    env["GIT_GRAFT_FILE"] = ""
    if isolated:
        env["GIT_CONFIG_GLOBAL"] = "/dev/null"
        env["GIT_CONFIG_SYSTEM"] = "/dev/null"
        for key in tuple(env):
            if key.startswith("GIT_CONFIG_") and key not in {
                "GIT_CONFIG_GLOBAL",
                "GIT_CONFIG_SYSTEM",
            }:
                del env[key]
    filter_overrides: list[str] = []
    if path == WORKSPACE:
        # Even status can execute .gitattributes clean/process filters. Read
        # config names without evaluating programs, then disable those drivers.
        settings = subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "config",
                "--null",
                "--name-only",
                "--get-regexp",
                "^filter\\.",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if settings.returncode not in (0, 1):
            settings.check_returncode()
        for key in settings.stdout.split("\0"):
            if re.fullmatch(r"filter\..*\.(clean|smudge|process|required)", key, re.DOTALL):
                value = "false" if key.endswith(".required") else ""
                filter_overrides.extend(["-c", f"{key}={value}"])
    return run(
        [
            "git",
            "--no-pager",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-c",
            "diff.external=",
            "-c",
            f"core.worktree={path}",
            "-C",
            str(path),
            *filter_overrides,
            *args,
        ],
        capture=capture,
        env=env,
    )


def clean_repository(path: Path) -> None:
    if git(path, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"Uncommitted changes in {path}. Commit or stash before continuing.")


def read_state(*, allow_profile_mismatch: bool = False) -> AgentState:
    if STATE.is_symlink() or WORKSPACE.is_symlink() or STATE_DIR.is_symlink():
        raise ValueError("Agent paths must not be symbolic links.")
    result: AgentState = json.loads(STATE.read_text())
    # Old sessions used provider to mean the entire installed profile.
    result.setdefault("provider", "codex")
    result.setdefault("profile", result["provider"])
    if result["provider"] != result["profile"] or (
        result["profile"] != PROFILE and not allow_profile_mismatch
    ):
        raise ValueError(
            "Agent session profile/provider differs from this project. Run make agent-clean "
            "(credential volumes are preserved), review/archive .agent outside the checkout, "
            "then make agent-rebuild and make agent-start. Retain all unmerged work."
        )
    for key in ("ports", "preferred_ports"):
        values = result.get(key, {})
        if not isinstance(values, dict) or any(
            name not in SERVICE_PORTS or type(port) is not int or not 1024 <= port <= 65535
            for name, port in values.items()
        ):
            raise ValueError(f"Invalid {key} in agent state.")
        if key == "ports" and len(set(values.values())) != len(values):
            raise ValueError("Effective agent ports must be distinct.")
    return result


def state(*, allow_profile_mismatch: bool = False) -> AgentState:
    result = read_state(allow_profile_mismatch=allow_profile_mismatch)
    git_dir = WORKSPACE / ".git"
    if result.get("workspace") != str(WORKSPACE) or not git_dir.is_dir():
        raise ValueError("Invalid agent workspace; expected an independent .git directory.")
    if git_dir.is_symlink() or any(path.is_symlink() for path in git_dir.rglob("*")):
        raise ValueError("Agent .git must not contain symlinks when inspected by the host.")
    if (WORKSPACE / ".git/objects/info/alternates").exists():
        raise ValueError("Agent Git object store must not use alternates.")
    if not re.fullmatch(r"[0-9a-f]{40,64}", result.get("base", "")):
        raise ValueError("Invalid base commit in agent state.")
    if not re.fullmatch(r"agent/[0-9TZ-]+", result.get("branch", "")):
        raise ValueError("Invalid agent branch in state.")
    branch = git(WORKSPACE, "branch", "--show-current")
    rebasing = any((git_dir / name).exists() for name in ("rebase-merge", "rebase-apply"))
    if branch != result["branch"] and not (not branch and rebasing):
        raise ValueError("Agent changed branch; restore the session branch before continuing.")
    return result


def validate_repository() -> str:
    detected = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    local_git = ROOT / ".git"
    if (
        detected.returncode != 0
        or not local_git.is_dir()
        or local_git.is_symlink()
        or Path(detected.stdout.strip()).resolve() != ROOT
    ):
        parent = ""
        if detected.returncode == 0 and Path(detected.stdout.strip()).resolve() != ROOT:
            parent = (
                "A parent Git repository was detected, but this project does not "
                "have its own repository.\n\n"
            )
        raise ValueError(
            "This directory is not an independent Git repository.\n\n"
            + parent
            + "The secure agent requires a project-local .git directory and at least one commit."
            + "\n\nRun:\n\n    make init\n\nthen:\n\n    make agent"
        )
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        raise ValueError(
            "The secure agent requires at least one commit. Run make init, then make agent."
        )
    return head.stdout.strip()


def prepare() -> AgentState:
    validate_repository()
    clean_repository(ROOT)
    if git(ROOT, "check-ignore", ".agent/workspace") != ".agent/workspace":
        raise ValueError(".agent/ must be ignored by the primary repository.")
    if STATE.exists():
        result = finish_rebase(state())
        if git(ROOT, "rev-parse", "HEAD") != result["base"]:
            return refresh()
        if PROFILE == "both":
            result["default_provider"] = default_provider()
        STATE.write_text(json.dumps(result, indent=2) + "\n")
        return result
    if WORKSPACE.exists():
        raise ValueError("Workspace exists without state. Inspect/archive .agent manually.")
    STATE_DIR.mkdir(exist_ok=True)
    base = git(ROOT, "rev-parse", "HEAD")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    branch = f"agent/{stamp}"
    run(["git", "clone", "--no-hardlinks", "--no-local", str(ROOT), str(WORKSPACE)])
    git(WORKSPACE, "remote", "remove", "origin")
    git(WORKSPACE, "checkout", "-b", branch, base)
    for key in ("user.name", "user.email"):
        value = subprocess.run(
            ["git", "config", "--get", key], cwd=ROOT, capture_output=True, text=True, check=False
        )
        if value.returncode == 0:
            git(WORKSPACE, "config", key, value.stdout.strip())
    result = {
        "base": base,
        "branch": branch,
        "workspace": str(WORKSPACE),
        "created": stamp,
        "provider": PROFILE,
        "profile": PROFILE,
    }
    if PROFILE == "both":
        result["default_provider"] = default_provider()
    STATE.write_text(json.dumps(result, indent=2) + "\n")
    return result


def git_operation() -> str:
    for name in (
        "rebase-merge",
        "rebase-apply",
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "sequencer",
        "BISECT_LOG",
        "index.lock",
    ):
        if (WORKSPACE / ".git" / name).exists():
            return name
    return ""


@contextmanager
def comparison_repository() -> Iterator[Path]:
    # Compare actual objects in a trusted bare repo: no agent remotes, hooks,
    # grafts, replacements or config are used to import either history.
    with tempfile.TemporaryDirectory(prefix="agent-comparison-") as directory:
        path = Path(directory) / "repository.git"
        run(["git", "init", "--bare", "--initial-branch=main", str(path)], capture=True)
        for source in (ROOT, WORKSPACE):
            copy_objects(source / ".git/objects", path / "objects")
        yield path


def copy_objects(source: Path, destination: Path) -> None:
    # Git objects are immutable and often read-only. Keep existing objects rather
    # than overwriting duplicate hashes; do not copy info/alternates or caches.
    def missing_object(src: str, dst: str) -> str:
        if not Path(dst).exists():
            shutil.copy2(src, dst)
        return dst

    for path in source.iterdir():
        if path.is_dir() and (path.name == "pack" or re.fullmatch(r"[0-9a-f]{2}", path.name)):
            shutil.copytree(
                path, destination / path.name, dirs_exist_ok=True, copy_function=missing_object
            )


def session_work(session: AgentState) -> tuple[int, int, str]:
    dirty = len(git(WORKSPACE, "status", "--porcelain", "--untracked-files=all").splitlines())
    operation = git_operation()
    primary = validate_repository()
    head = git(WORKSPACE, "rev-parse", "HEAD")
    with comparison_repository() as repository:
        # A rewritten/detached history is ambiguous even if its tree looks empty.
        try:
            git(repository, "merge-base", "--is-ancestor", session["base"], head)
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1:
                raise
            return 1, dirty, operation or "agent history diverged from recorded base"
        cherry = git(repository, "cherry", primary, head, session["base"])
        unapplied = {line.split()[1] for line in cherry.splitlines() if line.startswith("+")}
        # cherry skips merge and empty commits; preserve both conservatively.
        for commit in git(
            repository, "rev-list", head, "^" + primary, "^" + session["base"]
        ).splitlines():
            parents = git(repository, "rev-list", "--parents", "-n", "1", commit).split()[1:]
            if len(parents) != 1 or not git(
                repository, "diff-tree", "--root", "--no-commit-id", "-r", commit
            ):
                unapplied.add(commit)
    return len(unapplied), dirty, operation


def report_session(session: AgentState) -> bool:
    primary = validate_repository()
    commits, dirty, operation = session_work(session)
    stale = primary != session["base"]
    print(f"Agent session: {'stale' if stale else 'current'}")
    print(f"Session base: {session['base']}\nPrimary HEAD: {primary}")
    print(f"Agent work: {commits} unapplied commits, {dirty} modified/untracked files")
    if operation:
        print(f"Git operation/history requiring review: {operation}")
    safe = not (commits or dirty or operation)
    if stale:
        print("Safe automatic refresh available on next start." if safe else "Refresh blocked.")
    return safe


def require_no_work(session: AgentState) -> None:
    if not report_session(session):
        raise ValueError(
            "The agent workspace contains unapplied work or an unfinished Git operation.\n"
            f"Base: {session['base']}\nPrimary: {validate_repository()}\n"
            f"Agent: {git(WORKSPACE, 'rev-parse', 'HEAD')}\n"
            "Review with make agent-diff and make agent-test. Then make agent-rebase, "
            "or make agent-archive to retain the old session. Use make agent-apply "
            "only with a compatible base. No workspace changes made."
        )


def stop_session_runtime() -> None:
    if not shutil.which("podman"):
        raise ValueError(
            "Podman required on the host to stop/remove runtime before session changes."
        )
    compose("down")  # Never --volumes: authentication and custom tools survive.


def retire_session() -> Path:
    archive = STATE_DIR / "archive"
    if archive.is_symlink():
        raise ValueError("Agent archive must not be a symlink.")
    archive.mkdir(exist_ok=True)
    destination = archive / dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    destination.mkdir()
    WORKSPACE.rename(destination / "workspace")
    STATE.rename(destination / "state.json")
    print(f"Previous session retained at {destination}; no files copied or credentials removed.")
    return destination


def refresh() -> AgentState:
    validate_repository()
    clean_repository(ROOT)
    if not STATE.exists():
        return prepare()
    session = finish_rebase(state())
    require_no_work(session)
    stop_session_runtime()
    # Freeze the runtime before the final check; it may have edited during inspection.
    session = state()
    require_no_work(session)
    print(
        f"Refreshing isolated agent workspace. Old base: {session['base']}\n"
        f"New base: {validate_repository()}"
    )
    retire_session()
    result = prepare()
    if "ports" in session:
        result["ports"] = session["ports"]
    if "preferred_ports" in session:
        result["preferred_ports"] = session["preferred_ports"]
    STATE.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Agent workspace refreshed. Base commit: {result['base']}\nCredentials preserved.")
    return result


def archive_session() -> None:
    state(allow_profile_mismatch=True)
    stop_session_runtime()
    state(allow_profile_mismatch=True)
    retire_session()
    print("Session archived. Run make agent-start for a fresh session. Credentials preserved.")


def finish_rebase(session: AgentState) -> AgentState:
    target = session.get("pending_rebase_base")
    if not target or git_operation():
        return session
    if not re.fullmatch(r"[0-9a-f]{40,64}", target):
        raise ValueError("Invalid pending rebase target.")
    try:
        git(WORKSPACE, "merge-base", "--is-ancestor", target, "HEAD")
    except subprocess.CalledProcessError as exc:
        if exc.returncode != 1:
            raise
        print("Previous rebase was aborted; original session base retained.")
    else:
        session["base"] = target
        print(f"Completed rebase recognized. Session base: {target}")
    del session["pending_rebase_base"]
    STATE.write_text(json.dumps(session, indent=2) + "\n")
    return session


def rebase_session() -> None:
    primary = validate_repository()
    clean_repository(ROOT)
    session = finish_rebase(state())
    if git_operation():
        raise ValueError("Git operation already in progress. Resolve or abort it explicitly.")
    clean_repository(WORKSPACE)
    if primary == session["base"]:
        print("Agent base already matches primary HEAD; no rebase needed.")
        return
    commits, _, operation = session_work(session)
    if operation:
        raise ValueError(f"Cannot rebase ambiguous history: {operation}")
    if not commits:
        refresh()
        return
    if git(WORKSPACE, "rev-list", "--merges", f"{session['base']}..HEAD"):
        raise ValueError(
            "Merge commits require manual review/rebase; archive preserves the session."
        )
    stop_session_runtime()
    state()
    clean_repository(WORKSPACE)
    if git_operation():
        raise ValueError("Git operation appeared while stopping the runtime; inspect workspace.")
    # Import primary objects without invoking fetch against clone-controlled config.
    copy_objects(ROOT / ".git/objects", WORKSPACE / ".git/objects")
    session["pending_rebase_base"] = primary
    STATE.write_text(json.dumps(session, indent=2) + "\n")
    config = WORKSPACE / ".git/config"
    original = config.read_bytes()
    # A host-side rebase must not execute clone-configured filters, merge drivers,
    # editors or hooks. Keep only trusted identity in a temporary local config.
    safe_config = "[core]\nrepositoryformatversion = 0\nbare = false\n"
    for key in ("user.name", "user.email"):
        value = git(ROOT, "config", "--get", key)
        section, name = key.split(".")
        safe_config += f"[{section}]\n{name} = {json.dumps(value, ensure_ascii=False)}\n"
    try:
        config.write_text(safe_config)
        git(
            WORKSPACE, "rebase", "--no-autostash", "--onto", primary, session["base"], isolated=True
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            "Agent rebase stopped because of conflicts or a Git error. No automatic abort/reset.\n"
            "Inspect: git -C .agent/workspace status\n"
            "Resolve and git -C .agent/workspace rebase --continue, or rebase --abort explicitly.\n"
            "Then run make agent-rebase again to reconcile session metadata."
        ) from exc
    finally:
        config.write_bytes(original)
    finish_rebase(session)


def environment(*, preferred: bool = False) -> dict[str, str]:
    # Do not pass the host environment or .env wholesale to Compose. In
    # particular .env must never redirect AGENT_WORKSPACE or select build files.
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        in {
            "PATH",
            "HOME",
            "XDG_RUNTIME_DIR",
            "DBUS_SESSION_BUS_ADDRESS",
            "TERM",
            "LANG",
            "SSH_AUTH_SOCK",
        }
    }
    for key, default in PORTS.items():
        value = setting(key, str(default))
        if not value.isdecimal() or not 1024 <= int(value) <= 65535:
            raise ValueError(f"{key} must be an unprivileged port (1024..65535).")
        env[key] = value
    if not preferred and STATE.exists():
        effective = read_state(allow_profile_mismatch=True).get("ports", {})
        for key in PORTS:
            if service_name(key) in effective:
                env[key] = str(effective[service_name(key)])
    if AGENTS and VERSIONS_FILE.exists():
        env.update(harness_versions())
    env["AGENT_WORKSPACE"] = str(WORKSPACE)
    provider = shutil.which("podman-compose")
    if provider:
        env["PODMAN_COMPOSE_PROVIDER"] = provider
    return env


def compose(*args: str, capture: bool = False, ports: dict[str, int] | None = None) -> str:
    if not shutil.which("podman-compose"):
        raise ValueError(
            "podman-compose is unavailable. Install it on the host; see docs/podman.md."
        )
    env = environment()
    if ports is not None:
        for key in PORTS:
            env[key] = str(ports[service_name(key)])
    return run(
        [
            "podman",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            str(ROOT / "containers/compose.agent.yaml"),
            *args,
        ],
        capture=capture,
        env=env,
    )


@contextmanager
def reserve_ports(
    preferences: dict[str, int],
    previous: dict[str, int] | None = None,
    previous_preferences: dict[str, int] | None = None,
) -> Iterator[dict[str, int]]:
    """Reserve stable choices first, then ephemeral fallbacks, on loopback only."""
    previous = previous or {}
    selected: dict[str, int] = {}
    busy: set[int] = set()
    with ExitStack() as stack:

        def reserve(port: int) -> int | None:
            sock = stack.enter_context(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            try:
                sock.bind(("127.0.0.1", port))
            except OSError as exc:
                sock.close()
                if exc.errno != errno.EADDRINUSE:
                    raise
                busy.add(port)
                return None
            return int(sock.getsockname()[1])

        for name, preferred in preferences.items():
            candidates = [preferred]
            if name in previous and (
                previous_preferences is None or previous_preferences.get(name) == preferred
            ):
                candidates.insert(0, previous[name])
            for candidate in dict.fromkeys(candidates):
                port = reserve(candidate)
                if port is not None:
                    selected[name] = port
                    break
        # Do not consume another service's free preferred port as a fallback.
        for name, preferred in preferences.items():
            if name not in selected:
                port = reserve(0)
                assert port is not None
                selected[name] = port
            if selected[name] != preferred:
                if preferred in busy:
                    print(
                        f"Preferred agent port {preferred} is already in use. "
                        f"Using {selected[name]} instead.",
                        flush=True,
                    )
                else:
                    print(
                        f"Reusing saved {name} port {selected[name]} (preferred {preferred}).",
                        flush=True,
                    )
        yield selected


def agent_container() -> dict[str, Any] | None:
    identifiers = compose("ps", "-q", capture=True).splitlines()
    if not identifiers:
        return None
    containers = json.loads(run(["podman", "inspect", *identifiers], capture=True))
    agents = [
        container
        for container in containers
        if container.get("Config", {})
        .get("Labels", {})
        .get(
            "com.docker.compose.service",
            container.get("Config", {}).get("Labels", {}).get("io.podman.compose.service"),
        )
        == "agent"
    ]
    if not agents and len(containers) == 1:
        agents = containers
    if len(agents) != 1:
        raise ValueError("Cannot identify the agent container in this project's stack.")
    result: dict[str, Any] = agents[0]
    return result


def published_ports(container: dict[str, Any]) -> dict[str, int]:
    bindings = container.get("NetworkSettings", {}).get("Ports", {})
    result: dict[str, int] = {}
    for key in PORTS:
        name = service_name(key)
        mappings = bindings.get(f"{SERVICE_PORTS[name]}/tcp") or []
        if len(mappings) != 1 or mappings[0].get("HostIp") != "127.0.0.1":
            raise ValueError(f"Expected one localhost-only publication for {name}.")
        port = int(mappings[0]["HostPort"])
        if not 1024 <= port <= 65535 or port in result.values():
            raise ValueError("Invalid effective port published by the agent.")
        result[name] = port
    return result


def start_stack(session: AgentState) -> None:
    env = environment(preferred=True)
    preferences = {service_name(key): int(env[key]) for key in PORTS}
    container = agent_container()
    if container is not None and container["State"]["Running"]:
        # Never reallocate a running agent's own busy ports, even for old states.
        effective = published_ports(container)
        compose("up", "-d", "--no-build", ports=effective)
    else:
        for attempt in range(3):
            with reserve_ports(
                preferences, session.get("ports"), session.get("preferred_ports")
            ) as effective:
                effective = dict(effective)
            # Podman must bind these itself. Retry a bind race across projects.
            try:
                compose("up", "-d", "--no-build", "--force-recreate", ports=effective, capture=True)
                break
            except subprocess.CalledProcessError as exc:
                message = f"{exc.stderr or ''} {exc.output or ''}".lower()
                if not any(
                    text in message
                    for text in ("address already in use", "port is already allocated")
                ):
                    raise
                if attempt == 2:
                    raise ValueError(
                        "Ports changed during startup repeatedly; retry make agent-start."
                    ) from exc
                print(
                    "Port allocation changed during startup; selecting free ports again.",
                    flush=True,
                )
        session["preferred_ports"] = preferences
    container = agent_container()
    if container is None or not container["State"]["Running"]:
        raise ValueError("Agent container did not start. Inspect make agent-logs.")
    session["ports"] = published_ports(container)
    STATE.write_text(json.dumps(session, indent=2) + "\n")


def running_containers() -> bool:
    identifiers = compose("ps", "-q", capture=True).splitlines()
    if not identifiers:
        return False
    containers = json.loads(run(["podman", "inspect", *identifiers], capture=True))
    return any(container["State"]["Running"] for container in containers)


def check(*, inspect_image: bool = True) -> None:
    if not shutil.which("podman"):
        raise ValueError(
            "Podman missing. Install Podman and configure rootless execution: "
            "https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md"
        )
    info = json.loads(run(["podman", "info", "--format", "json"], capture=True))
    if not info.get("host", {}).get("security", {}).get("rootless", False) or os.getuid() == 0:
        raise ValueError(
            "Rootless Podman required. Check /etc/subuid, /etc/subgid, "
            "newuidmap/newgidmap and podman info; no automatic sudo repair."
        )
    provider = shutil.which("podman-compose")
    if not provider:
        raise ValueError(
            "podman-compose is unavailable. Install it on the host; see docs/podman.md."
        )
    versions()
    default_provider()
    print("Podman: available\nRootless: true")
    print(f"Compose provider: {provider}")
    run([provider, "--version"], env=environment())
    base = validate_repository()
    if STATE.exists():
        report_session(state())
    elif WORKSPACE.exists():
        raise ValueError("Workspace without state; inspect .agent before starting.")
    if not (ROOT / "containers/Containerfile").is_file():
        raise ValueError("Containerfile missing; image cannot be built.")
    compose("config", capture=True)
    print("Agent CLIs: " + (", ".join(AGENTS) or "none (custom sandbox)"))
    print(f"Git repository: valid\nAgent base commit: {base}")
    if not inspect_image:
        return
    present = subprocess.run(["podman", "image", "exists", IMAGE], check=False)
    if present.returncode == 0:
        probe = [
            "podman",
            "run",
            "--rm",
            "--user",
            "1000:1000",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            IMAGE,
        ]
        for agent in AGENTS.values():
            version = run([*probe, agent.cli, "--version"], capture=True)
            print(f"{agent.name} version: {version}")
        if not AGENTS:
            run([*probe, "uv", "--version"])
            configured = custom_command()
            if configured:
                run(
                    [
                        *probe,
                        "python",
                        "-c",
                        "import shutil, sys; sys.exit(0 if shutil.which(sys.argv[1]) else 1)",
                        configured[0],
                    ]
                )
            else:
                print("Custom sandbox: no harness command configured; use make agent-shell.")
        print("Agent environment ready.")
    elif present.returncode == 1:
        print("Image not built: verification pending make agent-start.")
    else:
        raise ValueError("Podman could not inspect the selected agent image.")


VERSION_KEYS = {"codex": "CODEX_VERSION", "claude": "CLAUDE_CODE_VERSION"}
PACKAGES = {"codex": "@openai/codex", "claude": "@anthropic-ai/claude-code"}


def validate_version(value: str) -> str:
    # Stable npm versions only. No tags, ranges, shell syntax, or build options.
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError(f"Invalid harness version {value!r}; expected a stable X.Y.Z version.")
    return value


def harness_versions() -> dict[str, str]:
    values = {}
    for line in VERSIONS_FILE.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key not in VERSION_KEYS.values() or key in values:
            raise ValueError("Invalid or duplicate entry in harness-versions.env.")
        values[key] = validate_version(value)
    for name in AGENTS:
        if VERSION_KEYS[name] not in values:
            raise ValueError(f"Missing pin for {name} in harness-versions.env.")
    return values


def latest_version(name: str) -> str:
    # Host-side HTTPS with a finite timeout. Never evaluate registry data as code.
    with urlopen(f"https://registry.npmjs.org/{PACKAGES[name]}/latest", timeout=30) as response:
        return validate_version(json.load(response)["version"])


def parsed_version(name: str, output: str) -> str:
    pattern = (
        r"codex-cli (\d+\.\d+\.\d+)" if name == "codex" else r"(\d+\.\d+\.\d+) \(Claude Code\)"
    )
    match = re.fullmatch(pattern, output.strip())
    if match is None:
        raise ValueError(f"Unexpected {name} --version output: {output!r}")
    return validate_version(match[1])


def image_version(image: str, name: str) -> str:
    return parsed_version(
        name,
        run(
            [
                "podman",
                "run",
                "--rm",
                "--pull=never",
                "--network=none",
                "--user",
                "1000:1000",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                image,
                AGENTS[name].cli,
                "--version",
            ],
            capture=True,
        ),
    )


def versions() -> None:
    report_profile()
    configured = harness_versions() if AGENTS else {}
    container = None
    available = False
    if AGENTS and shutil.which("podman"):
        try:
            container = agent_container()
            available = (
                subprocess.run(
                    ["podman", "image", "exists", IMAGE],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    for name, agent in AGENTS.items():
        installed = "unavailable (image/container not available)"
        if container is not None and container["State"]["Running"]:
            installed = parsed_version(
                name,
                compose(
                    "exec",
                    "-T",
                    "agent",
                    agent.cli,
                    "--version",
                    capture=True,
                ),
            )
        elif container is not None or available:
            installed = image_version(container["Image"] if container else IMAGE, name)
        pin = configured[VERSION_KEYS[name]]
        print(f"\n{agent.name}:\n  configured: {pin}\n  installed:  {installed}")
        if installed != pin and not installed.startswith("unavailable"):
            print(
                f"WARNING: Configured {agent.name} version differs from the running image."
                "\nRun:\n\n    make agent-rebuild"
            )


def update_check() -> None:
    configured = harness_versions()
    report_profile()
    for name, agent in AGENTS.items():
        current = configured[VERSION_KEYS[name]]
        latest = latest_version(name)
        status = (
            "up to date"
            if latest == current
            else "update available"
            if tuple(map(int, latest.split("."))) > tuple(map(int, current.split(".")))
            else "configured version is newer"
        )
        print(
            f"{agent.name}:\n  configured:       {current}"
            f"\n  latest available: {latest}\n  {status}"
        )


def require_stopped() -> dict[str, Any] | None:
    container = agent_container()
    if container is not None and container["State"]["Running"]:
        raise ValueError(
            "Agent container is currently in use.\n"
            "Stop the interactive session before updating:\n\n"
            "    make agent-stop\n    make agent-update (or make agent-rebuild)"
        )
    return container


def write_pins(content: str) -> None:
    # Resolve the master's shared-source symlink, and replace the file atomically.
    path = VERSIONS_FILE.resolve()
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def rebuild(*, updates: dict[str, str] | None = None) -> None:
    check(inspect_image=False)
    container = require_stopped()
    if STATE.exists():
        read_state()  # Check profile without refreshing/rebasing the Git workspace.
    pins = harness_versions() if AGENTS else {}
    original = VERSIONS_FILE.read_text() if AGENTS else ""
    desired = dict(pins)
    desired.update(updates or {})
    candidate = IMAGE + "-candidate-" + uuid4().hex
    args = [
        "podman",
        "build",
        "--target",
        BUILD_TARGET,
        "--file",
        str(ROOT / "containers/Containerfile"),
        "--tag",
        candidate,
    ]
    for name in AGENTS:
        key = VERSION_KEYS[name]
        args.extend(["--build-arg", f"{key}={validate_version(desired[key])}"])
    previous = None
    present = subprocess.run(["podman", "image", "exists", IMAGE], check=False)
    if present.returncode == 0:
        previous = run(
            ["podman", "image", "inspect", "--format", "{{ '{{' }}.Id{{ '}}' }}", IMAGE],
            capture=True,
        )
    elif present.returncode != 1:
        raise ValueError("Podman could not inspect the selected agent image.")
    activated = False
    try:
        print("Building candidate agent image...", flush=True)
        run([*args, str(ROOT)])
        for name in AGENTS:
            if image_version(candidate, name) != desired[VERSION_KEYS[name]]:
                raise ValueError(f"Candidate {name} version differs from the requested pin.")
        require_stopped()  # Recheck after a potentially long build.
        if AGENTS and VERSIONS_FILE.read_text() != original:
            raise ValueError("Harness pins changed during the build; retry after review.")
        if updates:
            content = original
            for key, value in updates.items():
                content = re.sub(rf"(?m)^{key}=.*$", f"{key}={value}", content)
            write_pins(content)
        activated = True
        run(["podman", "tag", candidate, IMAGE])
        if container is not None:
            # No down --volumes, no prepare/start/uv sync, no Git operation.
            # Recreate only the agent service and leave it stopped after verification.
            compose("up", "-d", "--no-build", "--force-recreate", "agent")
            try:
                for name, agent in AGENTS.items():
                    actual = parsed_version(
                        name,
                        compose(
                            "exec",
                            "-T",
                            "agent",
                            agent.cli,
                            "--version",
                            capture=True,
                        ),
                    )
                    if actual != desired[VERSION_KEYS[name]]:
                        raise ValueError(f"Activated {name} version differs from its pin.")
            finally:
                compose("stop", "agent")
        for name, agent in AGENTS.items():
            key = VERSION_KEYS[name]
            print(f"{agent.name}: {pins[key]} → {desired[key]}")
        print(
            "Credentials: preserved\nWorkspace: preserved\nState: preserved\n"
            "Agent image ready. Run make agent-start or make agent."
        )
    except BaseException:
        if activated:
            try:
                if updates:
                    write_pins(original)
            finally:
                if previous:
                    run(["podman", "tag", previous, IMAGE])
                else:
                    run(["podman", "untag", IMAGE])
                if container is not None and previous:
                    compose("up", "-d", "--no-build", "--force-recreate", "agent")
                    compose("stop", "agent")
        raise
    finally:
        # Remove only our temporary tag; retain previous images/layers for recovery.
        subprocess.run(
            ["podman", "untag", candidate],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def update(provider: str | None, version: str | None) -> None:
    if not AGENTS:
        raise ValueError("This profile has no managed official harnesses; use agent-rebuild.")
    names = [provider] if provider else list(AGENTS)
    if any(name not in AGENTS for name in names):
        raise ValueError(f"Harness is not installed by profile {PROFILE!r}.")
    if version is not None and not provider:
        raise ValueError("VERSION requires agent-update-codex or agent-update-claude.")
    if version is not None:
        validate_version(version)
    require_stopped()
    targets = {
        VERSION_KEYS[name]: version if version is not None else latest_version(name)
        for name in names
    }
    rebuild(updates=targets)


def start() -> None:
    check()
    session = prepare()
    present = subprocess.run(["podman", "image", "exists", IMAGE], check=False)
    if present.returncode == 1:
        compose("build")
    elif present.returncode != 0:
        raise ValueError("Podman could not inspect the agent image.")
    start_stack(session)
    uid = compose("exec", "-T", "agent", "id", "-u", capture=True)
    if not uid.isdecimal() or int(uid) == 0:
        compose("stop")
        raise ValueError("Sandbox must execute as a non-root user.")
    compose("exec", "-T", "agent", "uv", "sync", "--locked")
    for agent in AGENTS.values():
        compose("exec", "-T", "agent", agent.cli, "--version")
    compose("exec", "-T", "agent", "node", "--version")
    compose("exec", "-T", "agent", "npm", "--version")


def diff() -> None:
    result = state()
    for args in (
        ("status", "--short"),
        ("log", "--oneline", f"{result['base']}..HEAD"),
        ("diff", "--no-ext-diff", "--no-textconv", "--stat", result["base"]),
        ("diff", "--no-ext-diff", "--no-textconv", result["base"]),
    ):
        git(WORKSPACE, *args, capture=False)


def apply() -> None:
    if shutil.which("podman") and running_containers():
        raise ValueError("Stop the sandbox with make agent-stop before applying commits.")
    result = state()
    clean_repository(ROOT)
    clean_repository(WORKSPACE)
    if git(ROOT, "rev-parse", "HEAD") != result["base"]:
        raise ValueError("Primary HEAD must equal the session base. No changes applied.")
    git(WORKSPACE, "merge-base", "--is-ancestor", result["base"], "HEAD")
    if git(WORKSPACE, "rev-list", "--merges", f"{result['base']}..HEAD"):
        raise ValueError("Merge commits are unsupported; prepare a linear agent branch.")
    commits = git(WORKSPACE, "rev-list", "--reverse", f"{result['base']}..HEAD").splitlines()
    if not commits:
        raise ValueError("No agent commits to apply. Commit reviewed changes in the clone first.")
    # Serve objects from a fresh bare repository, never execute upload-pack
    # with agent-controlled config or hooks. The running sandbox should be stopped.
    with tempfile.TemporaryDirectory(prefix="agent-recovery-") as directory:
        recovery = Path(directory) / "repository.git"
        run(["git", "init", "--bare", str(recovery)], capture=True)
        shutil.copytree(WORKSPACE / ".git/objects", recovery / "objects", dirs_exist_ok=True)
        git(recovery, "update-ref", "refs/heads/recovery", commits[-1])
        git(
            ROOT,
            "-c",
            "protocol.file.allow=always",
            "fetch",
            "--no-tags",
            "--no-recurse-submodules",
            "--upload-pack=git-upload-pack",
            str(recovery),
            "refs/heads/recovery",
            capture=False,
        )
    if git(ROOT, "rev-parse", "FETCH_HEAD") != commits[-1]:
        raise ValueError("Agent HEAD changed during recovery; stop the agent and retry.")
    try:
        git(ROOT, "cherry-pick", *commits, capture=False)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            "Cherry-pick stopped. Inspect git status; resolve and run "
            "git cherry-pick --continue, or git cherry-pick --abort."
        ) from exc
    print("Commits applied locally. Stop/archive this session before creating another. No push.")


def status() -> None:
    result = state()
    report_session(result)
    container = agent_container()
    running = container is not None and container["State"]["Running"]
    if running and container is not None:
        result["ports"] = published_ports(container)
        STATE.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Agent: {'running' if running else 'stopped'}")
    print("Runtime: Podman rootless")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"preferred_ports", "ports"}
            },
            indent=2,
        )
    )
    report_profile()
    if PROFILE == "both":
        print(f"Default provider: {default_provider()}")
    print("Published services:" if running else "Last published services (currently stopped):")
    for name, port in result.get("ports", {}).items():
        print(f"{name.title()}: http://127.0.0.1:{port}")
    if not result.get("ports"):
        print("No effective ports recorded; run make agent-start.")
    print(run(["podman", "info", "--format", "rootless={{ '{{' }}.Host.Security.Rootless{{ '}}' }}"], capture=True))
    compose("ps")


@contextmanager
def locked() -> Iterator[None]:
    if STATE_DIR.is_symlink():
        raise ValueError(".agent must not be a symlink.")
    STATE_DIR.mkdir(exist_ok=True)
    with (STATE_DIR / "host.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "check",
            "start",
            "rebuild",
            "versions",
            "update-check",
            "update",
            "refresh",
            "rebase",
            "archive",
            "run",
            "login",
            "shell",
            "stop",
            "status",
            "logs",
            "diff",
            "test",
            "apply",
            "clean",
        ],
    )
    parser.add_argument("--provider", choices=["codex", "claude"])
    parser.add_argument("--version", default=os.environ.get("VERSION"))
    options = parser.parse_args()
    command = options.command
    try:
        agent = None
        argv: tuple[str, ...] = ()
        if options.provider and command not in {"run", "login", "update"}:
            raise ValueError("--provider is only supported for run/login/update.")
        if command in {"run", "login"}:
            agent = selected_agent(options.provider)
            if PROFILE == "custom":
                if command == "login":
                    raise ValueError(
                        "Custom authentication is harness-specific; use make agent-shell."
                    )
                argv = custom_command()
        if command == "versions":
            versions()
            return
        if command == "update-check":
            update_check()
            return
        with locked():
            if command == "check":
                check()
            elif command == "update":
                update(options.provider, options.version)
            elif command == "rebuild":
                rebuild()
            elif command == "refresh":
                refresh()
            elif command == "rebase":
                rebase_session()
            elif command == "archive":
                archive_session()
            elif command in {"start", "run", "login"}:
                start()
            elif command in {"shell", "test"}:
                state()
                args = ["bash"] if command == "shell" else ["make", "check"]
                compose("exec", *([] if command == "shell" else ["-T"]), "agent", *args)
            elif command in {"stop", "clean", "logs"}:
                state(allow_profile_mismatch=command in {"stop", "clean"})
                compose({"stop": "stop", "clean": "down", "logs": "logs"}[command])
                if command == "clean":
                    print("Clone and persistent volumes preserved. No credentials deleted.")
            elif command == "diff":
                diff()
            elif command == "apply":
                apply()
            else:
                status()
        # Release the host lifecycle lock during the interactive session so a
        # second terminal can inspect status/diff or stop the sandbox.
        if command == "run":
            if agent is not None:
                compose("exec", "agent", *agent.launch)
            elif argv:
                compose("exec", *([] if sys.stdin.isatty() else ["-T"]), "agent", *argv)
            else:
                print(
                    "Custom agent sandbox is ready, but no harness command is configured.\n\n"
                    "Open the sandbox:\n\n    make agent-shell\n\n"
                    "or configure a harness command and rebuild the agent image."
                )
        elif command == "login":
            assert agent is not None
            compose("exec", "agent", *agent.login)
    except subprocess.CalledProcessError as exc:
        # argv can contain custom CLI arguments; never echo them in wrapper errors.
        sys.exit(f"Agent command failed with exit code {exc.returncode}; see command output above.")
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        sys.exit(f"Agent: {exc}")


if __name__ == "__main__":
    main()
