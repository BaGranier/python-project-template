# Testing the generator

The master is a generator, so its test levels differ from the application checks
in a rendered project. Application `make check` still runs its configured checks.

| Command | Scope | When |
| --- | --- | --- |
| `make test` | Unmarked logic, rendering, hooks, static security, ports and lightweight Git | During iteration |
| `make check` | Ruff lint/format, mypy and fast tests | Standard development check |
| `make test-integration` | `integration` marker: real application environments, build, docs, Cruft, bootstrap | Finalizing rendering changes |
| `make test-runtime` | `runtime` marker: real engines, containers, networking, credentials, multiple projects | Finalizing container/agent changes on a capable host |
| `make check-full` | Checks, then integration, then runtime | Full validation before release/important merge |
| `make test-profile` | Full pytest run with the slowest 30 durations, minimum 0.5 s | Investigate performance |

The last two suites are invoked sequentially by `check-full`. No xdist is used.
Runtime tests explicitly skip if their engine is unavailable or unusable; they
are not selected at all by `make test`. Never forward a host engine socket into
the sandbox for these tests. An unavailable runtime has not passed validation.

## Layout and fixtures

`tests/test_template.py` now contains lightweight rendering/configuration tests
and the shared helpers. Other `tests/test_*.py` modules contain pure logic, fake
engine dispatch, state, isolated Git, adoption and retention tests.

`tests/integration/` separates generated application workflows, bootstrap/public
CLI workflows and Cruft. `tests/runtime/` contains the actual dev/agent/master
containers and the separate multi-project test. Every module there declares its
marker explicitly. Markers are registered with `--strict-markers`.
`test_suite_layout.py` guards the designated expensive scenarios and module
markers so they cannot quietly return to FAST.

Lightweight `generate()` still uses Cookiecutter and the real validation and
cleanup hooks. During rendering only, it temporarily uses an empty PATH, which
exercises the hook's existing uv-unavailable path. No dependency resolution,
lockfile or application environment is created. Each distinct context is rendered
once into an immutable temporary skeleton. Every caller gets an independent copy;
Git, `.env`, source and state changes cannot contaminate another test. The
read-only `default_project` remains a session fixture. No mutable Git repository
or application environment is shared across tests.

Integration/runtime use `generate_locked()`, which runs the normal hooks with uv
available and fresh, independent output. Public CLI and Cruft tests also run the
real hooks. The default integration smoke explicitly requires `uv.lock`, then
runs setup, locked sync, application checks, package build and docs build. It
also performs the Jupytext CLI round-trip and executes the notebook using the
environment it already synchronized. FAST keeps notebook metadata/syntax checks.
Shell activation tests need only a real Python executable and use a tiny `uv venv`
instead of installing an application's dependency groups.

## Coverage and removed repetition

- Every option row still renders its context, checks conditional files and Make
  help, and parses Python, TOML and YAML. Full application quality is checked by
  the default smoke and representative `both`, `custom`, `none/minimal` workflows.
- All five providers retain Containerfile/Compose, volumes, dispatch, instructions
  and Make target checks. The default smoke covers Codex; `both` covers both
  official harnesses; `custom` covers its distinct tool path; `none/minimal`
  covers agent removal plus disabled docs/notebooks/runtime/CI. `make init`
  already invokes setup, so provider workflows no longer call setup separately.
- All five contexts retain real Cruft create and metadata/provider assertions.
  `both` and `none` retain full check/diff/update cycles. Both legacy
  `enable_agent` migrations and the Codex-to-both volume-preserving migration
  retain real updates and application checks.
- The four runtime profiles (`codex`, `claude`, `both`, `custom`) are unchanged.
  This retains provider-specific absence, volume and security assertions without
  claiming equivalence solely from mocks. Existing image-layer/uv caches remain
  enabled. Multi-project concurrency/isolation remains a separate runtime test.
- Initialization/idempotence and setup-hook workflows stay independent because
  they mutate Git or `.env`. Their repeated setup calls test actual idempotence;
  other redundant syncs were removed. The smoke repeats the setup helper to
  check `.env` preservation without another dependency sync.

The shared uv cache and pytest temporary policy remain unchanged:
`tmp_path_retention_policy = "failed"`, `tmp_path_retention_count = "1"`.
Passing heavy test directories are removed; failures retain their diagnostics.
Immutable render skeletons contain no `.venv` and are removed when pytest exits.

## Profiling and CI

```bash
make test-profile
# Or profile a single level:
uv run pytest -m 'not integration and not runtime' --durations=30 --durations-min=0.5
```

Compare timings on the same machine with the existing uv cache. Network,
filesystem and engine availability affect these measurements; there are no
fragile wall-clock assertions. [The recorded comparison](test-performance.md)
includes counts, all 30 slowest phases and the coverage mapping.

CI runs independent fast (`make check`) and integration jobs. A manually selected
runtime job (`workflow_dispatch`, `runtime=true`) uses whichever real engines the
host runner supports, preserving explicit skips. The workflows do not require
Podman on unsupported runners and do not mount an engine socket into an agent.
