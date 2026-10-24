# Testing

Run `make test-unit` or `make test-integration` during development, then
`make check` and `make build`. `make coverage` reports package coverage.
Ruff replaces separate Black/isort/Flake8 tools. Strict mypy covers src, tests
and helper scripts. pre-commit checks lightweight file conventions and Ruff;
the full tests remain an explicit local/CI operation.

The shell helper exposes environment calculation separately from os.execve.
Interactive startup is intended for a terminal; automated environment checks
do not establish prompt rendering or terminal integration on every system.
