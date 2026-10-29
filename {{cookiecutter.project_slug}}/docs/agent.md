# Coding agent

Selected profile: **{{ cookiecutter.coding_agent }}**.
All enabled profiles share one rootless Podman sandbox, clone and Git recovery workflow.
`both` installs Codex and Claude Code; `custom` installs no coding harness. See [security](agent-security.md) and
[Podman setup](podman.md) for the common boundary and host prerequisites.

## First launch and authentication

```bash
make init
make agent-check
{% if cookiecutter.coding_agent == 'custom' %}
make agent-start
make agent-shell
{% else %}
make agent-login
make agent
{% endif %}
```

The agent stack explicitly uses the installed `podman-compose` provider;
no per-session export is necessary. Install it on the host if check reports
it missing. Development Compose selection remains independent.
Check validates the rootless engine, selected provider/config, independent Git
repository/base and CLI when the image exists. Before the first build, it
reports CLI verification as pending; start builds and verifies it.
{% if cookiecutter.coding_agent in ['codex', 'both'] %}

Codex is launched with `--no-daemon` inside the Podman sandbox. The Codex
background app-server is unnecessary for this workflow and would otherwise
require additional process-management utilities in the minimal agent image.
Its internal sandbox is bypassed with `--dangerously-bypass-approvals-and-sandbox`;
the rootless, non-root Podman sandbox is the security boundary. Never run this
command directly on the host checkout outside that sandbox.

`{{ 'make agent-login-codex' if cookiecutter.coding_agent == 'both' else 'make agent-login' }}` runs `codex login --device-auth` inside the container.
Open the displayed URL in your host browser, sign in with ChatGPT, and enter
the one-time code. Enable device-code login in your ChatGPT security/workspace
settings if required. No OAuth port forwarding is added. The pinned CLI's
`codex login --help` supports this flag. From `make agent-shell`, check your
session with `codex login status`; do not print or copy auth files.

Configuration and file-based authentication live in `/home/agent/.codex`
(`CODEX_HOME`), persisted by `{{ cookiecutter.project_slug }}-agent-codex-home`.
The host's real Codex directory is never mounted.

Official references: [Codex CLI](https://learn.chatgpt.com/docs/cli),
[ChatGPT/Codex authentication](https://learn.chatgpt.com/docs/auth).
{% endif %}
{% if cookiecutter.coding_agent in ['claude', 'both'] %}

`{{ 'make agent-login-claude' if cookiecutter.coding_agent == 'both' else 'make agent-login' }}` runs `claude auth login` inside the container. For an
individual claude.ai subscription, follow the standard subscription sign-in.
In WSL2, SSH or containers the browser may not reach the local callback:
copy the displayed login URL (press `c` when offered), open it in the host
browser, complete sign-in, then paste the returned code at Claude's terminal
prompt when requested. No host networking or OAuth port range is needed.
From `make agent-shell`, use `claude auth status --text` to check the session.

`CLAUDE_CONFIG_DIR=/home/agent/.claude` is persisted by
`{{ cookiecutter.project_slug }}-agent-claude-home`. On Linux the standard
claude.ai credential file is `.credentials.json` under this directory.
Other authentication modes (cloud providers, API helpers, federation profiles)
can use different stores and are not configured by this template. No host
credential directories are copied or mounted. Never run `claude /init` over the
provided `CLAUDE.md`; it already contains the shared repository conventions.
CLI auto-update is disabled in the image; update the Containerfile pin and rebuild.

Official references: [Claude Code setup](https://code.claude.com/docs/en/setup),
[authentication](https://code.claude.com/docs/en/authentication).
{% endif %}

## Lifecycle and persistence

{% if cookiecutter.coding_agent == 'both' %}
### Both: one clone, two harnesses

```bash
make agent-login-codex
make agent-login-claude
make agent-codex
# Exit Codex before switching:
make agent-claude
```

`make agent` and `make agent-login` use `AGENT_DEFAULT_PROVIDER=codex` from
`.env`; set it to `claude` to change the default. Switching commands never
creates another clone, Python environment or container. The two credential
volumes remain independent; reconnecting one provider does not delete the other.

The template does not launch both automatically or serialize interactive work.
Running two interactive agents concurrently in the shared clone can cause
overlapping edits, Git conflicts and concurrent commits. Prefer sequential use.
Both instruction files are generated from one common source and have identical rules.
{% endif %}
{% if cookiecutter.coding_agent == 'custom' %}
### Custom: reproducible harness installation

`custom` means “I want an isolated agent sandbox but will choose/install the
coding harness myself.” `none` means “I do not want agent infrastructure.”
Custom contains Python, uv, Git, curl, Make, Bash/Zsh, CA certificates, build
tools and shared Node/npm, but no Codex or Claude CLI. No harness-specific
instruction file is generated; use CONTRIBUTING.md and the project guides and
integrate those conventions with your chosen tool. This is not a universal
instruction-file standard.

For quick exploration, install tools in `make agent-shell` as the non-root
user. npm's runtime prefix is `/home/agent/.local`, on PATH. Installations in
the container's writable filesystem can disappear on recreation. The `.local`
and `.config` named volumes persist useful user tools/configuration, but do not
cover all harness storage layouts.

For durable installs, edit `containers/agent-custom-install.sh` on the host.
It is a no-op initially and runs **as agent** during the image build. Install
version-pinned packages or binaries there. Build-time npm uses `/opt/agent-tools`;
standalone binaries should go in `/opt/agent-tools/bin`. This image-owned path
is ahead of `.local/bin` and is not masked by a stale tools volume on rebuild.

```bash
# Example inside containers/agent-custom-install.sh:
npm install -g your-harness-package@an-exact-version
```

Configure `.env`, without storing tokens in command arguments:

```dotenv
CUSTOM_AGENT_COMMAND=your-harness
CUSTOM_AGENT_ARGS=--option "value with spaces"
```

Command and arguments are split into argv; no host shell, eval, environment
expansion, pipelines or redirections are interpreted. Do not quote the entire
command+arguments as one executable name. Secrets must use an appropriate
credential store or explicitly reviewed runtime injection, not command arguments.

Commit the build recipe before the first sandbox session, then:

```bash
make agent-rebuild
make agent
```

Rebuild requires a stopped stack (`make agent-stop` first), builds a candidate
image, and keeps the clone, state and volumes. An existing container is recreated
and left stopped after verification; the next start resumes it. If a session already exists,
review its work when primary HEAD changes. An idle clean session refreshes
automatically; otherwise use `make agent-rebase` or `make agent-archive`. Never silently reset a
clone to pick up a host commit. Empty CUSTOM_AGENT_COMMAND starts the sandbox
and explains `make agent-shell` rather than pretending a harness is available.

Some harnesses store credentials in a specific directory under HOME. Add a
dedicated named volume for `/home/agent/.my-harness` if needed; never mount the
host HOME or host `.config`. Do not embed credentials in the install script.
{% endif %}

### Ports across projects

`AGENT_APP_PORT`, `AGENT_JUPYTER_PORT` and `AGENT_DOCS_PORT` in `.env` are
preferred localhost ports. Start keeps free preferences and automatically
selects available alternatives for collisions, without changing `.env` or
stopping another project. Use `make agent-status` for the actual service URLs;
do not assume the values in `.env` are currently published.

Effective ports are recorded under `ports` in `.agent/state.json` (`app`,
`jupyter`, `docs` for enabled services). Restart prefers the previous mapping
when it is available. Changing a preferred value in `.env` takes priority at
the next stopped-agent startup. A running agent keeps its current mapping
until stopped; status reads live Podman publications, including legacy sessions.
All bindings remain `127.0.0.1`. `agent-stop` releases the ports, while
`agent-clean` removes only this project's stack and preserves credentials.

Port reservations must be released before Podman binds them. A competing start
in that handoff window triggers up to three allocation/start attempts;
unrelated startup errors are reported immediately.

For a manual multi-project smoke test, initialize two projects with different
slugs and the same default preferences. Run `make agent-start` in each without
stopping the first, then `make agent-status` in both. Confirm distinct localhost
URLs. Stop the first and confirm the second still responds. No account login
is needed for this noninteractive lifecycle check.

### Commands and retained state

Use `agent-start`, `agent-shell`, `agent-status`, `agent-logs`, `agent-test`,
`agent-stop` and `agent-clean` through Make. Stop/clean preserve the workspace
and configuration volume. Clean removes the Compose stack, not authentication.
Profile metadata is stored outside the clone in `.agent/state.json`, with
`default_provider` for both. Legacy `provider` metadata is recognized for
single-provider sessions (a missing provider means Codex). A different profile
is rejected. To change profiles, run `make agent-archive` (also supported for an
old-profile session), then rebuild/start. The archived clone retains all work.
Credential volumes are never removed; existing
Codex/Claude volume names stay unchanged when switching to both.

Before recovery, commit in the clone, run `make agent-diff` and
`make agent-test`, stop the sandbox and run `make agent-apply`.
The primary checkout must be clean and compatible with the saved base.
No hard reset or push is performed.

## Agent session lifecycle

The primary checkout belongs to the user. The independent agent workspace has
a saved base commit (`base` in `.agent/state.json`) and an `agent/<timestamp>`
branch. A session is stale when primary HEAD differs from that base.
Refresh/rebase/archive never change primary HEAD. Status/check report stale
state and whether refresh is safe, without refreshing it.

Normal workflow: `make agent`, local agent commits, review/test, stop, then
`make agent-apply`. If primary advances with no remaining agent work, simply
run `make agent` / `make agent-start` again for automatic refresh. Dirty/untracked
files, unfinished Git operations and unapplied commits block replacement.
Git patch comparison recognizes ordinary cherry-picks already in primary;
empty commits, unintegrated merges and rewritten histories are retained conservatively.

| Command | Behavior |
| --- | --- |
| `make agent-clean` | Clean runtime resources only; retain workspace/state/volumes. |
| `make agent-refresh` | Explicit safe recreation on current primary HEAD. |
| `make agent-rebase` | Rebase clean linear agent commits onto current primary HEAD. |
| `make agent-archive` | Preserve and retire even dirty/divergent work for a new session. |

The host removes the old runtime before replacement and checks the stopped
workspace again. It never passes `--volumes`: authentication/custom volumes stay.
Old workspace and state move to `.agent/archive/<timestamp>/` without copying
large trees; ignored local files remain available too. Archives are not pruned
automatically and may consume disk; review before manual deletion. A failed new
clone does not delete the archived predecessor. Previous ports are reused when
available, with localhost fallback otherwise. All profiles share this lifecycle.
No redundant reset-session or credential-cleaning command is introduced.

Rebase requires clean primary/agent trees and no pending operation. The host
temporarily disables clone-configured hooks, filters, merge drivers and editors.
Host inspections also disable clean/process filters; filter-dependent repositories
may require manual review rather than automatic refresh.
Conflicts remain visible, with the runtime stopped:

```bash
git -C .agent/workspace status
# Resolve/stage files and explicitly choose:
git -C .agent/workspace rebase --continue
# Or:
git -C .agent/workspace rebase --abort
make agent-rebase  # reconcile metadata after completion/abort
```

No automatic abort, reset or push occurs. After rebase, test/review before
`make agent-apply`; its unchanged-base and clean-tree guards remain mandatory.
Host Podman is required to stop/remove the runtime before session changes.
Grafts and replace objects are disabled for inspections. The former
`GIT_GRAFT_FILE=/dev/null` caused a deprecation warning itself; the empty setting
disables grafts without creating a file or suppressing warning advice.

{% if cookiecutter.coding_agent != 'custom' %}
## Manual account persistence validation

Real authentication is deliberately not automated by pytest. On the host:

1. Run `make agent-login`, then `make agent`; confirm authentication works.
2. Exit, run `make agent-stop`, `make agent-start`, then `make agent` again.
3. Run `make agent-clean`, `make agent-start`, then `make agent` again. Confirm
   login remains present after container recreation without deleting volumes.
4. Verify no credential files appeared in `git status` or the project directory.

Do not include codes, auth-file contents or tokens in logs/issues. Automated
runtime tests use a non-secret volume sentinel, never a real account.
{% endif %}

{% if cookiecutter.coding_agent != 'custom' %}
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
{% endif %}
