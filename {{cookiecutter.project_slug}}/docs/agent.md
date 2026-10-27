# Coding agent

Selected provider: **{{ 'Codex' if cookiecutter.coding_agent == 'codex' else 'Claude Code' }}**.
The same rootless Podman sandbox and Git recovery workflow serves both choices.
Only the selected CLI is installed. See [security](agent-security.md) and
[Podman setup](podman.md) for the common boundary and host prerequisites.

## First launch and authentication

```bash
make init
make agent-check
make agent-login
make agent
```

The agent stack explicitly uses the installed `podman-compose` provider;
no per-session export is necessary. Install it on the host if check reports
it missing. Development Compose selection remains independent.
Check validates the rootless engine, selected provider/config, independent Git
repository/base and CLI when the image exists. Before the first build, it
reports CLI verification as pending; start builds and verifies it.
{% if cookiecutter.coding_agent == 'codex' %}

`make agent-login` runs `codex login --device-auth` inside the container.
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
{% else %}

`make agent-login` runs `claude auth login` inside the container. For an
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

Use `agent-start`, `agent-shell`, `agent-status`, `agent-logs`, `agent-test`,
`agent-stop` and `agent-clean` through Make. Stop/clean preserve the workspace
and configuration volume. Clean removes the Compose stack, not authentication.
Provider metadata is stored outside the clone in `.agent/state.json`; a
different provider's session is rejected. Legacy sessions without this field
are treated as Codex sessions. Review and archive them before changing providers.

Before recovery, commit in the clone, run `make agent-diff` and
`make agent-test`, stop the sandbox and run `make agent-apply`.
The primary checkout must be clean and compatible with the saved base.
No hard reset or push is performed.

## Manual account persistence validation

Real authentication is deliberately not automated by pytest. On the host:

1. Run `make agent-login`, then `make agent`; confirm authentication works.
2. Exit, run `make agent-stop`, `make agent-start`, then `make agent` again.
3. Run `make agent-clean`, `make agent-start`, then `make agent` again. Confirm
   login remains present after container recreation without deleting volumes.
4. Verify no credential files appeared in `git status` or the project directory.

Do not include codes, auth-file contents or tokens in logs/issues. Automated
runtime tests use a non-secret volume sentinel, never a real account.
