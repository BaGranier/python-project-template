# Adopt an existing repository

The repository retains its name `python-project-template`, but its common
infrastructure supports applications beyond Python.

For a new project, from the directory where you keep projects:

```bash
cd ~/projects
uvx cruft create ~/python-project-template
```

Choose `project_profile` independently from `coding_agent`. Python retains the
uv/Ruff/mypy/pytest/build/MkDocs workflow. Other new profiles provide common
infrastructure and empty application command configuration; they do not scaffold
a complete application. `auto` starts as `generic` for a new project.

For an existing repository:

```bash
cd ~/python-project-template
make adopt-dry-run REPO=~/projects/existing-repo
make adopt REPO=~/projects/existing-repo
# Optional independent choices:
make adopt-dry-run REPO=~/projects/existing-repo PROFILE=generic AGENT=both
```

`PROFILE` defaults to `auto`; `AGENT` defaults to `both` and accepts `codex`,
`claude`, `both`, `custom`, `none`. During adoption `none` installs the sandbox
without an official harness. For new Cookiecutter projects `coding_agent=none`
continues to omit the sandbox.

The target must be the root of a Git repository with at least one commit.
Adoption requires a clean working tree, never initializes Git, never stashes,
and never commits automatically. A dry-run can audit a dirty repository and
writes nothing. It prints the audit, ADD/MERGE/REVIEW/SKIP plan and unified diffs,
including the full contents of new files. REVIEW entries describing existing
application manifests, Docker, development containers and CI are informational:
those files remain untouched. Conflicts in required infrastructure files, Make
targets or environment defaults block all writes. Existing instruction files
remain intact with a separate `AGENTS.template.md`/`CLAUDE.template.md` candidate.

Review after adopting:

```bash
cd ~/projects/existing-repo
git status --short
git diff
# New files are untracked: inspect them too before committing.
git add <reviewed-files>
git diff --cached
git commit -m "chore: adopt project template infrastructure"
make agent-check
make agent-start
make agent-status
make agent
```

Commit the infrastructure before starting the agent: the independent workspace
clones committed HEAD, preserving the existing explicit commit recovery model.
Rootless Podman and podman-compose must be available on the host. Never mount an
engine socket to work around an unavailable container runtime. See [agent.md](agent.md)
and [podman.md](podman.md).

| Profile | Python tooling | Node tooling | Agent sandbox |
| --- | --- | --- | --- |
| python | Complete for new projects; existing manager preserved on adoption | Optional | Yes |
| node | Internal control plane only | Existing scripts and package manager | Yes |
| mixed | As configured; detected manifests reported | As configured; detected manifests reported | Yes |
| generic | None imposed on application | None imposed on application | Yes |
| auto | Resolves from detected manifests | Resolves from detected manifests | Yes |

Python is used internally by the template tooling; it does not imply that the
application itself is a Python project. Some template maintenance commands use
a small Python-based control plane internally through `uv run --no-project`.
No application `pyproject.toml`, virtual environment or Python quality tools are
created during adoption. `scripts/agent.py` uses the standard library;
`scripts/shell.py` activates an application Python environment and is therefore
only shipped for new Python projects. Application dependencies and control-plane
tooling remain separate. The agent image contains Python/uv for internal tools,
and Node/npm for official harness installation and Node applications. Their
presence does not select the application stack. Additional runtimes and package
managers (including yarn, pnpm and bun) must be provisioned in the image if used;
no package-manager conversion or version migration is performed.

Detection searches nested manifests, excluding `.git`, `.agent`, `.venv`,
`node_modules`, build outputs and vendor trees, without following symlink
directories. Python package metadata and historical manager files are recognized;
Node lockfiles, declared package manager and TypeScript configuration are
reported. Ambiguous Node lockfiles without a declared manager yield `unknown`
and no inferred commands. Rust, Go, Java and CMake metadata are reported while
the profile remains `generic`. Override the proposal with `PROFILE=...`.

Application commands live in `.template/project.json`. For a root Node application,
only existing lint/test/build/etc. scripts are mapped, with an install command
for the detected manager. No scripts are invented. Mixed monorepos and existing
Python projects need explicit command configuration. For example:

```json
{
  "profile": "mixed",
  "commands": {
    "test": [
      {"argv": ["pnpm", "run", "test"], "cwd": "frontend"},
      {"argv": ["uv", "run", "pytest"], "cwd": "backend"}
    ]
  }
}
```

The runner validates command objects, argv strings and working directories before
execution, and uses subprocess argv without `eval` or `shell=True`. Configured
commands, like package scripts, execute project code: review them as code.
`check` runs format-check, lint, typecheck and test. Empty commands print an
explicit message and succeed. An existing Makefile keeps its targets and default
goal. New targets are added through `.template/make/agent.mk` and
`.template/make/project.mk`; `template-check`, `template-test`, etc. always expose
the configured commands even if historical targets have those names.

`.gitignore` merges missing infrastructure entries by line. `.env.example`
preserves existing values and blocks adoption on differing variable defaults;
the real `.env` is never touched. Docker and CI files remain intact; the sandbox
uses `containers/compose.agent.yaml` and `containers/Containerfile.agent`.

The complete in-memory candidate plan is checked before applying. Changed paths
are checked again, symlink destinations are refused, and a caught write failure
rolls back files and newly created directories. Git remains the recovery mechanism;
there is no full repository backup. Concurrent writers and process termination
cannot be made transactional across an entire filesystem: run adoption while the
repository is idle and inspect Git afterwards.

Cruft is not required. Adoption never creates `.cruft.json` or claims Cookiecutter
ancestry. `.template/adoption.json` records an infrastructure schema version,
template revision, original HEAD, detected stack and hashes of installed files.
These support a future infrastructure-only update mechanism; this ticket does
not implement one. Re-adoption refuses existing adoption metadata. Resolve
conflicts manually and rerun the dry-run on a clean tree. Managed Cruft conversion,
CI replacement and package-manager migration are outside this workflow.

Make integration also recognizes `GNUmakefile` and `makefile` in GNU Make's
precedence order. It preserves existing bytes and the historical default target.
Dynamic target names or includes that cannot be inspected safely require manual
integration and block adoption rather than risking a recipe collision.
