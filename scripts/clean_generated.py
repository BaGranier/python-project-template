"""Explicit cleanup of the template's disposable examples only."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / "generated"
    if target.is_symlink():
        raise ValueError("Refusing to clean a generated/ symlink; inspect it manually.")
    if target.exists():
        shutil.rmtree(target)
    print("Disposable generated/ directory removed; no other paths changed.")


if __name__ == "__main__":
    main()
