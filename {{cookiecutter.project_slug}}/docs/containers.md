# Containers

{% if cookiecutter.dev_container_runtime == 'podman' or cookiecutter.enable_agent == 'yes' %}
Start with the [Podman rootless installation and diagnostics guide](podman.md),
including the user socket, Compose smoke test and WSL2 troubleshooting.
{% endif %}

The shared Containerfile provides base → dev and, when enabled, base → agent.
Python's image follows `.python-version` at generation time; change both on a
Python upgrade. uv and Codex versions are pinned; OS package revisions and base
tags can change. For stricter supply-chain reproducibility, resolve and pin
image digests in your deployment environment and rebuild regularly.
{% if cookiecutter.dev_container_runtime != 'none' %}

Development runtime: {{ cookiecutter.dev_container_runtime }} with a Compose provider.
Run `make dev-up`, `make dev-shell`, `make dev-logs`, `make dev-down`.
The main checkout is mounted read/write for human development. The image uses
UID 1000. Podman maps the invoking user to this UID using keep-id; Docker users
must ensure checkout ownership permits UID 1000 writes.
{% endif %}

Container environments use `/opt/venv` and their own uv cache volumes.
The host `.venv` is never used by uv inside the container, even if visible
through the human development bind mount. Set ports in `.env` before startup.
Host bindings default to 127.0.0.1; application servers inside the container
must listen on 0.0.0.0 so Podman's port forwarding reaches them.
{% if cookiecutter.enable_agent == 'yes' %}

The agent always uses rootless Podman regardless of the human development runtime.
See [security and lifecycle](agent-security.md). Agent image rebuilds happen
on the host: stop the sandbox, review Containerfile changes, then use
`AGENT_WORKSPACE="$PWD/.agent/workspace" podman compose --env-file .env -f containers/compose.agent.yaml build`.
Apply Containerfile changes to the primary checkout before building; agent code
cannot command the host engine. Restart/recreate the stack after rebuilding.

To add PostgreSQL or Redis, edit `containers/compose.agent.yaml` on the host.
Add a service on its Compose network with a dedicated volume and runtime
credentials; connect using the service DNS name from the agent. Do not publish
database ports unless required, mount host credentials, or expose engine sockets.
No database service is imposed by this template.
{% endif %}
