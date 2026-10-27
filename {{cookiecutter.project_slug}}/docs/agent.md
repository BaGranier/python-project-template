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

Rebuild stops this project's stack, rebuilds its image and keeps the clone and
volumes. The next start recreates the container. If a session already exists,
preserve/apply its work and archive it after cleaning when the primary HEAD
changes; the unchanged-base guard remains mandatory. Never silently reset a
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
is rejected. To change profiles, run `make agent-clean` (also supported for an
old-profile session), retain all unmerged work, then archive `.agent` outside
the checkout and rebuild/start. Credential volumes are never removed; existing
Codex/Claude volume names stay unchanged when switching to both.

Before recovery, commit in the clone, run `make agent-diff` and
`make agent-test`, stop the sandbox and run `make agent-apply`.
The primary checkout must be clean and compatible with the saved base.
No hard reset or push is performed.

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
