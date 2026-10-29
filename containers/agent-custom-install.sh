#!/usr/bin/env bash
set -euo pipefail
# Optional reproducible custom harness installation, executed as agent at build.
# npm's build prefix is /opt/agent-tools; runtime user installs use ~/.local.
# Never embed credentials here.
