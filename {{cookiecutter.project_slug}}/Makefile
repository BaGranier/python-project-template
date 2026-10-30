SHELL := /bin/bash
.DEFAULT_GOAL := help
{% if cookiecutter.dev_container_runtime != 'none' %}
RUNTIME := {{ cookiecutter.dev_container_runtime }}
COMPOSE := $(RUNTIME) compose --env-file .env -f containers/compose.yaml
{% endif %}
.PHONY: help init setup sync shell format format-check lint typecheck test test-unit test-integration coverage check build clean
help: ## Show available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
init: ## Initialize an independent Git repo, environment, hooks and first commit
	uv run --no-project --python "$$(cat .python-version)" python scripts/init_project.py
setup: ## Synchronize environment and hooks; never initialize or commit Git
	uv sync
	uv run python scripts/setup.py
sync: ## Synchronize the environment (uv remains directly usable)
	uv sync
shell: sync ## Enter an activated bash/zsh child shell; exit to return
	uv run python scripts/shell.py
format: ## Apply Ruff lint fixes and formatting
	uv run ruff check --fix .
	uv run ruff format .
format-check: ## Check formatting
	uv run ruff format --check .
lint: ## Run Ruff lint
	uv run ruff check .
typecheck: ## Run strict mypy
	uv run mypy
.PHONY: test-disk-report
test-disk-report: ## Report retained pytest data and largest fixtures (read-only)
	uv run python scripts/disk_usage.py pytest-report
test: ## Run all tests
	uv run pytest
test-unit: ## Run unit tests
	uv run pytest tests/unit
test-integration: ## Run integration tests
	uv run pytest tests/integration
coverage: ## Run tests with package coverage
	uv run pytest --cov --cov-report=term-missing
check: lint format-check typecheck test ## Run all quality checks
build: ## Build wheel and source distribution with uv_build
	uv build
{% if cookiecutter.enable_notebooks == 'yes' %}
.PHONY: notebook
notebook: ## Launch JupyterLab; text notebooks are the Git source
	uv run jupyter lab --ip=0.0.0.0 --port=8888 --no-browser
{% endif %}
{% if cookiecutter.enable_docs == 'yes' %}
.PHONY: docs-serve docs-build
docs-serve: ## Serve documentation (container port 8001)
	uv run mkdocs serve --dev-addr=0.0.0.0:8001
docs-build: ## Build documentation in site/
	uv run mkdocs build --strict
{% endif %}
{% if cookiecutter.dev_container_runtime != 'none' %}
.PHONY: dev-build dev-up dev-down dev-shell dev-logs
dev-build: ## Build the development image
	$(COMPOSE) build
dev-up: ## Start the development container
	@test -f .env || cp .env.example .env
	$(COMPOSE) up -d --build
	$(COMPOSE) exec dev uv sync --locked
dev-down: ## Stop development containers (preserve volumes)
	$(COMPOSE) down
dev-shell: ## Enter the development container
	$(COMPOSE) exec dev zsh
dev-logs: ## Show development logs
	$(COMPOSE) logs
{% endif %}
{% if cookiecutter.coding_agent != 'none' %}
AGENT_PYTHON := $(shell cat .python-version)
AGENT := uv run --no-project --python $(AGENT_PYTHON) python scripts/agent.py
.PHONY: agent agent-check agent-rebuild agent-start agent-shell agent-stop agent-status agent-logs agent-diff agent-test agent-apply agent-clean
agent: ## Start sandbox and launch harness (custom: explain setup if unconfigured)
	$(AGENT) run
agent-rebuild: ## Rebuild the agent image; requires a stopped sandbox
	$(AGENT) rebuild
.PHONY: agent-refresh agent-rebase agent-archive
agent-refresh: ## Safely recreate workspace on current primary HEAD
	$(AGENT) refresh
agent-rebase: ## Rebase clean agent commits onto current primary HEAD
	$(AGENT) rebase
agent-archive: ## Retire workspace/state without deleting work or credentials
	$(AGENT) archive
{% if cookiecutter.coding_agent != 'custom' %}

.PHONY: agent-versions agent-update-check agent-update
ifneq ($(origin VERSION),undefined)
export VERSION
endif
agent-versions: ## Show configured/installed harness versions
	$(AGENT) versions
agent-update-check: ## Check for available harness updates
	$(AGENT) update-check
agent-update: ## Update all installed official harnesses
	$(AGENT) update
{% if cookiecutter.coding_agent in ['codex', 'both'] %}
.PHONY: agent-update-codex
agent-update-codex: ## Update Codex
	$(AGENT) update --provider codex
{% endif %}
{% if cookiecutter.coding_agent in ['claude', 'both'] %}
.PHONY: agent-update-claude
agent-update-claude: ## Update Claude Code
	$(AGENT) update --provider claude
{% endif %}

.PHONY: agent-login
agent-login: ## Start/resume and authenticate the default provider interactively
	$(AGENT) login
{% endif %}
{% if cookiecutter.coding_agent == 'both' %}
.PHONY: agent-codex agent-claude agent-login-codex agent-login-claude
agent-codex: ## Open Codex in the shared sandbox
	$(AGENT) run --provider codex
agent-claude: ## Open Claude Code in the shared sandbox
	$(AGENT) run --provider claude
agent-login-codex: ## Authenticate Codex in its dedicated volume
	$(AGENT) login --provider codex
agent-login-claude: ## Authenticate Claude Code in its dedicated volume
	$(AGENT) login --provider claude
{% endif %}
agent-check: ## Validate Podman rootless, Compose, ports and workspace
	$(AGENT) check
agent-start: ## Start/resume and synchronize the sandbox
	$(AGENT) start
agent-shell: ## Open a shell in the running agent container
	$(AGENT) shell

.PHONY: agent-disk agent-clean-temp agent-clean-cache
agent-disk: ## Diagnose project disk usage without deleting anything
	$(AGENT) disk
agent-clean-temp: ## Delete retained pytest data inside the agent (tests must be idle)
	$(AGENT) clean-temp
agent-clean-cache: ## Explicitly clean agent uv/npm caches; preserve credentials and work
	$(AGENT) clean-cache
agent-stop: ## Remove disposable runtime; preserve workspace, state and volumes
	$(AGENT) stop
agent-status: ## Show rootless/container/Git/port information
	$(AGENT) status
agent-logs: ## Show sandbox logs
	$(AGENT) logs
agent-diff: ## Inspect agent status, commits and changes since base
	$(AGENT) diff
agent-test: ## Run make check inside the agent
	$(AGENT) test
agent-apply: ## Cherry-pick reviewed agent commits into a clean primary checkout
	$(AGENT) apply
agent-clean: ## Remove stopped stack; preserve clone and all persistent volumes
	$(AGENT) clean
{% endif %}
clean: ## Remove reproducible caches only; preserve data, artifacts and agent state
	uv run python scripts/clean.py
