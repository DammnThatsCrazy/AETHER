"""
Aether Compliance — Consent Registry Reconciliation.

Verifies that the compliance ``ConsentPurpose`` enum (and its opt-in flags) stay
in sync with the canonical platform consent registry at
``packages/shared/contracts/consent-registry.json`` (11 purposes). The registry
is the single source of truth; this module never mutates it.

The registry is path-resolved relative to the repo root by walking up parent
directories, so the check works regardless of the current working directory.

Reconciliation asserts:
  * every canonical registry key has a ``ConsentPurpose`` member,
  * no ``ConsentPurpose`` member is a non-canonical, first-class purpose
    (legacy keys must be declared in ``LEGACY_PURPOSE_ALIASES``), and
  * each purpose's explicit-opt-in flag matches the registry
    ``explicitOptInRequired`` field.

Call ``assert_consent_registry_in_sync()`` from tests / CI to fail on drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from config.compliance_config import (
    EXPLICIT_OPT_IN_PURPOSES,
    LEGACY_PURPOSE_ALIASES,
    ConsentPurpose,
)

# Registry location relative to the repo root.
REGISTRY_RELPATH = Path("packages") / "shared" / "contracts" / "consent-registry.json"


class ConsentRegistryError(RuntimeError):
    """Raised when the compliance enum drifts from the canonical registry."""


def find_registry_path(start: Path = None) -> Path:
    """Locate the canonical consent registry.

    Walks up from ``start`` (this file by default) through every parent directory
    looking for ``packages/shared/contracts/consent-registry.json``.
    """
    origin = Path(start).resolve() if start is not None else Path(__file__).resolve()
    for base in (origin, *origin.parents):
        candidate = base / REGISTRY_RELPATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"Could not locate {REGISTRY_RELPATH} walking up from {origin}"
    )


def load_registry(start: Path = None) -> dict:
    """Load and parse the canonical consent registry JSON."""
    path = find_registry_path(start)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def canonical_purposes(start: Path = None) -> list:
    """Return the raw list of purpose objects from the registry."""
    return list(load_registry(start).get("purposes", []))


def canonical_keys(start: Path = None) -> list:
    """Return the ordered list of canonical purpose keys."""
    return [p["key"] for p in canonical_purposes(start)]


def canonical_opt_in_flags(start: Path = None) -> dict:
    """Map each canonical purpose key to its ``explicitOptInRequired`` flag."""
    return {
        p["key"]: bool(p.get("explicitOptInRequired", False))
        for p in canonical_purposes(start)
    }


@dataclass(frozen=True)
class ReconciliationReport:
    """Structured result of reconciling the enum against the registry."""

    canonical_keys: tuple
    enum_values: tuple
    missing_members: tuple       # canonical keys with no ConsentPurpose member
    uncanonical_members: tuple   # ConsentPurpose members not canonical and not aliased
    opt_in_mismatches: tuple     # (key, enum_flag, registry_flag)

    @property
    def in_sync(self) -> bool:
        return not (
            self.missing_members
            or self.uncanonical_members
            or self.opt_in_mismatches
        )

    def as_error_text(self) -> str:
        lines = []
        if self.missing_members:
            lines.append(
                "  Missing ConsentPurpose members for canonical keys: "
                + ", ".join(self.missing_members)
            )
        if self.uncanonical_members:
            lines.append(
                "  Non-canonical ConsentPurpose members (add to the registry or "
                "declare in LEGACY_PURPOSE_ALIASES): "
                + ", ".join(self.uncanonical_members)
            )
        if self.opt_in_mismatches:
            lines.append("  explicitOptInRequired mismatches (key: enum vs registry):")
            lines.extend(
                f"    {key}: enum={enum_flag} registry={registry_flag}"
                for key, enum_flag, registry_flag in self.opt_in_mismatches
            )
        return "\n".join(lines)


def reconcile(start: Path = None) -> ReconciliationReport:
    """Reconcile ``ConsentPurpose`` against the canonical registry (no raise)."""
    keys = canonical_keys(start)
    flags = canonical_opt_in_flags(start)
    enum_values = {p.value for p in ConsentPurpose}
    alias_keys = set(LEGACY_PURPOSE_ALIASES.keys())
    opt_in_values = {p.value for p in EXPLICIT_OPT_IN_PURPOSES}

    missing = tuple(k for k in keys if k not in enum_values)
    uncanonical = tuple(
        sorted(v for v in enum_values if v not in keys and v not in alias_keys)
    )
    mismatches = tuple(
        (k, k in opt_in_values, flags[k])
        for k in keys
        if k in enum_values and (k in opt_in_values) != flags[k]
    )
    return ReconciliationReport(
        canonical_keys=tuple(keys),
        enum_values=tuple(sorted(enum_values)),
        missing_members=missing,
        uncanonical_members=uncanonical,
        opt_in_mismatches=mismatches,
    )


def assert_consent_registry_in_sync(start: Path = None) -> ReconciliationReport:
    """Reconcile the enum against the registry; raise ``ConsentRegistryError`` on drift.

    Returns the ``ReconciliationReport`` on success so callers can inspect it.
    """
    report = reconcile(start)
    if not report.in_sync:
        raise ConsentRegistryError(
            "Compliance ConsentPurpose enum is out of sync with the canonical "
            "consent registry (packages/shared/contracts/consent-registry.json):\n"
            + report.as_error_text()
        )
    return report
