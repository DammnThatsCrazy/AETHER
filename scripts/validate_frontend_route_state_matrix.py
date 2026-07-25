#!/usr/bin/env python3
"""Validate the evidence-backed Aether and Kyber route-state matrix."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "audits" / "FRONTEND-ROUTE-STATE-MATRIX.md"
ROUTERS = {
    "aether": ROOT / "frontend" / "aether" / "src" / "app" / "router.tsx",
    "kyber": ROOT / "frontend" / "kyber" / "src" / "app" / "router.tsx",
}
NON_DATA_ROUTES = {
    "aether": {"/", "/callback", "/login", "/signup", "/legal/data-retention", "*"},
    "kyber": {"/", "/callback", "*"},
}
ROUTE_RE = re.compile(r'<Route\s+path="([^"]+)"')
BACKTICK_ROUTE_RE = re.compile(r"`([^`]+)`")
VALID_STATES = {"A", "I", "—", "n/a"}


def _router_routes(application: str) -> set[str]:
    text = ROUTERS[application].read_text(encoding="utf-8")
    return {
        route
        for route in ROUTE_RE.findall(text)
        if route not in NON_DATA_ROUTES[application]
    }


def _matrix_rows() -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    application: str | None = None
    for line_number, line in enumerate(
        MATRIX.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line == "## Aether":
            application = "aether"
            continue
        if line == "## Kyber":
            application = "kyber"
            continue
        if application is None or not line.startswith("| `"):
            continue

        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 9:
            errors.append(
                f"line {line_number}: expected 9 matrix columns, found {len(cells)}"
            )
            continue
        routes = BACKTICK_ROUTE_RE.findall(cells[0])
        if not routes:
            errors.append(f"line {line_number}: route cell contains no routes")
            continue
        critical = cells[2]
        if critical not in {"yes", "no"}:
            errors.append(f"line {line_number}: Critical must be yes or no")
        states = dict(zip(("loading", "empty", "error", "populated", "permission"), cells[3:8]))
        for label, state in states.items():
            if state not in VALID_STATES:
                errors.append(
                    f"line {line_number}: invalid {label} state {state!r}"
                )
        if "A" in states.values() and (
            not cells[8] or cells[8] in {"gap", "route-state gap"}
        ):
            errors.append(
                f"line {line_number}: automated coverage requires named test evidence"
            )
        rows.append(
            {
                "application": application,
                "routes": routes,
                "critical": critical == "yes",
                "states": states,
                "evidence": cells[8],
                "line": line_number,
            }
        )
    return rows, errors


def build_report() -> dict[str, Any]:
    rows, errors = _matrix_rows()
    route_states: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        for route in row["routes"]:
            key = (row["application"], route)
            if key in route_states:
                errors.append(
                    f"line {row['line']}: duplicate matrix route {row['application']} {route}"
                )
            route_states[key] = row

    route_counts: dict[str, int] = {}
    for application in ROUTERS:
        expected = _router_routes(application)
        actual = {
            route
            for app, route in route_states
            if app == application
        }
        for route in sorted(expected - actual):
            errors.append(f"{application}: route missing from matrix: {route}")
        for route in sorted(actual - expected):
            errors.append(f"{application}: stale matrix route: {route}")
        route_counts[application] = len(expected)

    total = sum(route_counts.values())
    metrics = {
        state: sum(
            1 for row in route_states.values() if row["states"][state] == "A"
        )
        for state in ("loading", "empty", "error", "populated", "permission")
    }
    critical = [row for row in route_states.values() if row["critical"]]
    critical_complete = sum(
        1
        for row in critical
        if row["states"]["empty"] == "A" and row["states"]["error"] == "A"
    )
    return {
        "route_counts": route_counts,
        "total_data_bearing_routes": total,
        "metrics": metrics,
        "empty_coverage": metrics["empty"] / total if total else 0.0,
        "critical_routes": len(critical),
        "critical_empty_and_error": critical_complete,
        "inventory_errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    report = build_report()
    failures = list(report["inventory_errors"])
    if args.enforce:
        if report["empty_coverage"] < 0.90:
            failures.append(
                "empty-state coverage is below 90% "
                f"({report['metrics']['empty']}/{report['total_data_bearing_routes']})"
            )
        if report["critical_empty_and_error"] != report["critical_routes"]:
            failures.append(
                "critical empty/error coverage is incomplete "
                f"({report['critical_empty_and_error']}/{report['critical_routes']})"
            )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"frontend-route-state: {failure}", file=sys.stderr)
    else:
        print(
            "frontend-route-state: pass "
            f"({report['metrics']['empty']}/{report['total_data_bearing_routes']} empty, "
            f"{report['critical_empty_and_error']}/{report['critical_routes']} critical)"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
