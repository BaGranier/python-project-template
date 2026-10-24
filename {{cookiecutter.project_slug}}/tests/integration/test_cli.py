import subprocess
import sys


def test_module_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "{{ cookiecutter.package_name }}"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "Hello, world!"
