#!/usr/bin/env bash
set -euo pipefail

# Reproducible, non-root build hook. No harness is installed by default.
# Build-time npm prefix: /opt/agent-tools (on PATH and not masked by a volume).
# Example: npm install -g your-harness-package@an-exact-version
# For standalone executables, install into /opt/agent-tools/bin.
# Never embed credentials or copy host configuration into the image.
