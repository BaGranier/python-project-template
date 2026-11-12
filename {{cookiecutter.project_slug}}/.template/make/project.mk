# Python/uv runs the control plane without reading application Python metadata.
TEMPLATE_PYTHON := uv run --no-project --python 3.12 python
.PHONY: setup format format-check lint typecheck test check build docs-build
setup format format-check lint typecheck test check build docs-build:
	$(TEMPLATE_PYTHON) scripts/project.py $@
