"""Reuse the generator's child-shell helper with the master's current directory."""

import runpy
from pathlib import Path

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    runpy.run_path(
        str(root / "{{cookiecutter.project_slug}}/scripts/shell.py"), run_name="__main__"
    )
