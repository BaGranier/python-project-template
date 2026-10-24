"""Testable child-shell setup. No reliance on a transient Make activation."""

import os
import shutil
import sys
from pathlib import Path


def shell_environment(root: Path, shell: str) -> tuple[str, dict[str, str]]:
    executable = shutil.which(shell)
    if Path(shell).name not in {"bash", "zsh"} or executable is None:
        raise ValueError("Set SHELL to an installed bash or zsh executable.")
    venv = Path(os.environ.get("UV_PROJECT_ENVIRONMENT", str(root / ".venv"))).resolve()
    if not (venv / "bin" / "python").is_file():
        raise ValueError("Virtual environment missing; run make setup first.")
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    env.pop("PYTHONHOME", None)
    return executable, env


def main() -> None:
    try:
        executable, env = shell_environment(Path.cwd(), os.environ.get("SHELL", "/bin/bash"))
    except ValueError as exc:
        sys.exit(str(exc))
    # A clean child avoids user startup files resetting PATH or VIRTUAL_ENV.
    flags = ["--norc", "--noprofile", "-i"] if Path(executable).name == "bash" else ["-f", "-i"]
    print(f"Entering {executable} with {env['VIRTUAL_ENV']}; use exit to return.", flush=True)
    os.execve(executable, [executable, *flags], env)


if __name__ == "__main__":
    main()
