"""Aether — Rights Authority: deterministic lifecycle / retention resolution.

Stream P-B2 (part 2) of the ``rights_irrl`` canonical authority. Implements
blueprint §9: effective lifecycle resolution is a *single deterministic
precedence* over the existing retention authorities — there is NO separate
retention platform.

Deterministic precedence (1 is highest):
    1. legal_prohibition / mandatory deletion
    2. legal_hold / preservation obligation
    3. contract-specific explicit rule
    4. source-license rule
    5. DataRightsGrant rule
    6. tenant rights profile
    7. canonical event retention class
    8. storage policy
    9. platform default

Every material resolution is persisted as a durable ``RightsDecision``-adjacent
record (``rights_decision_repository``, ``requested_use="lifecycle_resolution"``).
The deletion cascade is dependency-aware: each dependent component receives the
action appropriate to its type.
"""
from __future__ import annotations

import importlib
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.rights_irrl.lifecycle")

POLICY_VERSION = "irrl-2"

# Lifecycle actions (blueprint §9 vocabulary, snake_case).
LIFECYCLE_ACTIONS: tuple[str, ...] = (
    "preserve",
    "delete",
    "hard_delete",
    "tombstone",
    "quarantine",
    "suppress",
    "invalidate",
    "recompute",
    "retrain",
    "anonymize",
    "generalize",
    "legal_hold",
)

_NON_DESTRUCTIVE_ACTIONS = frozenset({
    "preserve", "legal_hold", "quarantine", "suppress", "tombstone",
})

# Documented 9-level precedence (level_number, key, one-line label).
LIFECYCLE_PRECEDENCE: tuple[tuple[int, str, str], ...] = (
    (1, "legal_prohibition", "Legal prohibition / mandatory deletion"),
    (2, "legal_hold", "Legal hold / preservation obligation"),
    (3, "contract", "Contract-specific explicit rule"),
    (4, "source_license", "Source-license rule"),
    (5, "grant", "DataRightsGrant rule"),
    (6, "tenant_profile", "Tenant rights profile"),
    (7, "event_retention_class", "Canonical event retention class"),
    (8, "storage_policy", "Resource storage policy"),
    (9, "platform_default", "Platform default"),
)

# Platform fallback for derived vs contributed material (used when no higher
# level is decisive). Bias is retention-safe: unknown never deletes silently.
PLATFORM_DEFAULT_ACTION = "preserve"
DERIVATION_PLATFORM_ACTIONS: dict[str, str] = {
    "source_representation": "delete",
    "normalized": "delete",
    "tenant_identifiable_derivative": "recompute_or_delete",
    "aether_generated_intelligence": "recompute_or_delete",
    "aggregated": "recompute_or_delete",
    "generalized": "preserve",
    "model_derived": "retrain_or_evaluation",
    "platform_knowledge": "preserve",
}

# Canonical event retention class → action (level 7).
EVENT_RETENTION_CLASS_ACTIONS: dict[str, str] = {
    "event_class_audit": "preserve",
    "event_class_compliance": "preserve",
    "event_class_operational": "delete",
    "event_class_analytics": "delete",
    "event_class_security": "preserve",
}

# Component-type → cascade action when the winning lifecycle action is a
# destructive / recompute-style action.
COMPONENT_CASCADE_ACTIONS: dict[str, str] = {
    "raw_object": "hard_delete",
    "normalized_row": "delete",
    "graph_edge": "delete",
    "vector_embedding": "recompute_or_delete",
    "cached_result": "recompute_or_delete",
    "derived_profile_attribute": "recompute_or_delete",
    "exported_artifact": "tenant_retains",
    "model_training_input": "retrain_or_evaluation",
    "model_weight": "retrain_or_evaluation",
    "generalized_artifact": "recheck_eligibility",
    "benchmark": "retain_if_generalization_passed",
    "ontology_improvement": "retain",
}


def _pb1_repositories():
    """P-B1: ``services.rights_authority.repositories`` singleton stores."""
    return importlib.import_module("services.rights_authority.repositories")


class LifecycleResolution(BaseModel):
    """Effective lifecycle resolution for one governed artifact / grant."""

    resolution_id: str = Field(default_factory=lambda: f"lr_{uuid.uuid4().hex}")
    tenant_id: str
    artifact_ref: Optional[str] = None
    action: str
    basis: str  # e.g. "level_2_legal_hold" — which precedence level won.
    basis_label: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION
    decision_ref: Optional[str] = None
    resolved_at: str = Field(default_factory=lambda: utc_now().isoformat())

    def deletion_cascade(self, dependency_map: dict[str, str]) -> list[dict[str, str]]:
        """Dependency-aware cascade: map each dependent component to its action.

        ``dependency_map`` maps a component reference → component type (one of
        the ``COMPONENT_CASCADE_ACTIONS`` keys). When the winning lifecycle
        action is non-destructive (preserve / legal_hold / quarantine /
        suppress / tombstone) every component inherits that action verbatim;
        otherwise each component receives the type-appropriate action.
        """
        rows: list[dict[str, str]] = []
        effective = self.action.lower()
        if effective in _NON_DESTRUCTIVE_ACTIONS:
            for component_ref, component_type in (dependency_map or {}).items():
                rows.append({
                    "component_ref": component_ref,
                    "component_type": component_type,
                    "action": effective,
                    "basis": self.basis,
                    "policy_version": self.policy_version,
                })
            return rows
        for component_ref, component_type in (dependency_map or {}).items():
            action = COMPONENT_CASCADE_ACTIONS.get(component_type, effective)
            rows.append({
                "component_ref": component_ref,
                "component_type": component_type,
                "action": action,
                "basis": self.basis,
                "policy_version": self.policy_version,
            })
        return rows


# ═══════════════════════════════════════════════════════════════════════════
# Decision extraction helpers
# ═══════════════════════════════════════════════════════════════════════════

def _norm_action(value: Any) -> str:
    """Normalise an action to canonical lowercase snake."""
    if hasattr(value, "value"):
        value = value.value
    return str(value).strip().lower()


def _obj_action(obj: Any) -> Optional[str]:
    """Explicit action carried by an object / dict, if any."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        for key in ("action", "lifecycle_action", "decision"):
            if obj.get(key) is not None:
                return _norm_action(obj[key])
        return None
    for attr in ("lifecycle_action", "action", "decision_action"):
        if hasattr(obj, attr):
            raw = getattr(obj, attr)
            if raw is not None:
                return _norm_action(raw)
    return None


def _is_active_legal_hold(obj: Any) -> bool:
    """Whether a legal-hold input is active."""
    if obj is None:
        return False
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, dict):
        if obj.get("active") is False:
            return False
        if obj.get("active") is True or obj.get("legal_hold_id") is not None:
            return True
        return "legal_hold" in str(_norm_action(obj.get("action", "")))
    active = getattr(obj, "active", None)
    if active is not None:
        return bool(active)
    return getattr(obj, "legal_hold_id", None) is not None or bool(
        getattr(obj, "preserve", False)
    )


def _grant_action(grant: Any) -> Optional[str]:
    """Lifecycle decision carried by a DataRightsGrant.

    Seam: the P-A grant carries structured ``termination_authority`` / retention
    components; until then a grant may carry an explicit ``lifecycle_action`` /
    ``termination_action`` attribute or an ``action`` key. Unknown → None (the
    grant level is not decisive and lower levels / platform default apply).
    """
    if grant is None:
        return None
    explicit = _obj_action(grant)
    if explicit:
        return explicit
    termination = getattr(grant, "termination_authority", None)
    if termination is not None:
        # termination_authority components express per-class retention verbs
        # (e.g. contributed_source_data: delete_by_policy). Map the dominant
        # verb onto a lifecycle action when present.
        verb_map = {
            "delete_by_policy": "delete",
            "recompute_or_delete": "recompute_or_delete",
            "tenant_retains": "tenant_retains",
            "retain_as_required": "preserve",
            "retain_if_independently_qualified": "preserve",
            "retain": "preserve",
            "retain_if_generalization_passed": "preserve",
            "governed_retention": "preserve",
        }
        resolved: set[str] = set()
        for name in dir(termination):
            if name.startswith("_"):
                continue
            try:
                raw = getattr(termination, name)
            except Exception:  # pragma: no cover
                continue
            if raw is None or isinstance(raw, (bool, int)):
                continue
            verb = _norm_action(raw)
            if verb in verb_map:
                resolved.add(verb_map[verb])
        if isinstance(termination, dict):
            for raw in termination.values():
                verb = _norm_action(raw)
                if verb in verb_map:
                    resolved.add(verb_map[verb])
        if len(resolved) == 1:
            return next(iter(resolved))
        if "delete" in resolved:
            return "delete"
    return None


def _retention_class_action(event_retention_class: Optional[str]) -> Optional[str]:
    if not event_retention_class:
        return None
    cls = _norm_action(event_retention_class)
    return EVENT_RETENTION_CLASS_ACTIONS.get(cls)


# ═══════════════════════════════════════════════════════════════════════════
# Resolution
# ═══════════════════════════════════════════════════════════════════════════

async def resolve_effective_lifecycle(
    *,
    tenant_id: str,
    artifact_ref: Optional[str] = None,
    grant: Optional[Any] = None,
    retention_policy: Optional[Any] = None,
    event_retention_class: Optional[str] = None,
    storage_policy: Optional[Any] = None,
    legal_hold: Optional[Any] = None,
    artifact_derivation_class: Optional[str] = None,
    legal_prohibition: Optional[Any] = None,
    contract_rule: Optional[Any] = None,
    source_license: Optional[Any] = None,
    tenant_profile: Optional[Any] = None,
    platform_default: Optional[Any] = None,
) -> LifecycleResolution:
    """Resolve the effective lifecycle action by deterministic §9 precedence.

    Levels are evaluated from highest (1) to lowest (9); the first level that is
    *decisive* wins and is recorded as ``basis``. A level is decisive only when
    its input carries an explicit action — an absent or unknown input never
    invents one (fail closed). Every resolution is persisted as a durable
    RightsDecision-adjacent record.
    """
    reason_codes: list[str] = []

    # Level 1 — legal prohibition / mandatory deletion.
    prohibition = _obj_action(legal_prohibition)
    if legal_prohibition is not None and prohibition is None:
        prohibition = "hard_delete"
    if prohibition:
        return await _finalize(
            tenant_id=tenant_id,
            artifact_ref=artifact_ref,
            action=prohibition,
            level_key="legal_prohibition",
            reason_codes=[*reason_codes, "legal_prohibition"],
        )

    # Level 2 — legal hold / preservation obligation.
    if _is_active_legal_hold(legal_hold):
        return await _finalize(
            tenant_id=tenant_id,
            artifact_ref=artifact_ref,
            action="legal_hold",
            level_key="legal_hold",
            reason_codes=[*reason_codes, "legal_hold_active"],
        )

    # Levels 3-6 — explicit action from the corresponding input.
    for level_key, source in (
        ("contract", contract_rule),
        ("source_license", source_license),
        ("grant", grant),
        ("tenant_profile", tenant_profile),
    ):
        if source is None:
            continue
        action: Optional[str]
        if level_key == "grant":
            action = _grant_action(source)
        else:
            action = _obj_action(source)
        if action:
            return await _finalize(
                tenant_id=tenant_id,
                artifact_ref=artifact_ref,
                action=action,
                level_key=level_key,
                reason_codes=[*reason_codes, f"{level_key}_rule"],
            )

    # Level 7 — canonical event retention class.
    class_action = _retention_class_action(event_retention_class)
    if class_action:
        return await _finalize(
            tenant_id=tenant_id,
            artifact_ref=artifact_ref,
            action=class_action,
            level_key="event_retention_class",
            reason_codes=[*reason_codes, "event_retention_class_rule"],
        )
    if event_retention_class:
        reason_codes.append("unmapped_event_retention_class")

    # Level 8 — resource storage policy.
    if storage_policy is not None:
        storage_action = _obj_action(storage_policy)
        if storage_action:
            return await _finalize(
                tenant_id=tenant_id,
                artifact_ref=artifact_ref,
                action=storage_action,
                level_key="storage_policy",
                reason_codes=[*reason_codes, "storage_policy_rule"],
            )

    # Level 9 — platform default (retention-safe; unknown never silently deletes
    # but also never silently retains material subject to a deletion request).
    derivation = _norm_action(artifact_derivation_class) if artifact_derivation_class else ""
    platform_action = (
        DERIVATION_PLATFORM_ACTIONS.get(derivation, PLATFORM_DEFAULT_ACTION)
        if platform_default is None
        else (_obj_action(platform_default) or PLATFORM_DEFAULT_ACTION)
    )
    return await _finalize(
        tenant_id=tenant_id,
        artifact_ref=artifact_ref,
        action=platform_action,
        level_key="platform_default",
        reason_codes=[*reason_codes, "platform_default"],
    )


async def _finalize(
    *,
    tenant_id: str,
    artifact_ref: Optional[str],
    action: str,
    level_key: str,
    reason_codes: list[str],
) -> LifecycleResolution:
    """Build, persist, and return a LifecycleResolution."""
    action = _norm_action(action)
    if action == "recompute_or_delete":
        # Canonical lifecycle-action vocabulary has no recompute_or_delete; it
        # decomposes into a recompute requirement the adapter must satisfy.
        action = "recompute"
    level_number, _, label = next(
        (lv, key, lab) for lv, key, lab in LIFECYCLE_PRECEDENCE if key == level_key
    )
    resolution = LifecycleResolution(
        tenant_id=tenant_id,
        artifact_ref=artifact_ref,
        action=action,
        basis=f"level_{level_number}_{level_key}",
        basis_label=label,
        reason_codes=list(reason_codes),
        policy_version=POLICY_VERSION,
    )
    resolution.decision_ref = await _persist_resolution(resolution)
    return resolution


async def _persist_resolution(resolution: LifecycleResolution) -> str:
    """Durable RightsDecision-adjacent lifecycle resolution record."""
    repos = _pb1_repositories()
    decision_id = f"rdec_{uuid.uuid4().hex}"
    row = {
        "decision_id": decision_id,
        "tenant_id": resolution.tenant_id,
        "allowed": True,
        "disposition": "recorded",
        "reason_codes": list(resolution.reason_codes),
        "source_grant_refs": [],
        "consent_decision_refs": [],
        "permitted_uses": [],
        "permitted_derivations": [],
        "permitted_learning": [],
        "permitted_disclosures": [],
        "retention": resolution.action,
        "deletion": resolution.action,
        "survival": resolution.action,
        "evaluated_at": resolution.resolved_at,
        "effective_as_of": resolution.resolved_at,
        "policy_version": resolution.policy_version,
        "evidence_refs": [resolution.resolution_id],
        "requested_use": "lifecycle_resolution",
        "lifecycle_basis": resolution.basis,
        "artifact_ref": resolution.artifact_ref,
    }
    await repos.rights_decision_repository.record(row)
    return decision_id


__all__ = [
    "COMPONENT_CASCADE_ACTIONS",
    "DERIVATION_PLATFORM_ACTIONS",
    "EVENT_RETENTION_CLASS_ACTIONS",
    "LIFECYCLE_ACTIONS",
    "LIFECYCLE_PRECEDENCE",
    "LifecycleResolution",
    "PLATFORM_DEFAULT_ACTION",
    "POLICY_VERSION",
    "resolve_effective_lifecycle",
]
