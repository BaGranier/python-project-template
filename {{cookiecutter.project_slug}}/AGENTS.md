# Repository purpose

{{ cookiecutter.project_name }} (`{{ cookiecutter.package_name }}`): {{ cookiecutter.description }}

## Tooling and sources of truth

Use uv, uv_build, Make, Ruff, mypy, pytest and pre-commit.
{% if cookiecutter.enable_notebooks == 'yes' %}Use Jupytext for notebooks.
{% endif %}
{% if cookiecutter.enable_docs == 'yes' %}Use MkDocs Material for documentation.
{% endif %}
Sources of truth: `pyproject.toml`, `uv.lock`, `.python-version`.
Use `uv add`, `uv remove`, `uv sync`. No requirements.txt or Poetry without request.
First-time project initialization: `make init` creates local Git, environment,
hooks and the first commit. `make setup` only synchronizes environment/hooks.

## Structure

`src/`: reusable package; `tests/`: unit/integration tests;
`data/`: local datasets; `artifacts/`: local outputs; `configs/`: non-secret config.
{% if cookiecutter.enable_notebooks == 'yes' %}
`notebooks/`: exploration. Jupytext `.py` is the source of truth; `.ipynb` is local.
{% endif %}
{% if cookiecutter.enable_docs == 'yes' %}
`docs/`: versioned wiki and ADRs.
{% endif %}
{% if cookiecutter.dev_container_runtime != 'none' or cookiecutter.enable_agent == 'yes' %}
`containers/`: shared image definition and enabled Compose stacks.
{% endif %}

## Before modifying and testing

Inspect `git status --short`, `git branch --show-current`, `git log -5 --oneline`
and the relevant code. Run targeted tests, then `make check` when appropriate.
Never report tests as green unless actually executed. Preserve unrelated changes.
Do not push without request or use destructive Git commands. Create clean local
commits when the ticket asks for them. Never delete data via routine cleanup.
{% if cookiecutter.enable_agent == 'yes' %}

## Agent environment

The supported sandbox uses Podman rootless and an independent Git clone.
You may freely change your workspace, dependencies, lock, tests and documentation.
Do not access the host system, Podman/Docker sockets or escalate privileges.
The host controls sandbox rebuilds and application of reviewed commits.
{% endif %}
