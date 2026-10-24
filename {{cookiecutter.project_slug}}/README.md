# {{ cookiecutter.project_name }}

{{ cookiecutter.description }}

Requires uv, Git and Make. Supported: Linux/WSL2, bash/zsh. macOS is initially
best effort; native Windows, PowerShell and cmd.exe are outside this version.

```bash
cruft create <template>  # run from your desired parent directory, e.g. ~/projects
cd {{ cookiecutter.project_slug }}
make init
make shell
make check
```

`make init` creates an independent project-local Git repository, runs setup,
installs pre-commit and creates the first commit. Configure `git config --global
user.name` and `git config --global user.email` first. It never commits changes
automatically when an initial commit already exists. `make setup` only prepares
or synchronizes the environment and hooks; it never initializes or commits Git.
The template's ignored `generated/` directory is for disposable smoke tests,
not the recommended location for your real project.

Use `exit` to leave the activated child shell. uv remains directly available:
`uv add pandas`, `uv remove pandas`, `uv sync`, `uv run pytest`, `uv tree`, `uv build`.
Commit pyproject.toml, uv.lock and .python-version together.

Main commands: `make help`, `make test`, `make lint`, `make format`,
`make typecheck`, `make check`, `make build`. `make clean` only removes caches
and build outputs; it preserves data and artifacts.

Code lives in `src/{{ cookiecutter.package_name }}/`, tests in `tests/unit/` and
`tests/integration/`, local datasets in `data/`, outputs in `artifacts/`, and
non-secret configuration in `configs/`.
{% if cookiecutter.enable_notebooks == 'yes' %}

Exploration lives in `notebooks/*.py` using Jupytext `py:percent`.
Run `uv run jupytext --to ipynb notebooks/01_example.py`, then `make notebook`.
Save paired notebooks in JupyterLab; commit the `.py` file only.
{% endif %}
{% if cookiecutter.enable_docs == 'yes' %}

Versioned documentation: `docs/`. Preview with `make docs-serve`
(http://localhost:8001), build with `make docs-build`.
{% endif %}
{% if cookiecutter.dev_container_runtime != 'none' %}

Reproducible development uses {{ cookiecutter.dev_container_runtime }} Compose:
`make dev-up`, `make dev-shell`, `make dev-down`. Edit ports in `.env`.
The container has its own uv environment. For Docker on Linux, the checkout
must be writable by container UID 1000; use Podman's keep-id mapping otherwise.
{% endif %}
{% if cookiecutter.enable_agent == 'yes' %}

Secure agent: install/configure **Podman rootless** and a Compose provider
(`podman-compose` or Docker Compose as a provider for Podman). After `make init`,
run `make agent-check` and `make agent`.
Codex runs as non-root in an independent clone, with dedicated authentication
storage. First sign-in may require `codex login --device-auth` in `make agent-shell`.
The primary checkout must be clean. Review with `make agent-diff`, test with
`make agent-test`, commit inside the agent, stop it, then `make agent-apply`.
Nothing is pushed. `make agent-clean` preserves the clone and credential volume.

The container is the security boundary: Codex's internal approval/sandbox layer
is disabled there for autonomous development. Outbound Internet is enabled;
all committed files provided to the clone are readable by the agent. Do not
commit secrets. Host HOME, engine sockets and the primary checkout are never mounted.
{% if cookiecutter.enable_docs == 'yes' %}
See [agent security](docs/agent-security.md) for the threat model and limitations.
See [Podman setup](docs/podman.md) for rootless installation, socket and diagnostics.
{% endif %}
{% endif %}
