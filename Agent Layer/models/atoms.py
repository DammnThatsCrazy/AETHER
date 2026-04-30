"""
Aether Agent Layer — Atoms Identity & Mascot Layer
Fully real but fully optional identity + mascot presentation layer.

Atoms applies by default to controllers and teams.
Atoms may optionally apply to long-lived objectives and workers.
Mascot/pet presentation is an optional skin — never required for operation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AtomClass(str, Enum):
    CONTROLLER = "controller"
    TEAM = "team"
    WORKER = "worker"
    OBJECTIVE = "objective"


class AtomStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    SLEEPING = "sleeping"
    OFFLINE = "offline"
    RETIRED = "retired"


# ---------------------------------------------------------------------------
# AtomIdentity — the core Atoms record
# ---------------------------------------------------------------------------

@dataclass
class AtomIdentity:
    atom_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    designation: str = ""
    number: int = 0
    name: str = ""
    atom_class: AtomClass = AtomClass.CONTROLLER
    atom_type: str = ""
    scope: str = ""
    status: AtomStatus = AtomStatus.ACTIVE
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
            AtomStatus.ACTIVE: "+",
            AtomStatus.IDLE: "~",
            AtomStatus.SLEEPING: "z",
            AtomStatus.OFFLINE: "-",
            AtomStatus.RETIRED: "x",
        }.get(self.status, "?")
        return f"[{status_icon}] {self.short_id} | {self.atom_class.value} | {self.scope}"


# ---------------------------------------------------------------------------
# Atoms Registry — manages all atom identities
# ---------------------------------------------------------------------------

class AtomRegistry:
    """Central registry for all Atoms identities. Optional — disabled by default."""

    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self._atoms: dict[str, AtomIdentity] = {}
        self._next_number: dict[str, int] = {}

    def register(self, atom: AtomIdentity) -> AtomIdentity:
        if not self.enabled:
            return atom
        if atom.number == 0:
            prefix = atom.designation or atom.atom_class.value.upper()
            self._next_number.setdefault(prefix, 1)
            atom.number = self._next_number[prefix]
            self._next_number[prefix] += 1
        self._atoms[atom.atom_id] = atom
        return atom

    def get(self, atom_id: str) -> Optional[AtomIdentity]:
        return self._atoms.get(atom_id)

    def list_by_class(self, atom_class: AtomClass) -> list[AtomIdentity]:
        return [a for a in self._atoms.values() if a.atom_class == atom_class]

    def list_by_controller(self, controller: str) -> list[AtomIdentity]:
        return [a for a in self._atoms.values() if a.owner_controller == controller]

    def list_all(self) -> list[AtomIdentity]:
        return list(self._atoms.values())

    @property
    def count(self) -> int:
        return len(self._atoms)
