"""Run explicitly configured application argv, independently of template tooling."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = ("setup", "format", "format-check", "lint", "typecheck", "test", "build", "docs-build")


def execute(name: str) -> None:
    config = json.loads((ROOT / ".template/project.json").read_text())
    commands = config.get("commands", {})
    steps = commands.get(name, [])
    if not isinstance(steps, list):
        raise ValueError(f"{name}: expected a list of command objects")
    validated = []
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"argv", "cwd"}:
            raise ValueError("Expected command objects with argv and optional cwd")
        argv = step.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or not arg or "\0" in arg for arg in argv)
        ):
            raise ValueError("argv must contain nonempty strings")
        cwd = (ROOT / step.get("cwd", ".")).resolve()
        if not cwd.is_relative_to(ROOT) or not cwd.is_dir():
            raise ValueError("Command cwd must be a directory inside the repository")
        validated.append((argv, cwd))
    if not validated:
        print(f"No application command configured for {name}; edit .template/project.json.")
    for argv, cwd in validated:
        subprocess.run(argv, cwd=cwd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*COMMANDS, "check"])
    name = parser.parse_args().command
    for command in ("format-check", "lint", "typecheck", "test") if name == "check" else (name,):
        execute(command)


if __name__ == "__main__":
    main()
