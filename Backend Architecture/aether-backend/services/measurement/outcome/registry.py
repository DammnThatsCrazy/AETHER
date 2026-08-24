"""Outcome-type registry consumer for the Outcome360 intelligence projection.

Consumes the canonical ``packages/shared/contracts/outcome-type-registry.json``
directly (repo-root-relative path, like
``scripts/lib/intelligence_projection_validation.load_context``), NOT a
generated twin. The generated twin
(``shared/measurement/generated_outcome_types.py``) is produced from this same
JSON by the platform contract generator after the slice lands; this module stays
authoritative against the JSON so it can never drift from the canonical source.

Load-time validation is fail-closed: an unknown ``domain``, a duplicate or
non-lower-snake ``id``, or an empty/malformed registry raises
:class:`ValueError` — a projection plane never consumes a registry it cannot
trust.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Canonical outcome-type registry path, repo-root-relative (parents[5] = repo
# root from ``services/measurement/outcome/registry.py``:
# outcome -> measurement -> services -> aether-backend -> "Backend Architecture"
# -> AETHER).
_OUTCOME_TYPE_REGISTRY_PATH = (
    Path(__file__).resolve().parents[5]
    / "packages"
    / "shared"
    / "contracts"
    / "outcome-type-registry.json"
)

_IDENT_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

_OUTCOME_TYPE_REQUIRED_FIELDS = ("id", "domain", "name", "description")


class OutcomeTypeRegistry:
    """Parsed, validated view over the canonical outcome-type registry.

    Order-stability: ``ids()`` / ``by_domain()`` return SORTED ids so the
    projection and any emitter can never depend on array order.
    """

    def __init__(self, data: Optional[dict] = None) -> None:
        """Load and validate. ``data`` defaults to the canonical JSON file."""
        if data is None:
            data = json.loads(
                _OUTCOME_TYPE_REGISTRY_PATH.read_text(encoding="utf-8")
            )
        if not isinstance(data, dict):
            raise ValueError("outcome-type registry must be a JSON object")

        self._schema_version: int = data.get("schemaVersion", 1)
        self._contract_version: str = data.get("contractVersion", "")

        domains = data.get("domains")
        if not isinstance(domains, list) or not domains:
            raise ValueError("outcome-type registry 'domains' must be a non-empty list")
        _seen_domains: set[str] = set()
        for domain in domains:
            if not isinstance(domain, str) or not _IDENT_RE.fullmatch(domain):
                raise ValueError(f"outcome-type domain {domain!r} must be lower_snake")
            if domain in _seen_domains:
                raise ValueError(f"duplicate outcome-type domain {domain!r}")
            _seen_domains.add(domain)
        self._domains: list[str] = list(domains)
        self._domain_set: set[str] = set(domains)

        types = data.get("outcomeTypes")
        if not isinstance(types, list) or not types:
            raise ValueError(
                "outcome-type registry 'outcomeTypes' must be a non-empty list"
            )
        self._types: dict[str, dict] = {}
        for entry in types:
            if not isinstance(entry, dict):
                raise ValueError("every outcomeType entry must be an object")
            for field in _OUTCOME_TYPE_REQUIRED_FIELDS:
                if field not in entry:
                    raise ValueError(f"outcomeType missing required field {field!r}")
            type_id = entry["id"]
            if not isinstance(type_id, str) or not _IDENT_RE.fullmatch(type_id):
                raise ValueError(f"outcome-type id {type_id!r} must be lower_snake")
            if type_id in self._types:
                raise ValueError(f"duplicate outcome-type id {type_id!r}")
            domain = entry["domain"]
            if domain not in self._domain_set:
                raise ValueError(
                    f"outcome-type {type_id!r} declares unknown domain {domain!r}"
                )
            if not isinstance(entry["name"], str) or not entry["name"]:
                raise ValueError(f"outcome-type {type_id!r} must have a non-empty name")
            if not isinstance(entry["description"], str) or not entry["description"]:
                raise ValueError(
                    f"outcome-type {type_id!r} must have a non-empty description"
                )
            self._types[type_id] = dict(entry)

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def contract_version(self) -> str:
        return self._contract_version

    def domains(self) -> list[str]:
        """All declared domains, in registry order."""
        return list(self._domains)

    def ids(self) -> list[str]:
        """All outcome-type ids, SORTED (order-stability)."""
        return sorted(self._types)

    def get(self, type_id: str) -> Optional[dict]:
        """The outcome-type definition for ``type_id``, or ``None``."""
        return self._types.get(type_id)

    def by_domain(self, domain: str) -> list[dict]:
        """Outcome types in ``domain``, sorted by id (order-stability)."""
        return [
            self._types[type_id]
            for type_id in sorted(self._types)
            if self._types[type_id]["domain"] == domain
        ]


# Module-level singleton consumed by the Outcome360 provider.
outcome_type_registry = OutcomeTypeRegistry()

__all__ = [
    "OutcomeTypeRegistry",
    "outcome_type_registry",
]
