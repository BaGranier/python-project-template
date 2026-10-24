.DEFAULT_GOAL := help
.PHONY: help setup test lint format-check typecheck check generate-default clean-generated
help: ## List maintenance commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
setup: ## Install the template tooling
	uv sync
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
