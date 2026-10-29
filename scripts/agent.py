"""Master sandbox entrypoint; the lifecycle source is shared with generated projects."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from master_agent import runtime_source


def profile() -> str:
    value = "both"
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, candidate = line.partition("=")
            if sep and key.strip() == "AGENT_PROFILE":
                value = candidate.strip()
    return os.environ.get("AGENT_PROFILE", value)


# Execute only trusted template text from this checkout, never from .agent/workspace.
# __file__ stays here, so ROOT and all host-side safety checks address the master.
try:
    source = runtime_source(profile())
except ValueError as exc:
    sys.exit(f"Template agent: {exc}")
exec(compile(source, __file__, "exec"), globals())
