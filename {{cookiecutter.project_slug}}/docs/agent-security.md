# Agent security

## Threat model

Podman rootless is not absolute security. This sandbox primarily limits host
filesystem access, damage to the primary checkout, credential exposure, and
container-engine escalation. Kernel, Podman and dependency vulnerabilities
remain possible; other network-reachable services may still be accessible.
Normal outbound Internet is enabled. **The agent can read and transmit any
secret or sensitive data committed to its repository or explicitly provided.**
This configuration is unsuitable for untrusted repositories containing secrets.

## Boundary and access

The host starts the stack. Codex runs as UID 1000 without sudo, with all Linux
capabilities dropped and no-new-privileges. No privileged mode, host network,
engine socket, host HOME, SSH/GPG/AWS directories or primary Git directory is
mounted. The sole host bind mount is `.agent/workspace` at `/workspace`.
It contains an independent clone with its own objects, no hardlinks, no object
alternates and no origin remote pointing back to the host.

Codex's internal approval/sandbox restrictions are disabled **only inside this
dedicated container**. The container provides the boundary and permits normal
uv/Git/test/server work without repeatedly asking for host permissions.
It does not contain a container engine. Rebuilds and service changes are host actions.

## Start and authentication

Install Podman rootless plus a working Compose provider. See the
[rootless setup guide](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md).
Configure subordinate UID/GID ranges and newuidmap/newgidmap as required by
your distribution. `podman info` must report rootless. No helper runs sudo.

Run `make agent-check`, commit/stash changes in the main checkout, then
`make agent`. Existing clones resume only while primary HEAD equals the saved
base. State (base, branch, workspace, timestamp) lives in `.agent/state.json`,
outside the mounted workspace. The branch is `agent/<UTC timestamp>`.

Codex authentication persists in the project-specific named volume
`{{ cookiecutter.project_slug }}-agent-codex-home`; the real `~/.codex` is never mounted.
For first sign-in, use Codex interactively, or `make agent-shell` followed by
`codex login --device-auth`. Never bake keys into images or commit them.
No API key or host `.env` is automatically forwarded. If needed, explicitly
pass a runtime variable through a locally reviewed Compose override (and keep
that file ignored); this grants the agent access to that credential.

## Ports and network

Set AGENT_APP_PORT, and the enabled documentation/notebook ports, in `.env`
before startup. Host bindings are 127.0.0.1 only; container ports are 8000,
8888 and 8001 as enabled. To test, launch
`uv run python -m http.server 8000 --bind 0.0.0.0` inside `make agent-shell`,
then visit `http://127.0.0.1:18000` (or the configured port) on the host.
Inside the container use `curl http://localhost:8000`.
No rebuild is needed for the preconfigured ports. A normal Compose network
allows outbound traffic; this is not an egress-filtering firewall.

## Review and recovery

Use `make agent-status`, `make agent-logs`, `make agent-diff`, `make agent-test`.
Diff includes status, commits, tracked diff/stat from base; inspect untracked
files listed by status separately. Commit desired changes inside the clone.
Stop the sandbox before recovery to avoid concurrent changes.
`make agent-apply` requires both checkouts clean, unchanged primary HEAD equal
to base, a compatible linear history and agent commits. It fetches local objects
and cherry-picks commits without pushing. Conflicts remain visible: inspect
`git status` and use `git cherry-pick --continue` or `git cherry-pick --abort`.
No automatic hard reset or clean is used. Review commits before applying them:
applied code, hooks and CI become trusted project content.

`make agent-stop` stops containers; `make agent-clean` removes the stack/network
while retaining the clone and all named volumes, including authentication.
After completing a session, stop/clean, then manually move `.agent` to a safe
archive outside the checkout before starting a new session. This explicit step
preserves uncommitted work. Named volumes persist between sessions; use distinct
project slugs for distinct projects. Delete credential volumes only deliberately
with Podman after confirming they are no longer needed.
