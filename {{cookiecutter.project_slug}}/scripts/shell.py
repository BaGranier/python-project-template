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
    old_venv = os.environ.get("VIRTUAL_ENV")
    excluded = {str(venv / "bin")}
    if old_venv:
        excluded.add(str(Path(old_venv) / "bin"))
    entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry not in excluded]
    env["PATH"] = os.pathsep.join([str(venv / "bin"), *entries])
    env.pop("PYTHONHOME", None)
    return executable, env


def main() -> None:
    try:
        shell = os.environ.get("SHELL") or shutil.which("bash") or "zsh"
        executable, env = shell_environment(Path.cwd(), shell)
    except ValueError as exc:
        sys.exit(str(exc))
    # Normal startup files load existing aliases, prompt, plugins and completions.
    flags = ["-i"]
    print(f"Entering {executable} with {env['VIRTUAL_ENV']}; use exit to return.", flush=True)
    os.execve(executable, [executable, *flags], env)


if __name__ == "__main__":
    main()
