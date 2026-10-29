# The template dogfoods its own agent sandbox

```text
Template repository (source of truth)
        ↓ independent Git clone, no hardlinks
.agent/workspace
        ↓ only host bind mount
Podman rootless / non-root user
        ↓
Codex or Claude Code (same clone, separate credentials)
```

## Developing the template

From Linux/WSL, install/configure [Podman rootless](podman.md) and
`podman-compose`, then:

```bash
cd ~/python-project-template
make setup
make check
make agent-check
make agent-login
make agent
```

No Docker daemon/Desktop is required. No generated project is used to develop
the master. `make shell` reuses the Bash/Zsh helper, including existing user RCs
on the host; `exit` returns to its parent. The agent uses its own container HOME
and shell configuration, with no host RC, Oh My Zsh, or credentials mounted.

`make setup` creates `.env` from `.env.example` only if absent. Defaults:

```dotenv
AGENT_PROFILE=both
AGENT_DEFAULT_PROVIDER=codex
AGENT_APP_PORT=18000
```

Profiles `codex`, `claude`, `both`, and `custom` are supported. Both includes
`make agent-codex`, `make agent-claude`, and separate `agent-login-codex` /
`agent-login-claude`. These commands share one workspace; use them sequentially
to avoid concurrent edits/commits. Explicit provider targets reject unavailable
harnesses in other profiles. Custom has no harness or generic login command;
use `make agent-shell`, edit `containers/agent-custom-install.sh`, set
`CUSTOM_AGENT_COMMAND` / `CUSTOM_AGENT_ARGS`, and `make agent-rebuild`.
The command is parsed as argv without a host shell. Do not put secrets in argv.
Build installs use `/opt/agent-tools`; runtime user tools/config persist in named
`.local` and `.config` volumes. Harness-specific credentials need dedicated
named volumes if stored elsewhere; never mount the host HOME.

Changing profile while a session exists is refused. Stop/clean the old stack,
retain all unmerged work, archive `.agent` outside the checkout, then rebuild
and start the new profile. Credential volumes are preserved, including when
switching between a single provider and both.

## Shared implementation

`scripts/agent.py` is a small master entrypoint. `scripts/master_agent.py` renders
the trusted `{{cookiecutter.project_slug}}/scripts/agent.py` text in memory using
Jinja, with an explicit master context. It does not invoke Cookiecutter, read
`cookiecutter.json` for profile selection, or create another repository skeleton.
The executed helper remains rooted at the master's `scripts/agent.py`, never at
agent-controlled code. Source edits are normal reviewed host changes.

Build files are committed for direct inspection. `make agent-sync` refreshes
one multi-stage Containerfile and four profile Compose manifests from generator
sources; a test checks exact agreement. Versions have a single source in the
generator Containerfile. The Python dependencies always come from root
`pyproject.toml`, `uv.lock`, and `.python-version`; startup runs `uv sync --locked`
in `/opt/venv`, isolated from the host `.venv`. No hand-maintained second Python
environment is baked into the image.

The master publishes only its configured app service (container 8000).
`AGENT_APP_PORT` is a preferred localhost port; collisions allocate another free
127.0.0.1 port, saved in `.agent/state.json`. `agent-status` reports actual ports.
It can coexist with agents for `test-ba`, `test-ba2`, and other projects. Stop
and cleanup address only this project's stack.

## Security and credentials

Same invariants as generated projects: Podman rootless, UID 1000, all capabilities
dropped, no-new-privileges, no privileged mode or host networking. Only the
independent clone is host-bound. No host Git metadata, HOME, SSH/GPG/AWS config,
Docker socket or Podman socket is exposed. Outbound Internet remains available.
An agent can transmit anything it can read: repository contents, explicitly
provided credentials, and accessible network services. This is not absolute
security. Both harnesses run as the same container user and can technically
read each other's mounted config; distinct volumes separate persistence, not
access permissions between harnesses.

Dedicated named volumes:

- `python-project-template-agent-codex-home` → `/home/agent/.codex`
- `python-project-template-agent-claude-home` → `/home/agent/.claude`

Use fresh interactive login, never copy Docker credentials. Codex uses its
pinned CLI's device login; Claude uses `claude auth login`. For a remote/container
browser callback, follow the CLI's URL/code instructions in the host browser.
No OAuth port range or host network is opened. No real login runs in pytest.

Codex is launched with `--no-daemon` inside the Podman sandbox. The Codex
background app-server is unnecessary for this workflow and would otherwise
require additional process-management utilities in the minimal agent image.
Both `make agent-codex` and `make agent` with Codex selected use that shared
provider command. Codex's internal sandbox is bypassed with
`--dangerously-bypass-approvals-and-sandbox`; the rootless, non-root Podman
sandbox, with capabilities dropped and no host HOME or engine sockets, is the
security boundary. Never use that command directly on the host checkout.

`agent-stop` stops the container. `agent-clean` removes the stack/network,
preserving clone, state and all named volumes, including authentication.
`agent-rebuild` stops and rebuilds the image, preserving work and credentials.
After applying commits, archive the old session before creating another base.

## Deliberate host/agent test boundary

Inside the sandbox run `uv sync --locked` and `make check` (also `agent-test`
from the host). Cookiecutter, Cruft create/check/diff/update, Git safety, port
allocation, lint/type checks, and real generated-project setup/check/build/docs
remain executable. Temporary projects use their own venv, never `/opt/venv`.
Pytest reports skipped tests and reasons explicitly.

Shell tests separate environment preparation, interactive `execve` dispatch,
and actual Bash/Zsh RC loading with `-i -c` and a 10-second timeout. They never
drive a persistent interactive shell through a stdin pipe. No PTY or real
Oh My Zsh installation is required in CI. Validate terminal UX manually from
a real WSL terminal in a generated project: `make shell`, then
`echo "$VIRTUAL_ENV"` and `command -v python`. Existing Oh My Zsh should retain
its prompt, aliases and plugins; `exit` must return to the parent shell.

Host-only checks include real Podman builds/startup, mount inspection,
multi-container coexistence, port publishing, engine security and persistent
volume recreation. They skip if the engine is absent/inaccessible. This boundary
is deliberate: **never add an engine socket to make these tests run inside the
agent**. On a complete WSL/Linux host, `make check` remains canonical and runs
these runtime checks too. Failures after detecting a usable runtime remain failures.

## Host acceptance and bootstrap transition

Keep `Dockerfile.dev` and `docker-compose.yaml` until the steps below succeed.
They are historical user-local untracked files, not input to the Podman build.
Move them outside the checkout (and adjust their old bootstrap paths if still
needed), or exclude them locally using `.git/info/exclude`, before starting an
agent: the main worktree must be clean. No automatic stash/reset is performed.
Do not commit them just to satisfy the guard.

### Phase A — runtime

```bash
cd ~/python-project-template
make agent-check
make agent-start
make agent-status
```

### Phase B — environment

```bash
make agent-shell
# Inside the container:
id
git status
uv --version
python --version
echo "$HOME"  # /home/agent
test ! -S /var/run/docker.sock
test ! -S /run/podman/podman.sock
find /run -name '*podman*.sock' -print 2>/dev/null
curl -I https://example.com
uv sync --locked
make check
exit
```

Inspect host mounts with `podman inspect` and confirm only `.agent/workspace`
is a bind; named volumes contain no host personal HOME/config directories.

### Phase C — authentication

```bash
make agent-login
# Or both independently:
make agent-login-codex
make agent-login-claude
make agent-stop
make agent-start
# Recreate, retaining volumes:
make agent-clean
make agent-start
```

Confirm both logins persist after restart and recreation.

### Phase D — real coding session

```bash
make agent
# Separately, on the same clone:
make agent-codex
make agent-claude
```

Give one harness a small documentation-fixture ticket, ask it to run relevant
tests and create a local commit, with no push. Do not run both editing sessions
concurrently. The agent can run all generator tools, including a real temporary
Cookiecutter/Cruft generation; `make check` already exercises those workflows.

### Phase E — review and recovery

```bash
make agent-status
make agent-diff
make agent-test
make agent-stop
make agent-apply
git status --short
git log -1 --oneline
```

Apply requires clean main and clone, unchanged base, reviewed linear commits,
and stopped container. It cherry-picks locally; conflicts stop for explicit
resolution/abort. Never resets or pushes. A temporary-repository test deletes
an important file in the clone, confirms main survives, then imports the commit.

Run host `make check` while other project agents are active to validate ports.
After successful manual acceptance, perform the next ticket entirely via
`make agent` without starting Docker bootstrap. Only then may you manually remove
the historical untracked Docker files. Docker remains a supported **dev runtime
for generated projects**; this migration does not remove that choice.
