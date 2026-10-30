"""Read-only disk diagnostics and narrowly scoped, explicit agent cache cleanup."""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

GENERATOR_CACHE = Path("/home/agent/.cache/uv")
NPM_CACHE = Path("/home/agent/.npm")
AGENT_TEST_ROOT = Path("/tmp/pytest-of-agent")


def allocated_size(path: Path) -> int:
    """Count allocated bytes once per inode, without following links or mounts."""
    seen: set[tuple[int, int]] = set()
    try:
        device = path.lstat().st_dev
    except FileNotFoundError:
        return 0
    pending = [path]
    total = 0
    while pending:
        item = pending.pop()
        info = item.lstat()
        key = (info.st_dev, info.st_ino)
        if key in seen or info.st_dev != device:
            continue
        seen.add(key)
        total += info.st_blocks * 512
        if item.is_dir() and not item.is_symlink():
            pending.extend(item.iterdir())
    return total


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def show(path: Path, label: str | None = None) -> None:
    try:
        print(f"{label or path}: {human_size(allocated_size(path))}", flush=True)
    except OSError as exc:
        print(f"{label or path}: unavailable ({exc.strerror})", flush=True)


def pytest_report(root: Path | None = None) -> None:
    if root is None:
        parent = Path(os.environ.get("PYTEST_DEBUG_TEMPROOT", tempfile.gettempdir()))
        root = parent / f"pytest-of-{getpass.getuser()}"
    show(root, "pytest temp root " + str(root))
    if not root.is_dir() or root.is_symlink():
        return
    entries = [
        child
        for session in root.iterdir()
        if session.is_dir() and not session.is_symlink()
        for child in session.iterdir()
        if child.is_dir() and not child.is_symlink()
    ]
    print("Largest retained entries (allocated sizes; nested .venv shown separately):")
    sizes = sorted(((allocated_size(path), path) for path in entries), reverse=True)
    for size, path in sizes[:15]:
        print(f"  {human_size(size):>12}  {path}")
        for environment in path.glob("*/.venv"):
            if not environment.is_symlink():
                show(environment, "    .venv")


def require_agent_runtime() -> None:
    if (
        os.getuid() != 1000
        or Path.home() != Path("/home/agent")
        or not Path("/run/.containerenv").is_file()
    ):
        raise ValueError("Cleanup is only supported inside the non-root Podman agent runtime.")


def safe_path(path: Path) -> None:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError(f"Refusing cleanup through a symlink: {path}")


def require_idle_tests() -> None:
    safe_path(AGENT_TEST_ROOT)
    if not AGENT_TEST_ROOT.exists():
        return
    for lock in AGENT_TEST_ROOT.glob("pytest-*/.lock"):
        if lock.is_symlink():
            raise ValueError("Refusing a symlinked pytest lock.")
        try:
            pid = int(lock.read_text())
            if pid <= 0:
                raise ValueError("Invalid pytest lock PID.")
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        raise ValueError(
            "A pytest session may be active; finish it before cleaning temporary data."
        )


def clean_temp() -> None:
    require_agent_runtime()
    require_idle_tests()
    print(f"Deleting retained pytest temporary data only: {AGENT_TEST_ROOT}", flush=True)
    show(AGENT_TEST_ROOT)
    if AGENT_TEST_ROOT.exists():
        shutil.rmtree(AGENT_TEST_ROOT)


def clean_cache() -> None:
    require_agent_runtime()
    require_idle_tests()
    for path in (GENERATOR_CACHE, NPM_CACHE):
        safe_path(path)
        print(f"Cleaning regenerable cache: {path}", flush=True)
        show(path)
    subprocess.run(["uv", "cache", "clean", "--cache-dir", str(GENERATOR_CACHE)], check=True)
    subprocess.run(["npm", "cache", "clean", "--force", "--cache", str(NPM_CACHE)], check=True)
    print("Credentials, workspace, state, venv and custom harness volumes preserved.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "pytest-report",
            "runtime-report",
            "path",
            "clean-temp",
            "clean-cache",
        ],
    )
    parser.add_argument("path", nargs="?", type=Path)
    options = parser.parse_args()
    if options.command == "pytest-report":
        pytest_report(options.path)
    elif options.command == "runtime-report":
        for path in (
            Path("/tmp"),
            AGENT_TEST_ROOT,
            Path("/workspace"),
            GENERATOR_CACHE,
            NPM_CACHE,
            Path("/opt/venv"),
        ):
            show(path)
    elif options.command == "path":
        if options.path is None:
            parser.error("path requires a path to measure")
        show(options.path)
    elif options.command == "clean-temp":
        clean_temp()
    else:
        clean_cache()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"Disk usage: {exc}") from exc
