"""
Aether Agent Layer — UNITS Identity & Mascot Layer
Fully real but fully optional identity + mascot presentation layer.

UNITS applies by default to controllers and teams.
UNITS may optionally apply to long-lived objectives and workers.
Mascot/pet presentation is an optional skin — never required for operation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class UnitClass(str, Enum):
    CONTROLLER = "controller"
    TEAM = "team"
    WORKER = "worker"
    OBJECTIVE = "objective"


class UnitStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    SLEEPING = "sleeping"
    OFFLINE = "offline"
    RETIRED = "retired"


# ---------------------------------------------------------------------------
# UnitIdentity — the core UNITS record
# ---------------------------------------------------------------------------

@dataclass
class UnitIdentity:
    unit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    designation: str = ""
    number: int = 0
    name: str = ""
    unit_class: UnitClass = UnitClass.CONTROLLER
    unit_type: str = ""
    scope: str = ""
    status: UnitStatus = UnitStatus.ACTIVE
    capabilities: list[str] = field(default_factory=list)
    owner_controller: str = ""
    persona_skin: Optional[dict[str, Any]] = None
    presentation_enabled: bool = False

    @property
    def display_name(self) -> str:
        if self.presentation_enabled and self.persona_skin:
            skin_name = self.persona_skin.get("display_name", "")
            if skin_name:
                return skin_name
        if self.name:
            return f"{self.designation}-{self.number:03d} ({self.name})"
        return f"{self.designation}-{self.number:03d}"

    @property
    def short_id(self) -> str:
        return f"{self.designation}-{self.number:03d}"

    def to_header(self) -> str:
        """Single-line header for CLI display."""
        status_icon = {
            UnitStatus.ACTIVE: "+",
            UnitStatus.IDLE: "~",
            UnitStatus.SLEEPING: "z",
            UnitStatus.OFFLINE: "-",
            UnitStatus.RETIRED: "x",
        }.get(self.status, "?")
        return f"[{status_icon}] {self.short_id} | {self.unit_class.value} | {self.scope}"


# ---------------------------------------------------------------------------
# UNITS Registry — manages all unit identities
# ---------------------------------------------------------------------------

class UnitRegistry:
    """Central registry for all UNITS identities. Optional — disabled by default."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._units: dict[str, UnitIdentity] = {}
        self._next_number: dict[str, int] = {}

    def register(self, unit: UnitIdentity) -> UnitIdentity:
        if not self.enabled:
            return unit
        if unit.number == 0:
            prefix = unit.designation or unit.unit_class.value.upper()
            self._next_number.setdefault(prefix, 1)
            unit.number = self._next_number[prefix]
            self._next_number[prefix] += 1
        self._units[unit.unit_id] = unit
        return unit

    def get(self, unit_id: str) -> Optional[UnitIdentity]:
        return self._units.get(unit_id)

    def list_by_class(self, unit_class: UnitClass) -> list[UnitIdentity]:
        return [u for u in self._units.values() if u.unit_class == unit_class]

    def list_by_controller(self, controller: str) -> list[UnitIdentity]:
        return [u for u in self._units.values() if u.owner_controller == controller]

    def list_all(self) -> list[UnitIdentity]:
        return list(self._units.values())

    @property
    def count(self) -> int:
        return len(self._units)
