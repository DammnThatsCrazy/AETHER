"""
Aether Agent Layer — CLI Interface
Command-line interface for internal operator interactions.
CLI-first operational surface for the agent layer.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from agent_controller.hub import ControllerHub
from agent_controller.dashboard import render_dashboard
from services.agent.internal_ops import InternalOpsService


def create_hub() -> ControllerHub:
    """Create a default controller hub for CLI use."""
    return ControllerHub()


def cmd_dashboard(hub: ControllerHub, args: argparse.Namespace) -> None:
    """Render the full dashboard."""
    ops = InternalOpsService(hub)
    events = ops.recent_timeline(20)
    objectives = ops.list_objectives()
    health = hub.controller_health()
    print(render_dashboard(events, objectives, health, hub.unit_registry.enabled))


def cmd_health(hub: ControllerHub, args: argparse.Namespace) -> None:
    """Show controller health."""
    health = hub.controller_health()
    print(json.dumps(health, indent=2, default=str))


def cmd_objectives(hub: ControllerHub, args: argparse.Namespace) -> None:
    """List objectives."""
    ops = InternalOpsService(hub)
    objectives = ops.list_objectives(status=args.status if hasattr(args, "status") else None)
    for obj in objectives:
        print(
            f"  {obj['objective_id'][:8]}.. "
            f"{obj['status']:<16} {obj['severity']:<8} {obj['goal']}"
        )
    if not objectives:
        print("  (no objectives)")


def cmd_review(hub: ControllerHub, args: argparse.Namespace) -> None:
    """List pending reviews."""
    ops = InternalOpsService(hub)
    pending = ops.review_pending()
    for batch in pending:
        print(
            f"  Batch {batch['batch_id'][:8]}.. "
            f"severity={batch['severity']} "
            f"mutations={batch['mutations']} "
            f"status={batch['status']}"
        )
    if not pending:
        print("  (no pending reviews)")


def cmd_timeline(hub: ControllerHub, args: argparse.Namespace) -> None:
    """Show recent timeline."""
    ops = InternalOpsService(hub)
    events = ops.recent_timeline(args.limit if hasattr(args, "limit") else 20)
    for event in events:
        print(
            f"  {event['timestamp'][:19]}  "
            f"{event['type']:<30} {event.get('source', '')}"
        )
    if not events:
        print("  (no events)")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aether-agent",
        description="Aether Agent Layer — Internal Operations CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("dashboard", help="Render full ASCII dashboard")
    subparsers.add_parser("health", help="Show controller health")

    obj_parser = subparsers.add_parser("objectives", help="List objectives")
    obj_parser.add_argument("--status", type=str, default=None)

    subparsers.add_parser("review", help="Show pending review batches")

    timeline_parser = subparsers.add_parser("timeline", help="Show recent timeline")
    timeline_parser.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    hub = create_hub()

    commands = {
        "dashboard": cmd_dashboard,
        "health": cmd_health,
        "objectives": cmd_objectives,
        "review": cmd_review,
        "timeline": cmd_timeline,
    }

    if args.command in commands:
        commands[args.command](hub, args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
