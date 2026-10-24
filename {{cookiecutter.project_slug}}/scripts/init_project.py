"""Initialize this project only; never stage or commit a parent repository."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=check
    )


def initialize() -> None:
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
        if key in os.environ:
            raise ValueError(f"Unset {key} before make init to avoid redirecting Git operations.")
    local_git = ROOT / ".git"
    pending = local_git / "template-init-pending"
    if local_git.is_symlink() or (local_git.exists() and not local_git.is_dir()):
        raise ValueError(
            "Expected a project-local .git directory; linked worktrees are unsupported."
        )
    if not local_git.exists():
        detected = git("rev-parse", "--show-toplevel", check=False)
        if detected.returncode == 0:
            print("Parent Git repository detected; creating an independent project repository.")
        git("init", "-b", "main")
        pending.touch()
        print("Git repository: initialized")
    else:
        print("Git repository: already initialized")
    if Path(git("rev-parse", "--show-toplevel").stdout.strip()).resolve() != ROOT:
        raise ValueError("Git root does not match the project root. No files staged or committed.")
    has_commit = git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    if not has_commit:
        for key in ("user.name", "user.email"):
            identity = git("config", "--get", key, check=False)
            if identity.returncode != 0 or not identity.stdout.strip():
                raise ValueError(
                    "Git identity is not configured.\n\nConfigure it with:\n\n"
                    'git config --global user.name "Your Name"\n'
                    'git config --global user.email "you@example.com"\n\n'
                    "Then rerun:\n\nmake init"
                )
        if not pending.exists():
            raise ValueError(
                "Existing repository has no commit. Review its files and create the first commit "
                "manually, then rerun make init. Existing work will not be committed automatically."
            )
    # Keep setup as the single implementation of sync, .env and hook installation.
    subprocess.run(["make", "setup"], cwd=ROOT, check=True)
    if has_commit:
        print("Initial commit: already present; existing changes preserved")
    else:
        print("Creating the initial commit from non-ignored project files.", flush=True)
        git("add", ".")
        subprocess.run(["git", "commit", "-m", "chore: initialize project"], cwd=ROOT, check=True)
        pending.unlink()
        print("Initial commit: created")
    print("Environment: synchronized\nPre-commit: installed\nProject ready.")


if __name__ == "__main__":
    try:
        initialize()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Initialization: {exc}\nCorrect the problem and rerun make init.")
