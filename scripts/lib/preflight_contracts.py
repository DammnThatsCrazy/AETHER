"""Contract / version-consistency checks for the staging preflight gate.

Runs the repo's contract gates as subprocesses:

- ``contracts:sdk-contracts``       python scripts/validate_sdk_contracts.py
- ``contracts:version-consistency`` python scripts/check_version_consistency.py
- ``contracts:version-alignment``   python scripts/bump_version.py --check

The first two scripts are built by a parallel release-train wave. A live
preflight fails closed when either is missing ("script missing"); in
``--dry-run`` a missing script SKIPs with a warning so wave ordering cannot
deadlock the gate self-test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .preflight_results import CheckResult, failed, passed, skipped

ROOT = Path(__file__).resolve().parents[2]

# (relative script path, check name) — order is the report order.
PARALLEL_WAVE_SCRIPTS = (
    ("scripts/validate_sdk_contracts.py", "contracts:sdk-contracts"),
    ("scripts/check_version_consistency.py", "contracts:version-consistency"),
)

VERSION_ALIGNMENT_CMD = ("scripts/bump_version.py", "--check")


def _tail(text: str) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def _run_script(name: str, argv: list[str], root: Path, remediation: str) -> CheckResult:
    command = " ".join(argv)
    try:
        proc = subprocess.run(
            [sys.executable, *argv],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return failed(name, f"'{command}' timed out", remediation)
    except OSError as exc:
        return failed(name, f"'{command}' could not start: {exc}", remediation)
    if proc.returncode == 0:
        return passed(name, f"{command} exited 0")
    detail = _tail(proc.stderr) or _tail(proc.stdout) or f"exit {proc.returncode}"
    return failed(name, f"{command} exited {proc.returncode}: {detail}", remediation)


def run_contract_checks(*, dry_run: bool = False, root: Path = ROOT) -> list[CheckResult]:
    results: list[CheckResult] = []

    for rel_path, name in PARALLEL_WAVE_SCRIPTS:
        script = root / rel_path
        if not script.exists():
            if dry_run:
                results.append(skipped(
                    name,
                    f"WARNING: {rel_path} not present yet (built in a parallel "
                    "wave) — missing scripts SKIP in dry-run only; a live "
                    "preflight FAILS without them",
                ))
            else:
                results.append(failed(
                    name,
                    f"script missing: {rel_path}",
                    f"restore {rel_path} — the live preflight gate fails closed "
                    "when a contract gate is absent",
                ))
            continue
        results.append(_run_script(
            name,
            [rel_path],
            root,
            remediation=f"run 'python {rel_path}' locally and fix the reported drift",
        ))

    bump_version = root / VERSION_ALIGNMENT_CMD[0]
    if bump_version.exists():
        results.append(_run_script(
            "contracts:version-alignment",
            list(VERSION_ALIGNMENT_CMD),
            root,
            remediation="python scripts/bump_version.py <canonical-version>",
        ))
    else:
        results.append(failed(
            "contracts:version-alignment",
            f"script missing: {VERSION_ALIGNMENT_CMD[0]}",
            "restore scripts/bump_version.py (canonical version tooling)",
        ))

    return results
