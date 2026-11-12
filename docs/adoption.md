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
writes nothing. The default dry-run prints a concise adoption summary: Git state,
detected/selected stack, agent profile, action counts and bounded file lists.
ADD lists paths; MERGE lists changed-line counts. REVIEW entries describing existing
application manifests, Docker, development containers and CI are informational:
those files remain untouched. Conflicts in required infrastructure files, Make
targets or environment defaults block all writes. Existing instruction files
remain intact with a separate `AGENTS.template.md`/`CLAUDE.template.md` candidate.

Output levels are available from Make and the native CLI:

```bash
# Concise overview; default lists are bounded, BLOCK lists are never truncated.
make adopt-dry-run REPO=~/projects/existing-repo
# Full classification, manifests, Python tools, package managers, commands, merge diffs:
make adopt-dry-run REPO=~/projects/existing-repo VERBOSE=1
# Complete proposed diffs and new-file contents, without writing anything:
make adopt-diff REPO=~/projects/existing-repo
# Internal audit, sections, candidate decisions, sizes, hashes and metadata:
make adopt-dry-run REPO=~/projects/existing-repo DEBUG=1

uv run python scripts/adopt.py --repo ~/projects/existing-repo --dry-run --verbose
uv run python scripts/adopt.py --repo ~/projects/existing-repo --diff
uv run python scripts/adopt.py --repo ~/projects/existing-repo --dry-run --debug
```

`DEBUG=1` includes the verbose level. Both flags accept `1/true/yes` and
`0/false/no` (case insensitive); `VERBOSE=0` and `DEBUG=0` stay concise.
`--dry-run` and `--diff` are mutually exclusive and both read-only. They create no
candidate files or temporary files inside the target, stash or commit. Use
`VERBOSE=1` to expand all path lists; use `adopt-diff` to inspect new file contents.
Verbose dry-run includes only merge diffs; debug adds implementation diagnostics,
not a machine output contract. There is no existing machine-output consumer and
no JSON mode is introduced by this change.

`make adopt` prints what was added, merged and preserved, counts and next steps.
It prints no full file payloads or diffs, including with verbose/debug flags.
Normal plans and success go to stdout; blockers, write failures and errors go to
stderr. All blocking conflicts are displayed independently of list limits;
REVIEW is informational and leaves those files intact. Dirty adoption is refused
with a commit/stash instruction, while dirty previews remain allowed. Expected
errors have no traceback by default. For unexpected failures, rerun with
`DEBUG=1` for a traceback. Write failures report completed rollback when it was
completed; failures during rollback remain errors requiring Git inspection.

For repositories not yet adopted, the complete candidate plan is computed and
validated in every output mode. Console verbosity does not change the audit, hashes, classification,
transactional guards, installed files or `.template/adoption.json` format.
A concise default reduces terminal/CI output and agent context usage while
keeping the result and conflicts visible. Prefer the normal dry-run during
iteration and reserve debug for diagnosis.

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

Discovery scans project source/configuration rather than every file physically
present below the repository root. A single traversal prunes excluded directories
before descending, for manifests, CI, Docker/Compose, development containers and
Make include analysis alike. Directory symlinks are never followed.

Exclusions apply at every depth: `.git`, `.agent`, `.template`, `.venv`, `venv`,
`node_modules`, Python/tool caches (`__pycache__`, `.pytest_cache`, `.mypy_cache`,
`.ruff_cache`, `.cache`), `target`, `dist`, `build`, `coverage`, `htmlcov`, `vendor`,
`.generated`, `generated`, `output`, `outputs`, `artifacts`, `snapshots`, `cache`,
`tmp` and `temp`. This includes `data/output` and generated QA snapshots without
excluding all of `data/`. `qa-assets/baseline` and `qa-assets/baselines` are pruned
specifically. These are explicit reserved directory conventions, not guesses based
on file content; source intentionally stored under those names is not discovered.
Caches are never deleted or modified.

Only `.cargo/registry` and `.cargo/git` are excluded within `.cargo`:
`.cargo/config.toml` remains visible to the traversal. Source Cargo manifests such
as `apps/desktop/src-tauri/Cargo.toml` remain detected. Tracked and untracked source
configuration are both inspected; discovery is not restricted to `git ls-files`,
so a dirty dry-run can still see newly added source manifests. Gitignored files
outside the explicit excluded trees can be inspected too.

Python package metadata and historical manager files are recognized. Node
lockfiles, declared package manager and TypeScript configuration are reported.
Ambiguous Node lockfiles without a declared manager yield `unknown` and no
inferred commands. Rust, Go, Java and CMake metadata are reported while the
profile remains `generic`. Override the proposal with `PROFILE=...`.

Before discovery, adoption validates the Git root/history and checks
`.template/adoption.json` through the same symlink-safe destination guard.
A valid marker has `template: "python-project-template"` and `adopted: true`;
known optional profile, harness and provenance fields are validated if present.
Older markers may omit these optional fields: the summary prints only known
information and does not rescan to fill gaps. All three commands (`adopt`,
`adopt-dry-run`, `adopt-diff`) then return exit code 0 with status `already adopted`,
without manifest discovery, Make analysis, candidate generation or writes, even
if the current tree is dirty. Invalid, unreadable or unsafe metadata requires
manual review and returns a nonzero status before discovery. Metadata is never
rewritten. Re-adoption and infrastructure updates remain separate, unsupported
workflows. Preview footers are printed once, including when blocked.

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
not implement one. Re-adoption exits early for valid adoption metadata. Resolve
conflicts in unadopted repositories manually and rerun the dry-run on a clean tree. Managed Cruft conversion,
CI replacement and package-manager migration are outside this workflow.

Make integration also recognizes `GNUmakefile` and `makefile` in GNU Make's
precedence order. It preserves existing bytes and the historical default target.
Dynamic target names or includes that cannot be inspected safely require manual
integration and block adoption rather than risking a recipe collision.

## Output validation (TEMPLATE-014)

A representative mixed repository with nested Python, a Node application,
Docker/Compose, CI and an existing Makefile produced these captured stdout sizes:

| Command/mode | Previous | Current |
| --- | ---: | ---: |
| `adopt-dry-run` | 2,929 lines | 46 lines |
| `adopt` | 2,940 lines | 59 lines |
| `adopt-dry-run VERBOSE=1` | — | 91 lines |
| `adopt-dry-run DEBUG=1` | — | 397 lines |
| `adopt-diff` | — | 2,900 lines, explicitly requested |

All preview modes were checked against target file contents and Git state;
regression tests also check modification timestamps. The actual user repository
`~/projects/test_ba` was unavailable in the agent environment, so manual validation
used an equivalent temporary fixture rather than claiming validation of that
external repository. Normal-output size has a generous 200-line regression
limit for the known fixture; blocking conflicts are never subject to that limit.

## Discovery validation (TEMPLATE-015)

A temporary repository equivalent to a Python/Node/Tauri monorepo retained the
real Python manifest, both Node manifests, the Tauri Cargo manifest and GitHub
Actions configuration. Dependency GitLab CI files and generated QA package
snapshots did not enter discovery or the adoption plan. `.cargo/config.toml`
remained visible. Preview commands left target contents and Git status intact.

For a sample of seven traversals (median, excluding Git subprocesses and candidate
rendering), adding 6,001 dependency/generated manifests produced:

| Traversal | Time | Visible files |
| --- | ---: | ---: |
| Current, source fixture only | 0.72 ms | 11 |
| Current, populated caches/outputs | 0.93 ms | 11 |
| Previous, populated caches/outputs | 73.42 ms | 2,012 |

These are diagnostic measurements, not test timing thresholds. The pruning
regression test instruments directory descent and refuses entry into excluded
trees containing 3,000 fake dependency manifests.

The non-adopted fixture's normal dry-run printed 45 lines; after adoption its
preview printed 24 lines with `already adopted`, no plan, no SKIP/BLOCK counts
and one footer. Tests replace discovery, rendering and application functions
with failure sentinels to guarantee the early exit for all three commands and
both current and minimal legacy metadata. Invalid/unreadable metadata and
metadata symlinks remain errors requiring manual review.

The actual `~/projects/pdf-editor` was unavailable in this environment; these
results describe the temporary equivalent, not validation of the external repo.
