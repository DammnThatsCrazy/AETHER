"""Performance-suite fixtures and markers.

Registers the ``performance`` marker so these measured-threshold tests can be
selected/deselected explicitly (``-m performance`` / ``-m 'not performance'``)
without an ``unknown marker`` warning.  The suite is intentionally kept fast
enough to run in the default gate: every module bounds its iteration count so a
full run completes in well under a second on the CI baseline.
"""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "performance: measured-threshold performance guardrail (fast, CI-safe).",
    )
