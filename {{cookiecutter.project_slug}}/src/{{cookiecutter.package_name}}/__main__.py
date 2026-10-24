"""Run the example with uv run python -m {{ cookiecutter.package_name }}."""

from {{ cookiecutter.package_name }} import greet


def main() -> None:
    print(greet())


if __name__ == "__main__":
    main()
