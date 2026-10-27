# Contributing

Install uv, Git and Make; run `make init` once, then `make shell`.
Use `make setup` to synchronize an existing development environment; it never
creates a Git repository or commit. Configure your Git identity yourself.
Use bash/zsh on Linux or WSL2. The child shell preserves the environment and
exits normally with `exit`; normal Bash/Zsh startup files and existing Oh My Zsh are loaded.

Add/remove dependencies with `uv add` / `uv remove` (use `--group` for tooling).
Commit the resulting uv.lock. Use `make format`, focused tests, then `make check`
and `make build` before review. Git hooks check lightweight file/code conventions;
they do not run the full suite. Separate reusable code from exploration.
{% if cookiecutter.enable_docs == 'yes' %}
Update `docs/` with behavior changes and run `make docs-build`.
Record substantial design decisions under `docs/adr/`.
{% endif %}
{% if cookiecutter.enable_notebooks == 'yes' %}
Use paired Jupytext percent scripts; `.ipynb` files are local artifacts.
{% endif %}

Inspect Git status before editing. Preserve unrelated work, keep commits focused,
use descriptive conventional commit messages, and never commit secrets or datasets.
Push only when explicitly requested. Resolve template updates with `cruft diff`
and `cruft update`, then run the project checks again.
