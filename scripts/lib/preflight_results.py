"""Result model + reporting for the staging preflight gate.

Mirrors the CheckResult/report style of scripts/repo_doctor.py and
scripts/ops_readiness.py: one record per check with a deterministic name,
an explicit PASS/FAIL/SKIP status, a human-readable detail, and an exact
remediation command or instruction for failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"
_VALID_STATUSES = (PASS, FAIL, SKIP)


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str = ""
    remediation: str = ""

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r} for check {self.name!r} "
                f"(expected one of {_VALID_STATUSES})"
            )

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "remediation": self.remediation,
        }


def passed(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name=name, status=PASS, detail=detail)


def failed(name: str, detail: str = "", remediation: str = "") -> CheckResult:
    return CheckResult(name=name, status=FAIL, detail=detail, remediation=remediation)


def skipped(name: str, detail: str = "") -> CheckResult:
    return CheckResult(name=name, status=SKIP, detail=detail)


def all_passed(results: Iterable[CheckResult]) -> bool:
    """True when no check FAILed (SKIPs never fail the gate)."""
    return not any(r.failed for r in results)


def count_by_status(results: Sequence[CheckResult]) -> dict[str, int]:
    counts = {PASS: 0, FAIL: 0, SKIP: 0}
    for r in results:
        counts[r.status] += 1
    return counts


def render_results(results: Sequence[CheckResult], *, indent: str = "  ") -> list[str]:
    """Deterministic per-check report lines (name, status, detail, remediation)."""
    if not results:
        return []
    width = max(len(r.name) for r in results) + 2
    lines: list[str] = []
    for r in results:
        suffix = f" {r.detail}" if r.detail else ""
        lines.append(f"{indent}[{r.status}] {r.name:<{width}}{suffix}")
        if r.failed and r.remediation:
            lines.append(f"{indent}       Required fix: {r.remediation}")
    return lines
