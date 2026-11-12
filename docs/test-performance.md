# TEMPLATE-013 performance and coverage record

Measured on 2026-11-12 in the same Linux agent sandbox using Python 3.12.15,
uv and the existing shared uv cache. Docker and Podman were unavailable.
There was no cache purge and no parallel pytest execution. These are individual
runs, not controlled statistical benchmarks: network and filesystem/cache
warming can affect the exact times. Command/workflow reductions below provide
an independent explanation of the improvement.

## Measurements

Before any repository edit, the complete original suite ran with:

```bash
uv run pytest --durations=30 --durations-min=0.5
```

For both before and after full-suite profiling, a temporary external pytest
plugin (`-p profile_metrics`) counted in-process Cookiecutter calls and test
subprocess argv requests. It did not change application/template files or test
selection. Its count does not observe subprocesses spawned inside Make/Cruft or
containers. The duration tables are pytest's measured phases. The Make timings
include the complete Make command, measured with a monotonic clock.

| Measurement | Seconds | Result |
| --- | ---: | --- |
| Before: old `make test` scope / full pytest | 541.99 | 209 passed, 7 skipped; 216 collected |
| After: `make test` | 43.93 | 197 passed, 25 deselected |
| After: `make check` | 41.58 | lint, format, mypy and FAST passed |
| After: `make test-integration` | 112.85 | 18 passed, 204 deselected |
| After: `make test-runtime` | 1.07 | 7 skipped, 215 deselected; engine unavailable |
| After: `make check-full` | 152.16 | 215 passed across FAST/integration; 7 runtime skips |
| After: full pytest profile | 149.59 | 215 passed, 7 skipped; 222 collected |

The normal development test command changed from **541.99 s to 43.93 s**
(12.3 times faster, 91.9% less elapsed time).
The ideal FAST target of 30 s was not reached on this machine; `make check`
fits the desired sub-minute development loop. The complete suite was also
measured after the changes, independently of selecting the smaller FAST scope.
The complete pytest profile fell from **541.99 s to 149.59 s**
(3.6 times faster, 72.4% less elapsed time).
No runtime execution/build success is claimed.

## Workload counts

The directly observed subprocess requests below include intentional no-op Make
commands in the eight new non-Python project cases and adopted generic projects.
They are not all Python builds or dependency installations.

| Observed test request | Before | After |
| --- | ---: | ---: |
| in-process Cookiecutter generation | 70 | 40 |
| cruft create | 8 | 8 |
| direct uv sync | 3 | 1 |
| make setup | 16 | 10 |
| make init | 11 | 9 |
| direct uv build | 1 | 1 |
| make build | 14 | 12 |
| make docs-build | 21 | 11 |
| make check | 25 | 23 |

Cookiecutter counts include eight expected invalid-input attempts. Actual
persistent render requests, excluding Cruft's internal temporary regenerations,
are in-process attempts minus eight, plus eight real Cruft creates and one
successful public CLI demo render: **71 → 41**. Copies of immutable render output
are independent test workspaces and do not trigger another Cookiecutter render.
The second public demo generation still tests refusing an existing project.

Auditing the unchanged Make recipes and successful workflows separates real
application work from no-ops:

| Application work | Before | After |
| --- | ---: | ---: |
| Explicit `uv sync`, including setup/init recipes | 20 | 10 |
| Python package builds, including the custom package name | 7 | 5 |
| Actual MkDocs builds | 13 | 3 |
| Fresh dependency-installed project environments | 22 | 11 |
| Additional tiny dependency-free shell environments | 0 | 2 |
| Observed container builds | 0 | 0 |
| Agent runtime provider cases retained for capable hosts | 4 | 4 |

The sync count excludes implicit synchronization by `uv run`. The environment
count is a source/workflow audit, not filesystem tracing: the nine option-matrix
environments and two redundant provider environments disappeared. Runtime
workloads could not be measured with the engine intentionally unavailable.

## Coverage equivalence

All **216** original collected scenario identifiers remain after
normalizing their moved file paths. The new collection has **222**
scenarios, adding:

- `test_expensive_tests_have_explicit_markers`
- `test_provider_workflow[both-options0]`
- `test_provider_workflow[custom-options1]`
- `test_provider_workflow[none-options2]`
- `test_render_cache_returns_independent_projects`
- `test_structural_render_does_not_create_environment`.

A stable identifier alone is not proof of behavioral equivalence; the actual
redistribution is:

- All option/provider contexts still render and inspect conditional files,
  Make help, Python syntax, TOML and YAML. Repeated Ruff/mypy/docs runs moved to
  default, both, custom and none/minimal integration workflows.
- The independent default smoke retains setup, locked sync, application checks,
  wheel/sdist inspection, docs, CLI import, clean preservation and `.env`
  preservation. Notebook CLI conversion/sync/execution moved into this same
  synchronized environment; notebook metadata/syntax remains in FAST.
- All five Cruft creates and provider metadata assertions remain. Full update
  cycles run for both/none; both legacy migrations and the Codex-to-both volume
  migration retain real updates, state and application checks.
- All four real agent-container provider cases, the dev container, master
  container and multi-project lifecycle remain unchanged apart from module
  placement/markers and calling the normal locked renderer.
- FAST retains lightweight Git refusal/recovery, provider dispatch, ports,
  credential/static isolation, shell behavior, config, hooks and retention.
  Render-cache isolation and explicit marker guards were added.

No pytest-xdist or strict wall-clock assertions were introduced.

## Disk impact and fixture isolation

The pytest failed-only retention policy and count of one are unchanged. The
baseline passed session removed its temporary session directory; no project
`.venv` remained under the pytest temporary root. The successful after run also
removes its temporary session directory. Thus retained dependency environments
after successful runs remain **0 → 0**. Two diagnostic directories from failed/
interrupted implementation checks remain intentionally retained; neither has
an application `.venv`. No peak-disk byte measurement was taken;
this report does not infer one from duration.

The workflow audit reduces dependency-installed environments **22 → 11**; two
shell tests use tiny `uv venv` environments without application dependencies.
The immutable render cache contains no `.venv`, Git or agent state and is cleaned
at process exit. Tests that change Git, `.env`, dependencies or Cruft state own
independent directories. The real default workflow owns a separate directory
from the read-only session rendering fixture, so config scans do not traverse
its installed dependencies. Shared uv/image-layer caches remain enabled.

## Before: 30 slowest measured phases

```text
79.00s call     tests/test_template.py::test_selected_provider_project[codex]
49.99s call     tests/test_template.py::test_cruft_create_check_diff[codex]
40.34s call     tests/test_template.py::test_cruft_create_check_diff[claude]
37.00s call     tests/test_template.py::test_cruft_create_check_diff[custom]
35.96s call     tests/test_template.py::test_cruft_create_check_diff[both]
35.04s call     tests/test_template.py::test_cruft_create_check_diff[none]
18.16s call     tests/test_template.py::test_init_and_idempotence
11.61s call     tests/test_agent_profiles.py::test_cruft_codex_to_both_preserves_volume_name
10.56s call     tests/test_template.py::test_selected_provider_project[both]
10.38s call     tests/test_template.py::test_selected_provider_project[custom]
10.26s call     tests/test_template.py::test_selected_provider_project[claude]
9.89s call     tests/test_template.py::test_selected_provider_project[none]
9.13s call     tests/test_template.py::test_cruft_legacy_context_upgrade[no-none]
9.03s call     tests/test_template.py::test_cruft_legacy_context_upgrade[yes-codex]
8.06s call     tests/test_template.py::test_setup_installs_git_hook
7.17s call     tests/test_template.py::test_default_execution
6.46s call     tests/test_template.py::test_agent_start_ports_state_and_status[address already in use]
6.36s call     tests/test_template.py::test_option_matrix[options1]
6.33s call     tests/test_template.py::test_option_matrix[options6]
6.22s call     tests/test_template.py::test_option_matrix[options7]
6.18s call     tests/test_template.py::test_option_matrix[options0]
6.12s call     tests/test_template.py::test_option_matrix[options3]
6.12s call     tests/test_template.py::test_option_matrix[options2]
6.02s call     tests/test_template.py::test_agent_start_ports_state_and_status[network permission denied]
5.70s call     tests/test_template.py::test_yaml_configuration
5.65s call     tests/test_template.py::test_init_missing_identity_and_resume
5.58s call     tests/test_template.py::test_init_inside_parent_repository
5.50s call     tests/test_template.py::test_option_matrix[options4]
4.61s call     tests/test_template.py::test_jupytext
4.37s call     tests/test_template.py::test_option_matrix[options5]
```

## After: 30 slowest measured phases

```text
16.11s call     tests/integration/test_generated_project.py::test_default_execution
10.33s call     tests/integration/test_cruft.py::test_cruft_codex_to_both_preserves_volume_name
9.81s call     tests/integration/test_cruft.py::test_cruft_legacy_context_upgrade[no-none]
9.71s call     tests/integration/test_generated_project.py::test_provider_workflow[custom-options1]
8.97s call     tests/integration/test_cruft.py::test_cruft_legacy_context_upgrade[yes-codex]
8.92s call     tests/integration/test_generated_project.py::test_provider_workflow[both-options0]
6.37s call     tests/integration/test_generated_project.py::test_provider_workflow[none-options2]
5.97s call     tests/integration/test_git_workflows.py::test_init_and_idempotence
5.05s call     tests/integration/test_git_workflows.py::test_setup_installs_git_hook
5.01s call     tests/integration/test_git_workflows.py::test_init_inside_parent_repository
4.89s call     tests/integration/test_git_workflows.py::test_init_missing_identity_and_resume
3.26s call     tests/integration/test_cruft.py::test_cruft_create_check_diff[both]
3.23s call     tests/integration/test_cruft.py::test_cruft_create_check_diff[none]
1.90s call     tests/integration/test_git_workflows.py::test_demo_generation_and_explicit_cleanup
1.58s call     tests/test_disk_usage.py::test_real_pytest_retention_all_phases
1.53s call     tests/integration/test_cruft.py::test_cruft_create_check_diff[codex]
1.12s call     tests/integration/test_cruft.py::test_cruft_create_check_diff[claude]
1.07s call     tests/test_adoption.py::test_profiles_preserve_history_and_application[python-manifests0]
1.04s call     tests/integration/test_cruft.py::test_cruft_create_check_diff[custom]
1.04s call     tests/test_adoption.py::test_profiles_preserve_history_and_application[node-manifests1]
1.02s call     tests/test_adoption.py::test_profiles_preserve_history_and_application[mixed-manifests2]
0.99s call     tests/test_adoption.py::test_profiles_preserve_history_and_application[generic-manifests3]
0.96s call     tests/test_adoption.py::test_new_nonpython_projects[both-node]
0.92s call     tests/test_adoption.py::test_new_nonpython_projects[both-mixed]
0.91s call     tests/test_adoption.py::test_new_nonpython_projects[both-generic]
0.90s call     tests/test_adoption.py::test_new_nonpython_projects[both-auto]
0.89s call     tests/test_adoption.py::test_new_nonpython_projects[none-node]
0.89s call     tests/test_adoption.py::test_new_nonpython_projects[none-auto]
0.88s call     tests/test_adoption.py::test_new_nonpython_projects[none-mixed]
0.86s call     tests/test_adoption.py::test_new_nonpython_projects[none-generic]
```

See [testing.md](testing.md) for the commands, suite boundaries, CI jobs and
profiling instructions. Runtime skipped because Docker/Podman were unavailable;
validate real engine behavior on a capable host without exposing a socket to an
agent container.
