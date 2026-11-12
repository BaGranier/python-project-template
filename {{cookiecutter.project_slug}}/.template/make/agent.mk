{% if cookiecutter.coding_agent != 'none' or cookiecutter._adoption | default('no') == 'yes' %}
TEMPLATE_AGENT_PYTHON := {{ cookiecutter.python_version }}
TEMPLATE_AGENT := uv run --no-project --python $(TEMPLATE_AGENT_PYTHON) python scripts/agent.py
.PHONY: agent agent-check agent-rebuild agent-start agent-shell agent-stop agent-status agent-logs agent-diff agent-test agent-apply agent-clean
agent: ## Start sandbox and launch harness (custom: explain setup if unconfigured)
	$(TEMPLATE_AGENT) run
agent-rebuild: ## Rebuild the agent image; requires a stopped sandbox
	$(TEMPLATE_AGENT) rebuild
.PHONY: agent-refresh agent-rebase agent-archive
agent-refresh: ## Safely recreate workspace on current primary HEAD
	$(TEMPLATE_AGENT) refresh
agent-rebase: ## Rebase clean agent commits onto current primary HEAD
	$(TEMPLATE_AGENT) rebase
agent-archive: ## Retire workspace/state without deleting work or credentials
	$(TEMPLATE_AGENT) archive
{% if cookiecutter.coding_agent not in ['custom', 'none'] %}

.PHONY: agent-versions agent-update-check agent-update
ifneq ($(origin VERSION),undefined)
export VERSION
endif
agent-versions: ## Show configured/installed harness versions
	$(TEMPLATE_AGENT) versions
agent-update-check: ## Check for available harness updates
	$(TEMPLATE_AGENT) update-check
agent-update: ## Update all installed official harnesses
	$(TEMPLATE_AGENT) update
{% if cookiecutter.coding_agent in ['codex', 'both'] %}
.PHONY: agent-update-codex
agent-update-codex: ## Update Codex
	$(TEMPLATE_AGENT) update --provider codex
{% endif %}
{% if cookiecutter.coding_agent in ['claude', 'both'] %}
.PHONY: agent-update-claude
agent-update-claude: ## Update Claude Code
	$(TEMPLATE_AGENT) update --provider claude
{% endif %}

.PHONY: agent-login
agent-login: ## Start/resume and authenticate the default provider interactively
	$(TEMPLATE_AGENT) login
{% endif %}
{% if cookiecutter.coding_agent == 'both' %}
.PHONY: agent-codex agent-claude agent-login-codex agent-login-claude
agent-codex: ## Open Codex in the shared sandbox
	$(TEMPLATE_AGENT) run --provider codex
agent-claude: ## Open Claude Code in the shared sandbox
	$(TEMPLATE_AGENT) run --provider claude
agent-login-codex: ## Authenticate Codex in its dedicated volume
	$(TEMPLATE_AGENT) login --provider codex
agent-login-claude: ## Authenticate Claude Code in its dedicated volume
	$(TEMPLATE_AGENT) login --provider claude
{% endif %}
agent-check: ## Validate Podman rootless, Compose, ports and workspace
	$(TEMPLATE_AGENT) check
agent-start: ## Start/resume and synchronize the sandbox
	$(TEMPLATE_AGENT) start
agent-shell: ## Open a shell in the running agent container
	$(TEMPLATE_AGENT) shell

.PHONY: agent-disk agent-clean-temp agent-clean-cache
agent-disk: ## Diagnose project disk usage without deleting anything
	$(TEMPLATE_AGENT) disk
agent-clean-temp: ## Delete retained pytest data inside the agent (tests must be idle)
	$(TEMPLATE_AGENT) clean-temp
agent-clean-cache: ## Explicitly clean agent uv/npm caches; preserve credentials and work
	$(TEMPLATE_AGENT) clean-cache
agent-stop: ## Remove disposable runtime; preserve workspace, state and volumes
	$(TEMPLATE_AGENT) stop
agent-status: ## Show rootless/container/Git/port information
	$(TEMPLATE_AGENT) status
agent-logs: ## Show sandbox logs
	$(TEMPLATE_AGENT) logs
agent-diff: ## Inspect agent status, commits and changes since base
	$(TEMPLATE_AGENT) diff
agent-test: ## Run make check inside the agent
	$(TEMPLATE_AGENT) test
agent-apply: ## Cherry-pick reviewed agent commits into a clean primary checkout
	$(TEMPLATE_AGENT) apply
agent-clean: ## Remove stopped stack; preserve clone and all persistent volumes
	$(TEMPLATE_AGENT) clean
{% endif %}
