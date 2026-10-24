# Architecture

`src/{{ cookiecutter.package_name }}/` is an installable pure Python package in src layout.
uv installs it editable for local development; imports never require sys.path hacks.
uv_build creates wheels and sdists. Its module-name is explicit so the package
may differ from the normalized distribution name.

`tests/unit/` checks small behavior; `tests/integration/` checks the public entrypoint.
`configs/` holds non-secret configuration. Real data in `data/` and outputs in
`artifacts/` remain local and are excluded from image build contexts.
{% if cookiecutter.dev_container_runtime != 'none' or cookiecutter.enable_agent == 'yes' %}

The host, development container and agent use independent environments with
the same Python definition and uv lock. One Containerfile shares OS and tools.
{% endif %}
