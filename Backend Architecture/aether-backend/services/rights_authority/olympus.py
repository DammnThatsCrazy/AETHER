"""Aether — Rights Authority: Olympus internal intelligence authority.

Stream P-B2 (part 2) of the ``rights_irrl`` canonical authority. Implements
blueprint §7 / §35–§36 / §9-F: Olympus-internal operators act through a first-
class actor + purpose vocabulary — there is deliberately NO ``olympus_superuser``
concept. Authority derives from *purpose + capabilities*, never from a global
superuser flag.

Prohibited (blueprint §13): unrestricted operator browsing of all-tenant raw
records; Olympus-internal multi-tenant queries without purpose-bound authority.
Backend resolves authority; frontend never determines rights.
"""
from __future__ import annotations

import importlib
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from services.rights_authority.generalization import _norm_enum_value

logger = get_logger("aether.rights_irrl.olympus")

OLYMPUS_INTERNAL_ACTOR = "olympus_internal"
CANONICAL_OLYMPUS_ROLES = frozenset({"olympus_operator", "olympus_security_operator"})
POLICY_VERSION = "irrl-2"
OWNERSHIP_CLASS_OLYMPUS_KNOWLEDGE = "generalized_knowledge"

# Frozen Olympus purpose vocabulary (blueprint §7). P-A exposes these as members
# of the OlympusPurpose enum (snake_case values); PURPOSE_ALLOWLIST mirrors the
# frozen vocabulary so authorize() stays deterministic while the enum lands.
OLYMPUS_PURPOSES: tuple[str, ...] = (
    "platform_research",
    "model_improvement",
    "security_research",
    "fraud_research",
    "resolver_calibration",
    "ontology_research",
    "product_analytics",
    "benchmark_analysis",
    "support_investigation",
    "incident_response",
)

PURPOSE_ALLOWLIST: tuple[str, ...] = OLYMPUS_PURPOSES

# Raw / generalized data-class prefixes used by Kyber intelligence requests.
RAW_DATA_CLASS_PREFIX = "raw."
GENERALIZED_DATA_CLASS_PREFIX = "generalized."

# Purpose-scoped allow/deny matrix (blueprint §7 / §9-F).
#   allowed_tenants: "generalized_only" → operator may NOT request tenant-scoped
#       material (only generalized, non-identifiable aggregates);
#                   "scope_owned" → operator may access the tenant-local scope a
#       support/security purpose requires (still grant-gated for raw data).
#   default_data_classes: data classes the purpose may read by default.
#   requires_generalization: raw data requires gateway generalization first.
PURPOSE_SCOPE_MATRIX: dict[str, dict[str, Any]] = {
    "platform_research": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.graph_pattern", "generalized.behavioral_motif",
            "generalized.feature_distribution", "generalized.ontology_improvement",
        ],
        "requires_generalization": True,
    },
    "model_improvement": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.graph_pattern", "generalized.feature_distribution",
            "generalized.model_improvement", "generalized.benchmark",
        ],
        "requires_generalization": True,
    },
    "security_research": {
        "allowed_tenants": "scope_owned",
        "default_data_classes": [
            "security_event", "risk_vector", "fraud_hypothesis",
            "generalized.graph_pattern", "raw.scope_tenant_local",
        ],
        "requires_generalization": False,
        "allowed_scopes": ("security", "support"),
    },
    "fraud_research": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.fraud_pattern", "generalized.graph_pattern",
            "generalized.behavioral_motif",
        ],
        "requires_generalization": True,
    },
    "resolver_calibration": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.resolver_calibration", "generalized.graph_pattern",
        ],
        "requires_generalization": True,
    },
    "ontology_research": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.ontology_improvement", "generalized.schema_mapping",
        ],
        "requires_generalization": True,
    },
    "product_analytics": {
        # Example from blueprint §7: product analytics may only read
        # generalized, non-identifiable material.
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.graph_pattern", "generalized.feature_distribution",
            "generalized.behavioral_motif",
        ],
        "requires_generalization": True,
    },
    "benchmark_analysis": {
        "allowed_tenants": "generalized_only",
        "default_data_classes": [
            "generalized.benchmark", "generalized.aggregate",
            "generalized.graph_pattern",
        ],
        "requires_generalization": True,
    },
    "support_investigation": {
        "allowed_tenants": "scope_owned",
        "default_data_classes": [
            "security_event", "risk_vector", "fraud_hypothesis",
            "raw.scope_tenant_local",
        ],
        "requires_generalization": False,
        "allowed_scopes": ("support",),
    },
    "incident_response": {
        "allowed_tenants": "scope_owned",
        "default_data_classes": [
            "security_event", "risk_vector", "fraud_hypothesis",
            "raw.scope_tenant_local", "generalized.graph_pattern",
        ],
        "requires_generalization": False,
        "allowed_scopes": ("security", "support"),
    },
}


def _pa_models():
    """P-A: ``services.integrations.data_rights.models`` (OlympusPurpose)."""
    return importlib.import_module("services.integrations.data_rights.models")


def _pb1_repositories():
    """P-B1: ``services.rights_authority.repositories`` singleton stores."""
    return importlib.import_module("services.rights_authority.repositories")


def olympus_purpose_allowlist() -> tuple[str, ...]:
    """Derive the allowlist from the OlympusPurpose enum when importable.

    When the parallel P-A enum is present it is authoritative; the frozen
    ``PURPOSE_ALLOWLIST`` constant remains the deterministic fallback.
    """
    try:
        enum_cls = _pa_models().OlympusPurpose
        values = tuple(_norm_enum_value(m) for m in enum_cls)
        if values:
            return values
    except Exception:  # pragma: no cover
        pass
    return PURPOSE_ALLOWLIST


def _disclosure_classes(grants: list[Any]) -> frozenset[str]:
    out: set[str] = set()
    for grant in grants or []:
        component = getattr(grant, "disclosure_authority", None)
        if component is None and isinstance(grant, dict):
            component = grant.get("disclosure_authority")
        if component is None:
            continue
        if isinstance(component, dict):
            for key, value in component.items():
                if value is True:
                    out.add(_norm_enum_value(key))
            continue
        for name in dir(component):
            if name.startswith("_"):
                continue
            try:
                if getattr(component, name) is True:
                    out.add(_norm_enum_value(name))
            except Exception:  # pragma: no cover
                continue
    return frozenset(out)


def _source_use_classes(grants: list[Any]) -> frozenset[str]:
    out: set[str] = set()
    for grant in grants or []:
        component = getattr(grant, "source_use", None)
        if component is None and isinstance(grant, dict):
            component = grant.get("source_use")
        if isinstance(component, dict):
            for key, value in component.items():
                if value is True:
                    out.add(_norm_enum_value(key))
        elif component is not None:
            for name in dir(component):
                if name.startswith("_"):
                    continue
                try:
                    if getattr(component, name) is True:
                        out.add(_norm_enum_value(name))
                except Exception:  # pragma: no cover
                    continue
    return frozenset(out)


class KyberIntelligenceRequest(BaseModel):
    """Blueprint §35 operator intelligence request (backend resolves authority)."""

    operator_id: str
    role: str
    purpose: str
    requested_tenants: list[str] = Field(default_factory=list)
    requested_scope: str = ""
    source_id: Optional[str] = None
    requested_data_classes: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=list)


class OlympusInternalDecision(BaseModel):
    """Purpose-bound authorization decision (mirrors the RightsDecision surface).

    ``RightsDecision`` is the P-B1-owned contract; this is the internal decision
    shape returned + persisted by this module and mapped onto the P-B1 model at
    the integration seam.
    """

    decision_id: str = Field(default_factory=lambda: f"rdec_{uuid.uuid4().hex}")
    actor: str = OLYMPUS_INTERNAL_ACTOR
    operator_id: str = ""
    purpose: str = ""
    allowed: bool = False
    disposition: str = "deny"
    reason_codes: list[str] = Field(default_factory=list)
    source_grant_refs: list[str] = Field(default_factory=list)
    consent_decision_refs: list[str] = Field(default_factory=list)
    ownership_class: str = OWNERSHIP_CLASS_OLYMPUS_KNOWLEDGE
    permitted_uses: list[str] = Field(default_factory=list)
    permitted_derivations: list[str] = Field(default_factory=list)
    permitted_learning: list[str] = Field(default_factory=list)
    permitted_disclosures: list[str] = Field(default_factory=list)
    retention: str = ""
    deletion: str = ""
    survival: str = ""
    evaluated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    effective_as_of: str = Field(default_factory=lambda: utc_now().isoformat())
    policy_version: str = POLICY_VERSION
    evidence_refs: list[str] = Field(default_factory=list)
    requested_scope: str = ""
    requested_tenants: list[str] = Field(default_factory=list)
    authorized_tenants: list[str] = Field(default_factory=list)
    allowed_data_classes: list[str] = Field(default_factory=list)

    def to_envelope_ref(self) -> str:
        return self.decision_id


class OlympusInternalAuthority:
    """Purpose-bound internal authority. There is no ``olympus_superuser``."""

    def __init__(self, decision_repository: Optional[Any] = None) -> None:
        self._decision_repository = decision_repository

    def _decisions(self) -> Any:
        if self._decision_repository is not None:
            return self._decision_repository
        return _pb1_repositories().rights_decision_repository

    # ── Public API ──────────────────────────────────────────────────────────

    async def authorize(
        self,
        request: KyberIntelligenceRequest,
        *,
        grant_records: Optional[list[Any]] = None,
    ) -> OlympusInternalDecision:
        """Authorize (or deny) an Olympus-internal intelligence request.

        Checks, in order:
        1. actor is olympus internal (the authority never delegates to tenants);
        2. purpose is a valid OlympusPurpose value (else ``unknown_purpose``);
        3. requested scope is known for the purpose (else ``unknown_scope``);
        4. requested tenants respect the purpose's tenant mode;
        5. requested data classes are within the purpose's allowed set;
        6. raw / cross-tenant-identifiable disclosure is grant-confirmed when
           grant records are supplied (fail closed when they cannot confirm);
        7. generalized material is only reached where the grant permits
           ``generalized_cross_tenant`` (and olympus baseline for raw).
        """
        decision = OlympusInternalDecision(
            operator_id=request.operator_id,
            purpose=request.purpose,
            requested_scope=request.requested_scope,
            requested_tenants=list(request.requested_tenants),
            evidence_refs=[],
        )

        # 1. Actor.
        if _norm_enum_value(request.role) not in CANONICAL_OLYMPUS_ROLES:
            decision.reason_codes.append("actor_not_olympus_internal")

        # 2. Purpose allowlist.
        purpose = _norm_enum_value(request.purpose)
        if purpose not in PURPOSE_ALLOWLIST:
            decision.reason_codes.append("unknown_purpose")
        else:
            decision.purpose = purpose

        matrix = PURPOSE_SCOPE_MATRIX.get(purpose)
        if matrix is None:
            decision.reason_codes.append("unknown_purpose")

        if matrix is not None:
            self._check_scope_tenants(request, matrix, decision)
            self._check_data_classes(request, matrix, decision)
            self._check_grant_disclosure(request, matrix, grant_records, decision)

        decision.allowed = not decision.reason_codes
        decision.disposition = "allow" if decision.allowed else "deny"
        if decision.allowed and matrix is not None:
            decision.allowed_data_classes = sorted(set(request.requested_data_classes))
            decision.authorized_tenants = list(request.requested_tenants)

        await self._persist(decision)
        return decision

    # ── internal checks ─────────────────────────────────────────────────────

    def _check_scope_tenants(
        self,
        request: KyberIntelligenceRequest,
        matrix: dict[str, Any],
        decision: OlympusInternalDecision,
    ) -> None:
        scope = _norm_enum_value(request.requested_scope)
        allowed_scopes = matrix.get("allowed_scopes")
        if allowed_scopes is not None and scope not in {str(s) for s in allowed_scopes}:
            decision.reason_codes.append("unknown_scope")
        if matrix["allowed_tenants"] == "generalized_only":
            if request.requested_tenants:
                decision.reason_codes.append("tenant_scope_not_allowed")
        elif not request.requested_tenants:
            # scope_owned purposes need a concrete tenant (or set) to operate on.
            decision.reason_codes.append("tenant_scope_required")

    def _check_data_classes(
        self,
        request: KyberIntelligenceRequest,
        matrix: dict[str, Any],
        decision: OlympusInternalDecision,
    ) -> None:
        allowed_defaults = {str(c) for c in matrix.get("default_data_classes", [])}
        for cls in request.requested_data_classes or []:
            cls_norm = _norm_enum_value(cls)
            if cls_norm.startswith(RAW_DATA_CLASS_PREFIX):
                # Raw data classes are never readable under a
                # ``requires_generalization`` purpose.
                if matrix["requires_generalization"]:
                    decision.reason_codes.append("raw_data_requires_generalization")
                    continue
            if matrix["allowed_tenants"] == "generalized_only":
                if not cls_norm.startswith(GENERALIZED_DATA_CLASS_PREFIX) \
                        and cls_norm not in allowed_defaults:
                    decision.reason_codes.append("data_class_not_allowed")
                    continue
            if cls_norm not in allowed_defaults:
                decision.reason_codes.append("data_class_not_allowed")

    def _check_grant_disclosure(
        self,
        request: KyberIntelligenceRequest,
        matrix: dict[str, Any],
        grant_records: Optional[list[Any]],
        decision: OlympusInternalDecision,
    ) -> None:
        def relevant(grant: Any) -> bool:
            tenant = getattr(grant, "tenant_id", None)
            if request.requested_tenants and tenant not in request.requested_tenants:
                return False
            if request.source_id and getattr(grant, "source_id", None) != request.source_id:
                return False
            if _norm_enum_value(getattr(grant, "status", "active")) != "active":
                return False
            if getattr(grant, "revoked_at", None) is not None:
                return False
            expires = getattr(grant, "expires_at", None)
            if expires:
                try:
                    from shared.common.common import parse_event_time
                    if parse_event_time(str(expires)) <= utc_now():
                        return False
                except Exception:
                    return False
            return True
        grants = [g for g in (grant_records or []) if relevant(g)]
        disclosure = _disclosure_classes(grants) if grants else frozenset()
        source_use = _source_use_classes(grants) if grants else frozenset()
        requested_classes = [_norm_enum_value(c) for c in request.requested_data_classes or []]
        raw_requested = any(c.startswith(RAW_DATA_CLASS_PREFIX) for c in requested_classes)
        cross_tenant = len(request.requested_tenants or []) > 1

        if not grants:
            # No grant confirmation available → fail closed on anything that
            # could expose tenant-identifiable raw material.
            if raw_requested:
                decision.reason_codes.append("raw_disclosure_not_confirmed")
            return

        if raw_requested and "olympus_baseline" not in source_use:
            decision.reason_codes.append("olympus_baseline_not_authorized")
        if cross_tenant and "cross_tenant_identifiable" not in disclosure:
            decision.reason_codes.append("cross_tenant_raw_not_authorized")
        for cls in requested_classes:
            if cls.startswith(GENERALIZED_DATA_CLASS_PREFIX) \
                    and "generalized_cross_tenant" not in disclosure:
                decision.reason_codes.append("generalized_disclosure_not_authorized")

    async def _persist(self, decision: OlympusInternalDecision) -> None:
        row = {
            "decision_id": decision.decision_id,
            "tenant_id": "",  # Olympus-internal, not tenant-scoped
            "allowed": decision.allowed,
            "disposition": decision.disposition,
            "reason_codes": list(decision.reason_codes),
            "source_grant_refs": list(decision.source_grant_refs),
            "consent_decision_refs": list(decision.consent_decision_refs),
            "permitted_uses": list(decision.permitted_uses),
            "permitted_derivations": list(decision.permitted_derivations),
            "permitted_learning": list(decision.permitted_learning),
            "permitted_disclosures": list(decision.permitted_disclosures),
            "retention": decision.retention,
            "deletion": decision.deletion,
            "survival": decision.survival,
            "evaluated_at": decision.evaluated_at,
            "effective_as_of": decision.effective_as_of,
            "policy_version": decision.policy_version,
            "evidence_refs": list(decision.evidence_refs),
            "requested_use": "olympus_internal_query",
            "actor": OLYMPUS_INTERNAL_ACTOR,
            "operator_id": decision.operator_id,
            "purpose": decision.purpose,
            "requested_scope": decision.requested_scope,
            "authorized_tenants": list(decision.authorized_tenants),
            "allowed_data_classes": list(decision.allowed_data_classes),
        }
        await self._decisions().record(row)


# Singleton.
olympus_internal_authority = OlympusInternalAuthority()


async def filter_graph_of_graphs_query(
    request: KyberIntelligenceRequest,
    candidate_refs: list[Any],
    *,
    grant_records: Optional[list[Any]] = None,
) -> tuple[list[Any], OlympusInternalDecision]:
    """Filter candidate artifact/tenant refs down to those the purpose authorizes.

    Pure filtering helper for the Kyber / data-plane seam (blueprint §36: no
    unrestricted cross-tenant browsing). ``candidate_refs`` items may be strings
    (treated as a generalized artifact ref, allowed only when the decision
    permits generalized classes) or dicts carrying ``artifact_ref`` / ``tenant_id``
    / ``data_class`` / ``generalized`` / ``tenant_identifiable``.
    """
    decision = await olympus_internal_authority.authorize(
        request, grant_records=grant_records
    )
    if not decision.allowed:
        return [], decision
    allowed_classes = set(decision.allowed_data_classes) or set(
        PURPOSE_SCOPE_MATRIX[decision.purpose]["default_data_classes"]
    )
    authorized_tenants = set(decision.authorized_tenants)
    purpose_mode = PURPOSE_SCOPE_MATRIX.get(decision.purpose, {}).get(
        "allowed_tenants", "generalized_only"
    )

    out: list[Any] = []
    for candidate in candidate_refs or []:
        if isinstance(candidate, str):
            if purpose_mode == "generalized_only":
                out.append(candidate)
            continue
        data_class = _norm_enum_value(candidate.get("data_class") or "")
        if not data_class:
            data_class = (
                "generalized.artifact"
                if candidate.get("generalized")
                else "raw.artifact"
            )
        tenant_id = candidate.get("tenant_id")
        tenant_identifiable = candidate.get("tenant_identifiable")
        if data_class not in allowed_classes and not data_class.startswith(
            GENERALIZED_DATA_CLASS_PREFIX
        ):
            continue
        if purpose_mode == "generalized_only":
            if tenant_id:
                continue
            if tenant_identifiable is not False and data_class.startswith(
                RAW_DATA_CLASS_PREFIX
            ):
                continue
            out.append(candidate)
        else:
            # scope_owned: tenant must be one the decision authorized.
            if tenant_id and tenant_id in authorized_tenants:
                out.append(candidate)
            elif not tenant_id and data_class.startswith(GENERALIZED_DATA_CLASS_PREFIX):
                out.append(candidate)
    return out, decision


__all__ = [
    "GENERALIZED_DATA_CLASS_PREFIX",
    "KyberIntelligenceRequest",
    "OLYMPUS_INTERNAL_ACTOR",
    "OLYMPUS_PURPOSES",
    "OlympusInternalAuthority",
    "OlympusInternalDecision",
    "PURPOSE_ALLOWLIST",
    "PURPOSE_SCOPE_MATRIX",
    "RAW_DATA_CLASS_PREFIX",
    "filter_graph_of_graphs_query",
    "olympus_internal_authority",
    "olympus_purpose_allowlist",
]
