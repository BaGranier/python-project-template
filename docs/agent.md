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

Changing profile while a session exists is refused. Use `make agent-archive`
to stop and retain the old workspace/state, then rebuild
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
sources; a test checks exact agreement. Harness versions have a single source in
`{{cookiecutter.project_slug}}/containers/harness-versions.env`; the master
`containers/harness-versions.env` is a relative symlink to that file. Both
updates and `make agent-sync` preserve this link, so a master update changes
the generated-project default in the same Git diff. The Python dependencies always come from root
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
`agent-rebuild` requires a stopped sandbox and transactionally rebuilds the image,
preserving work and credentials.
After applying commits, the next start safely refreshes an idle completed session.

## Agent session lifecycle

The primary checkout is the user's repository. The agent workspace is the
independent `.agent/workspace` clone, with a saved base commit (`base` in
state.json) and an `agent/<timestamp>` branch. A session is stale when primary
HEAD differs from that base. Refresh, rebase and archive never change primary HEAD.

Normal workflow: `make agent`, local agent commits, `make agent-diff`,
`make agent-test`, stop and `make agent-apply`. If primary advances without any
remaining agent work, simply run `make agent` or `make agent-start`: refresh is
automatic. `agent-status` and `agent-check` report stale state without refreshing.

Refresh requires clean primary and agent checkouts, no unfinished Git operation,
and no unapplied commits. A trusted temporary Git object store compares patch IDs
to recognize ordinary cherry-picks already integrated into primary. Empty commits,
unintegrated merges and rewritten histories are retained conservatively.
Dirty/untracked files block replacement. No automatic stash/reset is performed.

| Command | Purpose |
| --- | --- |
| `make agent-clean` | Remove runtime stack/network; retain workspace/state/volumes. |
| `make agent-refresh` | Explicit safe recreation on current primary HEAD. |
| `make agent-rebase` | Rebase clean linear agent commits onto current primary HEAD. |
| `make agent-archive` | Preserve and retire even dirty/divergent work, allowing a fresh session. |

Before replacing a workspace, the host removes its runtime with Compose `down`,
never `--volumes`, and rechecks the stopped workspace. The old clone and state
move to `.agent/archive/<timestamp>/` without copying large trees; ignored local
files are retained too. Archives are not pruned automatically and may consume
disk: review before manually deleting them. Archived metadata retains its original
workspace path. If fresh cloning fails, the archived predecessor remains available.
Codex/Claude/custom volumes survive, and previous ports are reused when available
with the existing localhost fallback. Both harnesses share the new workspace.
No redundant reset-session or credential-destruction command is introduced.

Rebase requires clean primary/agent trees and no pending Git operation. Clone
hooks, filters, merge drivers and editors are disabled during host-side rebase.
Host inspections also disable clean/process filters. Filter-dependent repositories
may therefore require manual review rather than automatic refresh.
Conflicts remain in the workspace, with the runtime stopped:

```bash
git -C .agent/workspace status
# Resolve files and stage them, then explicitly choose:
git -C .agent/workspace rebase --continue
# Or:
git -C .agent/workspace rebase --abort
make agent-rebase  # reconcile metadata after completing/aborting
```

There is no automatic abort, conflict resolution, reset or push. After successful
rebase, test/review before `make agent-apply`, whose unchanged-base and clean-tree
guards still apply. Host Podman is required for teardown before session changes;
pure Git tests mock only this runtime boundary.

The previous `GIT_GRAFT_FILE=/dev/null` caused Git's graft deprecation warning
even without an info/grafts file. An explicit empty setting now disables grafts
without creating a file or suppressing warnings; replace objects remain disabled.

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

## Updating coding harnesses

Harness updates are managed by the Podman image lifecycle rather than by
modifying the running container. Harness binaries are image-managed,
credentials are volume-managed, and the workspace is Git-managed.

`containers/harness-versions.env` records explicit stable npm versions. Commit
its changes to reproduce the environment later. Host `CODEX_VERSION` /
`CLAUDE_CODE_VERSION` variables and `.env` cannot override these pins.
`agent-start` builds a missing image using the pins; it never resolves `latest`.
An existing image is updated only through an explicit update or rebuild.

On the host:

```bash
make agent-versions       # Configured and installed versions; no Internet lookup
make agent-update-check   # Read-only npm registry lookup; network required
make agent-stop           # Exit the interactive session first
make agent-update         # Resolve and update all harnesses in this profile
make agent-start
make agent-versions
```

Provider targets are available only when included in the profile:

```bash
make agent-update-codex
make agent-update-claude
# Controlled upgrade, downgrade, or rollback:
make agent-update-codex VERSION=0.165.0
make agent-update-claude VERSION=2.1.311
```

Without `VERSION`, the registry's stable `latest` tag is resolved to an explicit
`X.Y.Z` pin. Only stable numeric versions are accepted. `VERSION` applies to a
single provider target; omit it for `agent-update`. `agent-update-check` compares
the configured pins to the registry; use `agent-versions` to inspect an older
installed image. Network failures leave the pins and runtime untouched.

Updates and `agent-rebuild` require a stopped container, conservatively treating
any running agent container as in use. Under the host lifecycle lock they build
a separately tagged candidate, then run each installed CLI's `--version` as UID
1000 without a network or credentials. The build itself also asserts the exact
version. Only after all probes pass are the image tag and pins activated.
If activation fails, the old pins and image tag are restored and the old
container is recreated when one existed. If host/engine failure also prevents
recovery, inspect the reported error, restore the recorded pin from Git, then
retry `make agent-rebuild`; do not delete the workspace or credential volumes.

An existing stopped agent container is recreated, verified and left stopped;
if none exists, creation waits for `agent-start`. No clone, reset, checkout,
rebase, or Python synchronization runs during a harness rebuild. Workspace,
`.agent/state.json`, named credential volumes and saved ports are retained.
Port collisions during recreation can fail activation safely; free the saved
port before retrying. Normal startup retains its existing port fallback.
A later commit of the pins uses the normal HEAD/session refresh rules:
unapplied work continues to block automatic workspace refresh.

`agent-check` warns when configured and installed versions differ and suggests
`make agent-rebuild`. A configuration-only report remains available with no
container/image or Podman engine. Custom profiles expose `agent-rebuild`, with
no automatic management of unknown harnesses. The `none` profile has no agent
update targets.

Codex retains `--no-daemon`. Its launcher passes the officially supported
[`check_for_update_on_startup=false`](https://developers.openai.com/codex/config-reference)
configuration so existing credential volumes also avoid startup update prompts.
Claude Code retains the official
[`DISABLE_AUTOUPDATER=1`](https://code.claude.com/docs/en/env-vars)
setting because deployment manages its updates. Direct manual self-update
commands are unnecessary and may fail against the immutable system install.
Neither harness gains root, sudo, capabilities, host HOME, an engine socket,
or write access to `/usr/local/bin` or `/usr/local/lib/node_modules`.

Node/npm also belong to the image. Ignore npm self-update notifications inside
the agent; update Node/npm by changing the Containerfile and rebuilding.
Old image layers are retained. Optional host maintenance: `podman image prune`
after reviewing unused images. No automatic system-wide prune runs.

### Codex update fails with EACCES under /usr/local/lib/node_modules

The npm global install is owned by root at image build time. The runtime runs
as non-root `agent`, so an in-session `npm install -g @openai/codex` cannot
replace it. This permission boundary is intentional. From the host, use:

```bash
exit                      # Leave Codex
make agent-stop
make agent-update-codex
make agent-codex           # Or make agent for a Codex-only generated project
```

Do not use `sudo npm install -g @openai/codex` or make system npm directories
writable. Apply the same image lifecycle to Claude Code updates.

### Manual WSL update and persistence validation

On a rootless Podman WSL/Linux host, run `make agent-versions` and
`make agent-update-check`. If an update exists, exit the harness, stop the
container, update the provider, then start and check the installed versions.
Reopen Codex and Claude sequentially and confirm both existing logins survive
without a new authentication flow. For repeatable rollback testing use an
explicit older `VERSION`, then restore the desired pin. Runtime pytest tests
use non-secret sentinels in both credential volumes, preserve a workspace file
and state across rebuild/recreation, and verify CLI versions and non-root
permissions. They skip when a usable rootless engine is unavailable; real
account persistence requires this manual validation.
