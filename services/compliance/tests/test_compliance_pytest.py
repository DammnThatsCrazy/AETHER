"""
Pytest wrapper for the Aether compliance test suite.

Runs the ComplianceTestRunner and asserts every check passes,
making the 22 compliance checks discoverable by pytest and CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the compliance module root is on sys.path
_compliance_root = str(Path(__file__).resolve().parent.parent)
if _compliance_root not in sys.path:
    sys.path.insert(0, _compliance_root)

from tests.compliance_tests import ComplianceTestRunner


def test_all_compliance_checks_pass():
    """Run all 22 compliance checks and assert each one passes."""
    runner = ComplianceTestRunner()
    results = runner.run_all()

    failures = [r for r in results if not r.passed]
    assert len(failures) == 0, (
        f"{len(failures)} compliance check(s) failed:\n"
        + "\n".join(f"  [{r.group}] {r.name}: {r.detail}" for r in failures)
    )
    assert len(results) == 22, f"Expected 22 checks, got {len(results)}"
