"""Kyber disclosure levels — how much of the platform a request may see.

Disclosure is orthogonal to *which* resource a request touches (that is the
capability) and to *whose* data it touches (that is the tenant access scope).
A role template establishes a ceiling; the effective level granted to any one
request is the MINIMUM of that ceiling and every other constraint in play
(purpose, environment, device state, session strength, risk, consent, policy).

    D0  Platform topology            services, releases, dependency shape
    D1  Fleet aggregates            cross-tenant counts/rates, never a tenant row
    D2  Masked tenant summaries     one tenant, identifiers masked
    D3  Tenant-visible Aether data  exactly what the tenant sees (Tenant Mirror)
    D4  Event-level evidence        individual events, lineage, decisions
    D5  Restricted raw evidence     unmasked raw records; always step-up gated

Nothing here decides access on its own — ``access.dependencies`` composes this
with capabilities, scopes and session strength. Levels are ordered and
comparable so "at most" and "at least" checks are total.
"""
from __future__ import annotations

from enum import IntEnum
from typing import Literal, Optional

DisclosureName = Literal["D0", "D1", "D2", "D3", "D4", "D5"]


class DisclosureLevel(IntEnum):
    """Ordered disclosure levels. Higher means more is revealed."""

    D0_PLATFORM_TOPOLOGY = 0
    D1_FLEET_AGGREGATE = 1
    D2_TENANT_MASKED = 2
    D3_TENANT_VISIBLE = 3
    D4_EVENT_EVIDENCE = 4
    D5_RAW_EVIDENCE = 5

    @property
    def name_token(self) -> DisclosureName:
        return f"D{int(self)}"  # type: ignore[return-value]

    @classmethod
    def parse(cls, value: "DisclosureLevel | DisclosureName | int | str") -> "DisclosureLevel":
        """Coerce a level from an enum, a ``D<n>`` token, or an int."""
        if isinstance(value, DisclosureLevel):
            return value
        if isinstance(value, int):
            return cls(value)
        token = str(value).strip().upper()
        if token.startswith("D") and token[1:].isdigit():
            return cls(int(token[1:]))
        raise ValueError(f"unrecognised disclosure level: {value!r}")


# Levels at or above this reveal a specific tenant rather than an aggregate, so
# they require an active, purpose-bound tenant access scope.
TENANT_SCOPED_FROM = DisclosureLevel.D2_TENANT_MASKED

# Levels at or above this reveal individual records and always require a fresh
# step-up authentication, regardless of role.
STEP_UP_REQUIRED_FROM = DisclosureLevel.D4_EVENT_EVIDENCE


def requires_tenant_scope(level: DisclosureLevel) -> bool:
    """True when the level exposes one tenant rather than an aggregate."""
    return level >= TENANT_SCOPED_FROM


def requires_step_up(level: DisclosureLevel) -> bool:
    """True when the level exposes record-level evidence."""
    return level >= STEP_UP_REQUIRED_FROM


def effective_disclosure(
    *constraints: Optional["DisclosureLevel | DisclosureName | int | str"],
) -> DisclosureLevel:
    """The minimum of every supplied constraint — the fail-closed composition.

    ``None`` constraints are ignored (a dimension that imposes no ceiling). With
    no constraints at all the result is ``D0``, the least-revealing level, so a
    caller that forgets to pass anything gets topology and nothing more.
    """
    levels = [DisclosureLevel.parse(c) for c in constraints if c is not None]
    if not levels:
        return DisclosureLevel.D0_PLATFORM_TOPOLOGY
    return min(levels)


def masks_tenant_identifiers(level: DisclosureLevel) -> bool:
    """True when tenant-identifying fields must be masked in the response."""
    return level <= DisclosureLevel.D2_TENANT_MASKED
