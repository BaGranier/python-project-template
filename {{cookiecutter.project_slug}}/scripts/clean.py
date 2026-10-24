"""Only remove explicitly named reproducible outputs, never project data."""

import shutil
from pathlib import Path


def main() -> None:
    for name in (".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist", "site"):
        path = Path(name)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
    print("Caches/build outputs removed. Data, artifacts and agent resources preserved.")


if __name__ == "__main__":
    main()
