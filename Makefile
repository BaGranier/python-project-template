.DEFAULT_GOAL := help
.PHONY: help setup test lint format-check typecheck check generate-default
help: ## List maintenance commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  %-22s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
setup: ## Install the template tooling
	uv sync
test: ## Run generation and Git isolation tests
	uv run pytest
lint: ## Lint template maintenance code
	uv run ruff check tests
format-check: ## Check maintenance code formatting
	uv run ruff format --check tests
typecheck: ## Type check the generator tests
	uv run mypy
check: lint format-check typecheck test ## Validate the template
generate-default: ## Generate defaults in generated/ (must not exist already)
	uv run cookiecutter . --no-input --output-dir generated
