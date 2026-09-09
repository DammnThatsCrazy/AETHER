#!/usr/bin/env python3
"""Index changed-path impact and optionally compare a legacy broad scope."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.impact_graph import (  # noqa: E402
    ImpactGraphConfigError,
    build_impact_index,
    compare_shadow_scopes,
    load_impact_graph,
)
from scripts.lib.telemetry import TelemetryContractError, load_registry  # noqa: E402
from scripts.lib.verification_router import LANE_ORDER, load_router_registry  # noqa: E402


def changed_files(base: str | None, explicit: list[str]) -> list[str]:
    if explicit:
        return sorted(set(explicit))
    proc = subprocess.run(
        ["git", "diff", "--name-only", base or "HEAD", "--"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "cannot discover changed files")
    return sorted(line for line in proc.stdout.splitlines() if line)


def _scope_file(path: Path) -> tuple[str, ...]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        values = raw
    elif isinstance(raw, dict):
        values = raw.get("transitive_nodes", raw.get("nodes"))
    else:
        values = None
    if not isinstance(values, list) or not all(
        isinstance(value, str) and value for value in values
    ):
        raise ValueError(f"{path} must contain a node list or an impact index")
    return tuple(sorted(set(values)))


def _event_id(event_name: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"event_name": event_name, "data": payload}, sort_keys=True, separators=(",", ":")
    )
    return "tel_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _write_telemetry(
    output: Path,
    *,
    index: dict[str, Any],
    shadow: dict[str, Any] | None,
    occurred_at: str | None,
) -> None:
    registry = load_registry()
    route = index["router"]
    route_data = {
        "changed_files": index["changed_files"],
        "affected_domains": route["affected_domains"],
        "minimum_lane": route["minimum_lane"],
        "selected_lane": route["selected_lane"],
        "followup_required": route["followup_required"],
        "selected_checks": route["selected_checks"],
        "affected_tests": route["selected_test_suites"],
        "global_change": route["global_change"],
    }
    graph_data = {
        "changed_files": index["changed_files"],
        "direct_nodes": index["direct_nodes"],
        "impacted_components": index["impacted_components"],
        "impacted_contracts": index["impacted_contracts"],
        "impacted_deployables": index["impacted_deployables"],
        "transitive_nodes": index["transitive_nodes"],
        "unresolved_paths": index["unresolved_paths"],
        "router_minimum_lane": route["minimum_lane"],
        "router_selected_lane": route["selected_lane"],
        "router_followup_required": route["followup_required"],
    }
    events = [
        registry.build_event(
            "verification.route.evaluated",
            route_data,
            event_id_value=_event_id("verification.route.evaluated", route_data),
            occurred_at=occurred_at,
        ),
        registry.build_event(
            "impact.graph.indexed",
            graph_data,
            event_id_value=_event_id("impact.graph.indexed", graph_data),
            occurred_at=occurred_at,
        ),
    ]
    if shadow is not None:
        events.append(
            registry.build_event(
                "verification.shadow.comparison",
                shadow,
                event_id_value=_event_id("verification.shadow.comparison", shadow),
                occurred_at=occurred_at,
            )
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="git revision used for changed-path discovery")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--lane", choices=LANE_ORDER)
    parser.add_argument("--legacy-file", type=Path, help="JSON node list or prior impact index")
    parser.add_argument(
        "--targeted-file", type=Path, help="JSON node list for the targeted shadow scope"
    )
    parser.add_argument(
        "--telemetry-output", type=Path, help="write validated local telemetry envelopes"
    )
    parser.add_argument("--occurred-at", help="ISO-8601 timestamp for telemetry envelopes")
    parser.add_argument(
        "--strict-shadow",
        action="store_true",
        help="fail when the targeted scope misses graph truth",
    )
    parser.add_argument(
        "--fail-on-unresolved",
        action="store_true",
        help="fail when any changed path is outside the registered impact graph",
    )
    args = parser.parse_args()
    try:
        paths = changed_files(args.base, args.changed_file)
        router = load_router_registry(ROOT / "config" / "verification_router.yaml")
        graph = load_impact_graph(router=router)
        index = build_impact_index(paths, graph, requested_lane=args.lane, router=router)
        shadow: dict[str, Any] | None = None
        if args.legacy_file:
            legacy = _scope_file(args.legacy_file)
            targeted = (
                _scope_file(args.targeted_file)
                if args.targeted_file
                else tuple(index["transitive_nodes"])
            )
            comparison = compare_shadow_scopes(
                expected_nodes=index["transitive_nodes"],
                targeted_nodes=targeted,
                legacy_nodes=legacy,
            )
            shadow = comparison.as_dict()
            index["shadow_comparison"] = shadow
        if args.telemetry_output:
            _write_telemetry(
                args.telemetry_output, index=index, shadow=shadow, occurred_at=args.occurred_at
            )
        print(json.dumps(index, indent=2) + "\n", end="")
        if args.fail_on_unresolved and index["unresolved_paths"]:
            return 1
        if args.strict_shadow and shadow and shadow["classification"].startswith("targeted_miss"):
            return 1
        return 0
    except (
        ImpactGraphConfigError,
        TelemetryContractError,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(json.dumps({"schema_version": 1, "status": "BLOCKED", "reason": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
