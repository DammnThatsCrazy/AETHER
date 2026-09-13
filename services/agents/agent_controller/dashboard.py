"""
Aether Agent Layer — CLI Dashboard & Internal UI
Terminal-first ASCII dashboard with three required views:

1. Feed / Timeline — objective events, checkpoints, briefs, review outcomes, alerts
2. Kanban / Objective Board — open, blocked, awaiting review, sleeping, failed, completed
3. Controller Health Console — controller status, team saturation, queue depth, catalysts

Supports:
- Optional Atom rendering (when Atoms enabled)
- Pure work mode (when Atoms disabled)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ======================================================================
# ASCII rendering helpers
# ======================================================================

def _box(title: str, lines: list[str], width: int = 72) -> str:
    """Render an ASCII box with title and content lines."""
    border = "+" + "-" * (width - 2) + "+"
    title_line = f"| {title:<{width - 4}} |"
    separator = "|" + "-" * (width - 2) + "|"
    body = []
    for line in lines:
        truncated = line[: width - 4]
        body.append(f"| {truncated:<{width - 4}} |")
    return "\n".join([border, title_line, separator] + body + [border])


def _status_icon(status: str) -> str:
    icons = {
        "active": "[+]",
        "idle": "[~]",
        "sleeping": "[z]",
        "blocked": "[!]",
        "halted": "[X]",
        "failed": "[F]",
        "completed": "[*]",
        "awaiting_review": "[?]",
        "recovering": "[R]",
        "pending": "[ ]",
    }
    return icons.get(status, "[.]")


# ======================================================================
# View 1: Feed / Timeline
# ======================================================================

def render_timeline(events: list[dict[str, Any]], limit: int = 20) -> str:
    """Render the feed/timeline view."""
    lines = []
    for event in events[:limit]:
        ts = event.get("timestamp", "")
        if isinstance(ts, str) and len(ts) > 19:
            ts = ts[:19]
        etype = event.get("type", "unknown")
        source = event.get("source", "")
        obj_id = event.get("objective_id", "")[:8]
        lines.append(f"  {ts}  {etype:<30} src={source:<10} obj={obj_id}...")
    if not lines:
        lines = ["  (no events)"]
    return _box("FEED / TIMELINE", lines)


# ======================================================================
# View 2: Kanban / Objective Board
# ======================================================================

def render_kanban(objectives: list[dict[str, Any]], atoms_enabled: bool = False) -> str:
    """Render the kanban/objective board view."""
    columns = {
        "OPEN": [],
        "BLOCKED": [],
        "REVIEW": [],
        "SLEEPING": [],
        "FAILED": [],
        "DONE": [],
    }
    status_map = {
        "pending": "OPEN",
        "planning": "OPEN",
        "active": "OPEN",
        "blocked": "BLOCKED",
        "awaiting_review": "REVIEW",
        "sleeping": "SLEEPING",
        "failed": "FAILED",
        "recovering": "FAILED",
        "completed": "DONE",
        "cancelled": "DONE",
    }
    for obj in objectives:
        col = status_map.get(obj.get("status", ""), "OPEN")
        obj_id = obj.get("objective_id", "")[:8]
        severity = obj.get("severity", "")
        goal = obj.get("goal", "")[:30]
        icon = _status_icon(obj.get("status", ""))
        entry = f"{icon} {obj_id}.. {severity:<8} {goal}"
        columns[col].append(entry)

    lines = []
    for col_name, entries in columns.items():
        lines.append(f"  --- {col_name} ({len(entries)}) ---")
        if entries:
            for e in entries[:10]:
                lines.append(f"    {e}")
        else:
            lines.append("    (empty)")
        lines.append("")
    return _box("KANBAN / OBJECTIVE BOARD", lines)


# ======================================================================
# View 3: Controller Health Console
# ======================================================================

def render_controller_health(health: dict[str, Any], atoms_enabled: bool = False) -> str:
    """Render the controller health console view."""
    lines = []
    for name, data in health.items():
        if not isinstance(data, dict):
            continue
        status = data.get("status", "unknown")
        icon = _status_icon(status)
        controller = data.get("controller", name)

        # Build detail string
        details = []
        for key in ["active_objectives", "total_evidence", "total_facts",
                     "total_verifications", "pending_mutations", "open_batches",
                     "active_catalysts", "total_checkpoints", "total_briefs",
                     "known_goals", "recoveries_performed"]:
            if key in data:
                short_key = key.replace("total_", "").replace("active_", "")
                details.append(f"{short_key}={data[key]}")

        detail_str = " | ".join(details[:4]) if details else ""
        lines.append(f"  {icon} {controller:<14} {detail_str}")

    # Cycle state
    cycle_data = health.get("cycle", {})
    if cycle_data:
        cycle_status = "stopped" if cycle_data.get("is_stopped") else "running"
        budget = cycle_data.get("budget_spent", 0)
        budget_limit = cycle_data.get("budget_limit", 0)
        actions = cycle_data.get("actions_taken", 0)
        lines.append("")
        lines.append(f"  CYCLE: {cycle_status} | actions={actions} | budget=${budget:.2f}/${budget_limit:.2f}")

    # Atoms
    atoms = health.get("atoms", {})
    if atoms.get("enabled"):
        lines.append(f"  ATOMS: enabled ({atoms.get('count', 0)} registered)")
    else:
        lines.append("  ATOMS: disabled (pure work mode)")

    return _box("CONTROLLER HEALTH CONSOLE", lines)


# ======================================================================
# Full dashboard render
# ======================================================================

def render_dashboard(
    events: list[dict[str, Any]],
    objectives: list[dict[str, Any]],
    health: dict[str, Any],
    atoms_enabled: bool = False,
) -> str:
    """Render the full three-panel ASCII dashboard."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = _box("Aether AGENT LAYER — INTERNAL OPS DASHBOARD", [
        f"  Timestamp: {now}",
        f"  Mode: {'Atoms enabled' if atoms_enabled else 'Pure work mode'}",
    ])

    timeline = render_timeline(events)
    kanban = render_kanban(objectives, atoms_enabled)
    console = render_controller_health(health, atoms_enabled)

    return "\n\n".join([header, timeline, kanban, console])
