# Template repository

This repository generates other repositories; it is not an application.
Edit generated project files under `{{cookiecutter.project_slug}}/`, hooks under
`hooks/`, and generator tests under `tests/`.

Before modifying, inspect `git status --short`, `git branch --show-current`,
`git log -5 --oneline` and the relevant files. Preserve unrelated work.

Use uv exclusively. Sources of truth: pyproject.toml, uv.lock, .python-version.
During iterative development, run targeted tests then `make check` (fast suite).
Before finalizing template/rendering changes, run `make test-integration`.
Before finalizing container/agent changes, run `make test-runtime` on a host
with the required engine. For full validation, run `make check-full`.
Use validation proportionate to the change: documentation or a small helper
change does not require real container builds. Cover enabled and disabled options.
Valid template source alone is insufficient: generate a real project and run
`make setup`, `make check`, `make build`, and `make docs-build` when applicable.
Never claim unavailable runtime/container checks passed. No push without request.
Agent sandbox changes must preserve rootless Podman, an independent Git clone,
non-root execution, no engine socket or host HOME, and explicit commit recovery.

The master dogfoods the same lifecycle: `make agent` uses an independent
`.agent/workspace` clone and defaults to both harnesses. Never expose a host
engine socket to run integration tests. Runtime tests skip when the engine is
intentionally unavailable; report those skips. See `docs/agent.md` for host
validation and recovery. After editing shared sandbox sources, run
`make agent-sync` and verify the generated master build files.
