"""Safe first-run setup after uv sync."""

import shutil
import subprocess
from pathlib import Path


def main() -> None:
    target = Path(".env")
    if not target.exists():
        with target.open("x") as output:
            output.write(Path(".env.example").read_text())
    if shutil.which("git"):
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
        if result.returncode == 0 and Path(result.stdout.strip()).resolve() == Path.cwd().resolve():
            subprocess.run(["uv", "run", "pre-commit", "install"], check=True)
    print("Ready. Run make shell, then make check. uv is also directly available.")


if __name__ == "__main__":
    main()
