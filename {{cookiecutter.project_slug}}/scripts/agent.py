"""Host-controlled rootless sandbox. Never execute this helper from agent code."""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".agent"
WORKSPACE = STATE_DIR / "workspace"
STATE = STATE_DIR / "state.json"
IMAGE = "localhost/{{ cookiecutter.project_slug }}-agent:template-v1"
VOLUME = "{{ cookiecutter.project_slug }}-agent-codex-home"
PORTS = {
    "AGENT_APP_PORT": 18000,
{% if cookiecutter.enable_notebooks == 'yes' %}    "AGENT_JUPYTER_PORT": 18888,
{% endif %}{% if cookiecutter.enable_docs == 'yes' %}    "AGENT_DOCS_PORT": 18001,
{% endif %}}


def run(
    args: list[str], cwd: Path = ROOT, capture: bool = False, env: dict[str, str] | None = None
) -> str:
    result = subprocess.run(
        args, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else ""


def git(path: Path, *args: str, capture: bool = True) -> str:
    # The agent controls clone-local Git config. Disable executable Git features
    # for host inspection; never run a script from the clone on the host.
    env = dict(os.environ)
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_GRAFT_FILE"] = "/dev/null"
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
            *args,
        ],
        capture=capture,
        env=env,
    )


def clean_repository(path: Path) -> None:
    if git(path, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError(f"Uncommitted changes in {path}. Commit or stash before continuing.")


def state() -> dict[str, str]:
    if STATE.is_symlink() or WORKSPACE.is_symlink() or STATE_DIR.is_symlink():
        raise ValueError("Agent paths must not be symbolic links.")
    result: dict[str, str] = json.loads(STATE.read_text())
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
    if git(WORKSPACE, "branch", "--show-current") != result["branch"]:
        raise ValueError("Agent changed branch; restore the session branch before continuing.")
    return result


def prepare() -> dict[str, str]:
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
    clean_repository(ROOT)
    if git(ROOT, "check-ignore", ".agent/workspace") != ".agent/workspace":
        raise ValueError(".agent/ must be ignored by the primary repository.")
    if STATE.exists():
        result = state()
        if git(ROOT, "rev-parse", "HEAD") != result["base"]:
            raise ValueError(
                "Primary HEAD changed since session creation. Review/apply or archive "
                ".agent after stopping the sandbox before starting another session."
            )
        return result
    if WORKSPACE.exists():
        raise ValueError("Workspace exists without state. Inspect/archive .agent manually.")
    STATE_DIR.mkdir(exist_ok=True)
    base = git(ROOT, "rev-parse", "HEAD")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
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
    result = {"base": base, "branch": branch, "workspace": str(WORKSPACE), "created": stamp}
    STATE.write_text(json.dumps(result, indent=2) + "\n")
    return result


def environment() -> dict[str, str]:
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
            "PODMAN_COMPOSE_PROVIDER",
        }
    }
    values: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in PORTS:
                values[key.strip()] = value.strip()
    for key, default in PORTS.items():
        value = os.environ.get(key, values.get(key, str(default)))
        if not value.isdecimal() or not 1024 <= int(value) <= 65535:
            raise ValueError(f"{key} must be an unprivileged port (1024..65535).")
        env[key] = value
    if len({env[key] for key in PORTS}) != len(PORTS):
        raise ValueError("Agent published ports must be distinct.")
    env["AGENT_WORKSPACE"] = str(WORKSPACE)
    return env


def compose(*args: str, capture: bool = False) -> str:
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
        env=environment(),
    )


def running_containers() -> bool:
    identifiers = compose("ps", "-q", capture=True).splitlines()
    if not identifiers:
        return False
    containers = json.loads(run(["podman", "inspect", *identifiers], capture=True))
    return any(container["State"]["Running"] for container in containers)


def check() -> None:
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
    run(["podman", "compose", "version"], env=environment())
    if STATE.exists():
        state()
    elif WORKSPACE.exists():
        raise ValueError("Workspace without state; inspect .agent before starting.")
    if not (ROOT / "containers/Containerfile").is_file():
        raise ValueError("Containerfile missing; image cannot be built.")
    compose("config", capture=True)
    print("Podman rootless and Compose available; image will be built on start if absent.")


def start() -> None:
    check()
    prepare()
    # Check availability only before initial startup; a resumed stack owns its ports.
    if not running_containers():
        for key in PORTS:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", int(environment()[key])))
    present = subprocess.run(["podman", "image", "exists", IMAGE], check=False)
    if present.returncode == 1:
        compose("build")
    elif present.returncode != 0:
        raise ValueError("Podman could not inspect the agent image.")
    compose("up", "-d", "--no-build")
    uid = compose("exec", "-T", "agent", "id", "-u", capture=True)
    if not uid.isdecimal() or int(uid) == 0:
        compose("stop")
        raise ValueError("Sandbox must execute as a non-root user.")
    compose("exec", "-T", "agent", "uv", "sync", "--locked")
    compose("exec", "-T", "agent", "codex", "--version")


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
    print("Runtime: Podman rootless")
    print(json.dumps(result, indent=2))
    print(f"Codex home volume: {VOLUME}")
    env = environment()
    for key in PORTS:
        print(f"{key}: 127.0.0.1:{env[key]}")
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
            "run",
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
    command = parser.parse_args().command
    try:
        with locked():
            if command == "check":
                check()
            elif command in {"start", "run"}:
                start()
            elif command in {"shell", "test"}:
                state()
                args = ["bash"] if command == "shell" else ["make", "check"]
                compose("exec", *([] if command == "shell" else ["-T"]), "agent", *args)
            elif command in {"stop", "clean", "logs"}:
                state()
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
            compose("exec", "agent", "codex", "--dangerously-bypass-approvals-and-sandbox")
    except (ValueError, OSError, subprocess.SubprocessError, KeyError) as exc:
        sys.exit(f"Agent: {exc}")


if __name__ == "__main__":
    main()
