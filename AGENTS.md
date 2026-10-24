# Template repository

This repository generates other repositories; it is not an application.
Edit generated project files under `{{cookiecutter.project_slug}}/`, hooks under
`hooks/`, and generator tests under `tests/`.

Before modifying, inspect `git status --short`, `git branch --show-current`,
`git log -5 --oneline` and the relevant files. Preserve unrelated work.

Use uv exclusively. Sources of truth: pyproject.toml, uv.lock, .python-version.
Run targeted tests then `make check`. Cover enabled and disabled options.
Valid template source alone is insufficient: generate a real project and run
`make setup`, `make check`, `make build`, and `make docs-build` when applicable.
Never claim unavailable runtime/container checks passed. No push without request.
Agent sandbox changes must preserve rootless Podman, an independent Git clone,
non-root execution, no engine socket or host HOME, and explicit commit recovery.
