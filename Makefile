.DEFAULT_GOAL := help
.PHONY: help setup test lint format-check typecheck check generate-default clean-generated
help: ## List maintenance commands
	@awk -v hidden="$(AGENT_UPDATE_HIDDEN)" 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {if ($$1 !~ hidden) printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
setup: ## Install the template tooling
	uv sync
	@test -e .env || cp .env.example .env
shell: setup ## Open a child Bash/Zsh with the template environment
	uv run python scripts/master_shell.py
.PHONY: test-disk-report
test-disk-report: ## Report retained pytest data and largest fixtures (read-only)
	uv run python scripts/disk_usage.py pytest-report
test: ## Run generation and Git isolation tests
	uv run pytest
lint: ## Lint template maintenance code
	uv run ruff check tests scripts
format-check: ## Check maintenance code formatting
	uv run ruff format --check tests scripts
typecheck: ## Type check the generator tests
	uv run mypy
check: lint format-check typecheck test ## Validate the template
generate-default: ## Generate a disposable validation example in generated/
	uv run cookiecutter . --no-input --output-dir generated
	@printf '%s\n' 'Generated project created for template validation only.' '' 'Path:' 'generated/my-python-project' '' 'This directory is disposable and ignored by Git.' '' 'For a real project, run Cruft from the parent directory where' 'you want the new repository to live.'
clean-generated: ## Explicitly delete only the disposable generated/ directory
	uv run python scripts/clean_generated.py

.PHONY: shell agent-sync agent agent-check agent-login agent-start agent-shell agent-status agent-logs agent-diff agent-test agent-apply agent-stop agent-clean agent-rebuild agent-codex agent-claude agent-login-codex agent-login-claude
agent-sync: ## Refresh master build files from shared generator sources
	uv run python scripts/master_agent.py
agent: ## Start the isolated template sandbox and selected harness
	uv run python scripts/agent.py run
agent-check: ## Diagnose rootless Podman, profile, image and Git
	uv run python scripts/agent.py check
agent-login: ## Authenticate the default provider in its dedicated volume
	uv run python scripts/agent.py login
agent-start: ## Start the template agent without an interactive harness
	uv run python scripts/agent.py start
agent-shell: ## Open the container's own shell
	uv run python scripts/agent.py shell
agent-status: ## Show the template session and effective ports
	uv run python scripts/agent.py status
agent-logs: ## Show this sandbox's logs
	uv run python scripts/agent.py logs
agent-diff: ## Review isolated commits and working changes
	uv run python scripts/agent.py diff
agent-test: ## Run make check inside the sandbox (host runtime tests may skip)
	uv run python scripts/agent.py test
agent-apply: ## Cherry-pick reviewed agent commits locally (stop first)
	uv run python scripts/agent.py apply

.PHONY: agent-disk agent-clean-temp agent-clean-cache
agent-disk: ## Diagnose project disk usage without deleting anything
	uv run python scripts/agent.py disk
agent-clean-temp: ## Delete retained pytest data inside the agent (tests must be idle)
	uv run python scripts/agent.py clean-temp
agent-clean-cache: ## Explicitly clean agent uv/npm caches; preserve credentials and work
	uv run python scripts/agent.py clean-cache
agent-stop: ## Remove disposable runtime; preserve workspace, state and volumes
	uv run python scripts/agent.py stop
agent-clean: ## Remove stack/network; preserve clone, state and credential volumes
	uv run python scripts/agent.py clean
agent-rebuild: ## Rebuild the selected profile; preserve clone and volumes
	uv run python scripts/agent.py rebuild
.PHONY: agent-refresh agent-rebase agent-archive
agent-refresh: ## Safely recreate the workspace on current primary HEAD
	uv run python scripts/agent.py refresh
agent-rebase: ## Rebase clean agent commits onto primary HEAD; leave conflicts explicit
	uv run python scripts/agent.py rebase
agent-archive: ## Retire the current workspace/state without deleting work or credentials
	uv run python scripts/agent.py archive
agent-codex: ## Open Codex in the shared sandbox (profile must include it)
	uv run python scripts/agent.py run --provider codex
agent-claude: ## Open Claude in the shared sandbox (profile must include it)
	uv run python scripts/agent.py run --provider claude
agent-login-codex: ## Authenticate Codex in its dedicated volume
	uv run python scripts/agent.py login --provider codex
agent-login-claude: ## Authenticate Claude in its dedicated volume
	uv run python scripts/agent.py login --provider claude

AGENT_PROFILE ?= $(or $(shell awk -F= '/^AGENT_PROFILE=/ {print $$2}' .env 2>/dev/null),both)
AGENT_UPDATE_HIDDEN := ^$$
ifeq ($(AGENT_PROFILE),custom)
AGENT_UPDATE_HIDDEN := ^agent-(versions|update)
else ifeq ($(AGENT_PROFILE),codex)
AGENT_UPDATE_HIDDEN := ^agent-update-claude$$
else ifeq ($(AGENT_PROFILE),claude)
AGENT_UPDATE_HIDDEN := ^agent-update-codex$$
endif
ifneq ($(AGENT_PROFILE),custom)

.PHONY: agent-versions agent-update-check agent-update
ifneq ($(origin VERSION),undefined)
export VERSION
endif
agent-versions: ## Show configured/installed harness versions
	uv run python scripts/agent.py versions
agent-update-check: ## Check for available harness updates
	uv run python scripts/agent.py update-check
agent-update: ## Update all installed official harnesses
	uv run python scripts/agent.py update
ifneq ($(AGENT_PROFILE),claude)
.PHONY: agent-update-codex
agent-update-codex: ## Update Codex
	uv run python scripts/agent.py update --provider codex
endif
ifneq ($(AGENT_PROFILE),codex)
.PHONY: agent-update-claude
agent-update-claude: ## Update Claude Code
	uv run python scripts/agent.py update --provider claude
endif
endif
