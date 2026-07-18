"""Path setup for the Agent Layer test suite.

Agent Layer packages (config, models, workers, agent_controller, guardrails) are
top-level modules resolved relative to the Agent Layer directory. Ensure that
directory is importable when the suite runs from anywhere.
"""

from __future__ import annotations

import os
import sys

_AGENT_LAYER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_LAYER_DIR not in sys.path:
    sys.path.insert(0, _AGENT_LAYER_DIR)

os.environ.setdefault("AETHER_ENV", "local")
