# Development

Use `uv add`, `uv remove`, `uv sync`, `uv tree`, `uv run` directly or the Make
shortcuts. Dependency groups `test` and `lint` are aggregated by `dev`.
{% if cookiecutter.enable_notebooks == 'yes' %}`notebook` is also included.
{% endif %}
The documentation group `docs` is included too. Commit pyproject.toml, uv.lock,
and .python-version. `make format` applies Ruff, `make check` runs lint, format
validation, strict mypy and pytest, and `make build` invokes uv_build.

`make clean` deletes named caches and build outputs only. Data, artifacts,
environments and persistent sandbox resources are preserved.

`make docs-serve` serves on port 8001; `make docs-build` validates links/navigation
strictly and writes the ignored `site/` directory.
{% if cookiecutter.ci_provider == 'github' %}

For Pages, enable **GitHub Actions** under repository Settings → Pages.
The Pages workflow builds on the default branch and supports manual dispatch.
Set repository/environment permissions according to your organization policy.
{% elif cookiecutter.ci_provider == 'gitlab' %}

GitLab CI publishes `public/` via Pages on the default branch. Enable Pages in
the project settings and inspect the deployment URL in Deploy → Pages.
{% endif %}
