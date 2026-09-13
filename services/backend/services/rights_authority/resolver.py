"""Effective Rights Resolver — canonical rights decision authority (blueprint §16/§4).

``EffectiveRightsResolver.resolve(...)`` composes the existing authorities
(DataRightsGrant via ``services.integrations.data_rights``, ConsentPolicyDecision
via ``services.policy``) with the P-A structured rights contracts and returns a
durable, tenant-scoped ``RightsDecision``. Every material request — allowed or
denied — is persisted to ``rights_decisions``.

Fail-closed doctrine (blueprint §1.5, §13):
  - no grant → DENIED ``no_grant``;
  - unknown requested-use family → DENIED ``unknown_use``;
  - missing/unknown structured authority → DENIED (never permissive default);
  - a historic ``as_of`` outside the grant's effective window → DENIED
    ``not_effective_as_of`` / ``grant_expired`` / ``grant_revoked``;
  - consent-based grants with no consent evidence on a consent-sensitive family →
    DENIED ``consent_required``.

CONSENT SEAM: the resolver accepts an optional async
``consent_evaluator(request, grant) -> ConsentPolicyDecision | None``. When wired,
the returned decision is honored (denied → ``consent_denied``; allowed → its
``policy_decision_id`` is recorded in ``consent_decision_refs``). When NOT wired,
a family listed in ``_CONSENT_SENSITIVE_FAMILIES`` on a grant whose
``legal_basis == "consent"`` is DENIED ``consent_required`` — a stored
``consent_basis`` string is self-asserted and is never treated as verified
consent, so a deployment that cannot verify subject consent fails closed rather
than trusting the grant row. Non-consent grants are unaffected (they are governed
by their structured rights, not this seam). The orchestrator injects a thin
adapter over ``services/consent/authority.py::evaluate_consent`` at wiring time so
real subject consent is verified against server-issued ``ConsentPolicyDecision``
records. ``resolve_structured_rights``-style resolution is delegated to the P-A
helpers (``effective_learning_authority``, ``derive_source_use_from_legacy``)
so the resolver never re-implements migration maps that P-A owns.
"""
from __future__ import annotations

import hashlib
from shared.common.common import parse_event_time, utc_now
from typing import Any, Awaitable, Callable, Optional

from services.integrations.data_rights.models import (
    DataRightsGrant,
    OlympusPurpose,
    RightsDecisionDisposition,
)
from services.integrations.data_rights.service import (
    data_rights_service,
    derive_source_use_from_legacy,
    effective_learning_authority,
)
from services.policy.contracts import ConsentPolicyDecision
from services.security.contracts import now_iso

from services.rights_authority.contracts import (
    RightsDecision,
    RightsDecisionRequest,
)
from services.rights_authority.repositories import (
    rights_decision_repository,
)

__all__ = [
    "EffectiveRightsResolver",
    "effective_rights_resolver",
    "configure_consent_evaluator",
    "decision_identity",
    "normalize_requested_use",
    "POLICY_VERSION",
]

POLICY_VERSION = "irrl-2"

# Canonical requested-use families recognised by the resolver. Anything else is
# an unknown use and is DENIED (never coerced into an allow/zero default).
_FAMILY_ALIASES: dict[str, str] = {
    # tenant source use
    "tenant_lake": "tenant_lake", "lake": "tenant_lake", "store": "tenant_lake",
    "write_tenant_lake": "tenant_lake",
    "tenant_graph": "tenant_graph", "graph": "tenant_graph",
    "write_tenant_graph": "tenant_graph", "mutate_graph": "tenant_graph",
    "tenant_insights": "tenant_insights", "insights": "tenant_insights",
    "use": "tenant_insights", "render_insights": "tenant_insights",
    # tenant-facing derived outputs
    "derive": "derive", "derivation": "derive", "create_derived": "derive",
    "export": "export", "tenant_export": "export", "export_data": "export",
    # learning / model governance
    "train": "contributed_model_training",
    "model_training": "contributed_model_training",
    "contributed_model_training": "contributed_model_training",
    "learn": "generalized_learning",
    "generalize": "generalized_learning",
    "generalization": "generalized_learning",
    "generalized_learning": "generalized_learning",
    "benchmark": "benchmarking", "benchmarking": "benchmarking",
    "resolver_calibration": "resolver_calibration",
    "ontology_learning": "ontology_learning",
    "schema_mapping_learning": "schema_mapping_learning",
    "inference": "inference",
    "tenant_adaptation": "tenant_adaptation",
    # olympus flows
    "baseline": "olympus_baseline", "olympus_baseline": "olympus_baseline",
    "olympus_internal": "olympus_internal", "internal_query": "olympus_internal",
    "olympus_internal_intelligence": "olympus_internal",
    # disclosure
    "disclose": "disclose", "disclosure": "disclose",
    "external_disclose": "disclose",
}

# requested-use family → short snake denial basis (reason_codes entry).
_FAMILY_DENY_TOKEN: dict[str, str] = {
    "tenant_lake": "tenant_lake",
    "tenant_graph": "tenant_graph",
    "tenant_insights": "tenant_insights",
    "derive": "derive",
    "export": "export",
    "contributed_model_training": "contributed_model_training",
    "generalized_learning": "generalized_learning",
    "benchmarking": "benchmarking",
    "resolver_calibration": "resolver_calibration",
    "ontology_learning": "ontology_learning",
    "schema_mapping_learning": "schema_mapping_learning",
    "inference": "inference",
    "tenant_adaptation": "tenant_adaptation",
    "olympus_baseline": "olympus_baseline_denied",
    "olympus_internal": "olympus_internal_denied",
    "disclose": "disclosure_denied",
}

# learning family → attribute on the effective LearningAuthority.
_LEARNING_ATTR: dict[str, str] = {
    "contributed_model_training": "contributed_model_training",
    "generalized_learning": "generalized_learning",
    "benchmarking": "benchmarking",
    "resolver_calibration": "resolver_calibration",
    "ontology_learning": "ontology_learning",
    "schema_mapping_learning": "schema_mapping_learning",
    "inference": "inference",
    "tenant_adaptation": "tenant_adaptation",
}

_LEARNING_DISCLOSURE_ATTRS: list[tuple[str, str]] = [
    ("inference", "inference"),
    ("tenant_adaptation", "tenant_adaptation"),
    ("generalized_learning", "generalized_learning"),
    ("resolver_calibration", "resolver_calibration"),
    ("ontology_learning", "ontology_learning"),
    ("schema_mapping_learning", "schema_mapping_learning"),
    ("benchmarking", "benchmarking"),
    ("contributed_model_training", "contributed_model_training"),
    ("olympus_internal_intelligence", "olympus_internal_intelligence"),
]

_SOURCE_USE_ATTRS: list[tuple[str, str, str]] = [
    # (permitted token, structured SourceUseAuthority attr, legacy grant attr)
    ("tenant_lake", "tenant_lake", "tenant_lake_allowed"),
    ("tenant_graph", "tenant_graph", "tenant_graph_allowed"),
    ("tenant_insights", "tenant_insights", "tenant_insights_allowed"),
    ("olympus_baseline", "olympus_baseline", "olympus_baseline_allowed"),
    ("cross_tenant_aggregate", "cross_tenant_aggregate", "cross_tenant_aggregate_allowed"),
    ("commercial_reuse", "commercial_reuse", "commercial_reuse_allowed"),
]

_TENANT_LICENSE_ATTRS: list[tuple[str, str]] = [
    ("view", "view"),
    ("use", "use"),
    ("reproduce", "reproduce"),
    ("integrate", "integrate"),
    ("export", "export"),
    ("internal_commercial_use", "internal_commercial_use"),
]

_DISCLOSURE_ATTRS: list[tuple[str, str]] = [
    ("tenant_internal", "tenant_internal"),
    ("olympus_internal", "olympus_internal"),
    ("cross_tenant_identifiable", "cross_tenant_identifiable"),
    ("external_identifiable", "external_identifiable"),
    ("generalized_cross_tenant", "generalized_cross_tenant"),
    ("generalized_external", "generalized_external"),
]

# Families that depend on subject-consent evidence when the grant is consent-based.
_CONSENT_SENSITIVE_FAMILIES: frozenset[str] = frozenset({
    "export", "disclose", "contributed_model_training", "generalized_learning",
    "benchmarking", "olympus_internal", "olympus_baseline",
})

_ACTIVE_GRANT_STATUS = frozenset({"active"})


def _flag(obj: Any, name: str, default: bool = False) -> bool:
    """Read a boolean flag off a pydantic model, dict, or namespace (fail closed)."""
    if obj is None:
        return bool(default)
    if isinstance(obj, dict):
        return bool(obj.get(name, default))
    return bool(getattr(obj, name, default))


def _as_dt(value: Optional[str]) -> Optional[Any]:
    """Parse an ISO instant via the shared temporal parser (aware UTC, None-safe)."""
    return parse_event_time(value)


def _grant_status(grant: DataRightsGrant) -> str:
    status = getattr(grant, "status", None)
    if status is None:
        return ""
    if isinstance(status, str):
        return status.strip().lower()
    return str(getattr(status, "value", status)).strip().lower()


def _olympus_purpose_tokens() -> set[str]:
    """Normalized Olympus internal purpose vocabulary (blueprint §7)."""
    tokens: set[str] = set()
    for member in OlympusPurpose:
        tokens.add(str(member.value).lower())
        tokens.add(str(member.name).lower())
    return tokens


_OLYMPUS_PURPOSE_TOKENS = _olympus_purpose_tokens()


def normalize_requested_use(requested_use: Optional[str]) -> Optional[str]:
    """Map a requested-use token to its canonical family, else None (unknown)."""
    if not requested_use:
        return None
    return _FAMILY_ALIASES.get(str(requested_use).strip().lower())


def decision_identity(
    *,
    tenant_id: str,
    actor: str,
    purpose: str,
    artifact: Optional[str],
    requested_use: str,
    destination: str,
    source_id: str = "",
    governing_grant_ref: str = "",
    subject_ref: str = "",
    policy_version: str = POLICY_VERSION,
    as_of: Optional[str] = None,
) -> str:
    """Deterministic decision identity (blueprint §17).

    Reproducible from: tenant + actor + purpose + artifact + requested_use +
    destination + governing source/grant + subject + policy version + as-of time.
    Identical inputs must never yield conflicting decisions; source/grant
    authority is part of the identity so two otherwise-equal source requests
    cannot replay one another.
    """
    material = "\0".join([
        tenant_id or "",
        actor or "",
        purpose or "",
        artifact or "",
        requested_use or "",
        destination or "",
        source_id or "",
        governing_grant_ref or "",
        subject_ref or "",
        policy_version or "",
        as_of or "",
    ])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"rdid_{digest[:64]}"


def _ownership_class(grant: DataRightsGrant, family: str, artifact_class: Optional[str]) -> str:
    """Classify the governed material (blueprint §2 taxonomy).

    Heuristic over source/connector class + requested family + artifact class; the
    resolver records the classification on the decision so downstream consumers
    never guess ownership.
    """
    connector = str(getattr(grant, "connector_class", "") or "").lower()
    if family == "generalized_learning" or family == "benchmarking":
        return "generalized_knowledge"
    if artifact_class:
        ac = artifact_class.lower()
        generated_markers = (
            "generated", "derived", "model_derived", "prediction", "recommendation",
            "risk", "fraud", "relationship", "profile", "episode", "journey",
            "attribution", "outcome", "anomaly", "cluster", "inference",
            "classification", "finding", "value_projection", "graph_feature",
        )
        if any(marker in ac for marker in generated_markers):
            return "aether_generated_intelligence"
        if "generalized" in ac or "aggregate" in ac:
            return "generalized_knowledge"
    if family == "derive":
        return "aether_generated_intelligence"
    if connector in ("olympus_provider", "olympus"):
        return "contributed_source"
    return "contributed_source"


class EffectiveRightsResolver:
    """Canonical rights decision authority (blueprint §16)."""

    def __init__(
        self,
        *,
        grant_loader: Optional[
            Callable[[str, str], Awaitable[Optional[DataRightsGrant]]]
        ] = None,
        consent_evaluator: Optional[
            Callable[[RightsDecisionRequest, DataRightsGrant], Awaitable[Optional[ConsentPolicyDecision]]]
        ] = None,
        decision_repository: Any = None,
    ) -> None:
        self._grant_loader = grant_loader or self._default_grant_loader
        self._consent_evaluator = consent_evaluator
        self._repo = decision_repository or rights_decision_repository

    # ── Public API ──────────────────────────────────────────────────────────

    async def resolve(
        self,
        tenant: str,
        source: str,
        artifact: str,
        actor: str,
        requested_use: str,
        purpose: str,
        destination: str,
        subject_ref: Optional[str] = None,
        as_of: Optional[str] = None,
    ) -> RightsDecision:
        """Positional resolver (blueprint §16 ``resolve_effective_rights``)."""
        return await self.resolve_request(
            RightsDecisionRequest(
                tenant_id=tenant,
                source_id=source,
                artifact_ref=artifact,
                actor=actor,
                requested_use=requested_use,
                purpose=purpose,
                destination=destination,
                subject_ref=subject_ref,
                as_of=as_of,
            )
        )

    async def resolve_request(
        self,
        request: RightsDecisionRequest,
        *,
        replay_recorded: bool = True,
    ) -> RightsDecision:
        """Resolve a ``RightsDecisionRequest`` into a durable ``RightsDecision``.

        ``replay_recorded`` enables historical decision idempotency (blueprint
        §17): when a recorded decision exists for the same §17 identity and the
        request supplies an immutable ``as_of`` timestamp, the recorded
        snapshot is returned. Live requests always re-evaluate current grant and
        consent state before any durable decision is returned.
        """
        evaluated_at = now_iso()
        effective_as_of = request.as_of or evaluated_at
        identity = decision_identity(
            tenant_id=request.tenant_id,
            actor=request.actor,
            purpose=request.purpose,
            artifact=request.artifact_ref,
            requested_use=request.requested_use,
            destination=request.destination,
            source_id=request.source_id,
            subject_ref=request.subject_ref or "",
            policy_version=POLICY_VERSION,
            as_of=request.as_of,
        )

        grant = await self._grant_loader(request.tenant_id, request.source_id)
        if grant is None:
            return await self._record(
                request, identity,
                self._decision(
                    request,
                    tenant_id=request.tenant_id,
                    allowed=False,
                    disposition=RightsDecisionDisposition.DENIED,
                    reason_codes=["no_grant"],
                    source_grant_refs=[],
                    ownership_class=None,
                    evaluated_at=evaluated_at,
                    effective_as_of=effective_as_of,
                ),
            )

        temporal = self._temporal_denial(grant, request.as_of, evaluated_at)
        if temporal:
            return await self._record(
                request, identity,
                self._decision(
                    request,
                    tenant_id=request.tenant_id,
                    allowed=False,
                    disposition=RightsDecisionDisposition.DENIED,
                    reason_codes=temporal,
                    source_grant_refs=[grant.data_rights_grant_id],
                    ownership_class=_ownership_class(
                        grant, normalize_requested_use(request.requested_use) or "",
                        request.artifact_class,
                    ),
                    evaluated_at=evaluated_at,
                    effective_as_of=effective_as_of,
                ),
            )

        # Historical decisions are immutable snapshots.  A live request must
        # always re-evaluate current consent/grant state (revocations can occur
        # after the original decision was recorded).
        if replay_recorded and request.as_of is not None:
            prior = await self._repo.find_by_identity(request.tenant_id, identity)
            if prior is not None:
                return RightsDecision(**prior)

        family = normalize_requested_use(request.requested_use)
        if family is None:
            return await self._record(
                request, identity,
                self._decision(
                    request,
                    tenant_id=request.tenant_id,
                    allowed=False,
                    disposition=RightsDecisionDisposition.DENIED,
                    reason_codes=["unknown_use"],
                    source_grant_refs=[grant.data_rights_grant_id],
                    ownership_class=_ownership_class(grant, "", request.artifact_class),
                    evaluated_at=evaluated_at,
                    effective_as_of=effective_as_of,
                ),
            )

        blocked, consent_reasons, consent_refs, consent_evidence = (
            await self._consent_blocked(request, grant, family)
        )
        if blocked:
            return await self._record(
                request, identity,
                self._decision(
                    request,
                    tenant_id=request.tenant_id,
                    allowed=False,
                    disposition=RightsDecisionDisposition.DENIED,
                    reason_codes=consent_reasons,
                    source_grant_refs=[grant.data_rights_grant_id],
                    consent_decision_refs=consent_refs,
                    ownership_class=_ownership_class(grant, family, request.artifact_class),
                    evidence_extra=consent_evidence,
                    evaluated_at=evaluated_at,
                    effective_as_of=effective_as_of,
                ),
            )

        allowed, reasons = self._family_allowed(request, grant, family)
        ownership = _ownership_class(grant, family, request.artifact_class)
        permitted_uses, permitted_derivations, permitted_learning, permitted_disclosures = (
            self._permitted_lists(grant)
        )
        # Include the requested family in the advisory lists when granted.
        if allowed:
            permitted_uses = self._append_granted_use(permitted_uses, family, grant)
            permitted_learning = self._append_granted_learning(permitted_learning, family)

        retention, deletion, survival = self._lifecycle_hints(ownership)

        decision = self._decision(
            request,
            tenant_id=request.tenant_id,
            allowed=allowed,
            disposition=(
                RightsDecisionDisposition.ALLOWED
                if allowed else RightsDecisionDisposition.DENIED
            ),
            reason_codes=reasons,
            source_grant_refs=[grant.data_rights_grant_id],
            consent_decision_refs=consent_refs,
            ownership_class=ownership,
            permitted_uses=permitted_uses,
            permitted_derivations=permitted_derivations,
            permitted_learning=permitted_learning,
            permitted_disclosures=permitted_disclosures,
            retention=retention,
            deletion=deletion,
            survival=survival,
            evidence_extra=consent_evidence,
            evaluated_at=evaluated_at,
            effective_as_of=effective_as_of,
        )
        return await self._record(request, identity, decision)

    # ── Decision helpers ────────────────────────────────────────────────────

    def _decision(self, request, **kwargs) -> RightsDecision:
        return RightsDecision(
            tenant_id=kwargs.pop("tenant_id", request.tenant_id),
            allowed=kwargs.pop("allowed"),
            disposition=kwargs.pop("disposition"),
            reason_codes=kwargs.pop("reason_codes", []),
            source_grant_refs=kwargs.pop("source_grant_refs", []),
            consent_decision_refs=kwargs.pop("consent_decision_refs", []),
            ownership_class=kwargs.pop("ownership_class", None),
            permitted_uses=kwargs.pop("permitted_uses", []),
            permitted_derivations=kwargs.pop("permitted_derivations", []),
            permitted_learning=kwargs.pop("permitted_learning", []),
            permitted_disclosures=kwargs.pop("permitted_disclosures", []),
            retention=kwargs.pop("retention", None),
            deletion=kwargs.pop("deletion", None),
            survival=kwargs.pop("survival", None),
            evaluated_at=kwargs.pop("evaluated_at", now_iso()),
            effective_as_of=kwargs.pop("effective_as_of", None),
            policy_version=kwargs.pop("policy_version", POLICY_VERSION),
            evidence_refs=kwargs.pop("evidence_extra", []),
        )

    async def _record(self, request, identity, decision) -> RightsDecision:
        await self._repo.record(decision, identity_key=identity)
        return decision

    async def _default_grant_loader(
        self, tenant_id: str, source_id: str,
    ) -> Optional[DataRightsGrant]:
        """Load the governing grant for (tenant, source).

        ``DataRightsService`` keys grants by grant id; summaries expose source_id.
        ``get_grant`` returns the pydantic ``DataRightsGrant`` (which carries any
        P-A structured components); ``get_grant_structured`` returns only the dict
        view and is therefore not used for authority reads.
        """
        summaries = await data_rights_service.list_grants(tenant_id=tenant_id)
        for summary in summaries:
            if str(getattr(summary, "source_id", "") or "") != source_id:
                continue
            grant_id = str(getattr(summary, "data_rights_grant_id", "") or "")
            if not grant_id:
                continue
            grant = await data_rights_service.get_grant(grant_id)
            if grant is not None and str(getattr(grant, "tenant_id", "") or "") == tenant_id:
                return grant
        return None

    # ── Grant-state gates (fail closed) ─────────────────────────────────────

    def _temporal_denial(
        self, grant: DataRightsGrant, as_of: Optional[str], evaluated_at: str,
    ) -> list[str]:
        status = _grant_status(grant)
        revoked_at = getattr(grant, "revoked_at", None)
        expires_at = getattr(grant, "expires_at", None)
        granted_at = getattr(grant, "granted_at", None)

        if as_of is None:
            if revoked_at is not None or status == "revoked":
                return ["grant_revoked"]
            if status == "expired":
                return ["grant_expired"]
            if status not in _ACTIVE_GRANT_STATUS and status not in ("", "unknown"):
                return ["grant_not_active"]
            expires = _as_dt(expires_at)
            if expires is not None and expires <= utc_now():
                return ["grant_expired"]
            return []

        as_of_dt = _as_dt(as_of)
        if as_of_dt is None:
            # Unparseable historical as-of → deny rather than assume a window.
            return ["not_effective_as_of"]
        revoked = _as_dt(revoked_at)
        if revoked is not None and as_of_dt >= revoked:
            return ["grant_revoked"]
        expires = _as_dt(expires_at)
        if expires is not None and as_of_dt > expires:
            return ["grant_expired"]
        granted = _as_dt(granted_at)
        if granted is not None and as_of_dt < granted:
            return ["not_effective_as_of"]
        return []

    # ── Consent seam ────────────────────────────────────────────────────────

    async def _consent_blocked(
        self,
        request: RightsDecisionRequest,
        grant: DataRightsGrant,
        family: str,
    ) -> tuple[bool, list[str], list[str], list[str]]:
        if family not in _CONSENT_SENSITIVE_FAMILIES:
            return False, [], [], []

        decision: Optional[ConsentPolicyDecision] = None
        if self._consent_evaluator is not None:
            decision = await self._consent_evaluator(request, grant)

        if decision is not None:
            if getattr(decision, "allowed", False) is False:
                return (
                    True,
                    ["consent_denied"],
                    [decision.policy_decision_id],
                    [],
                )
            return False, [], [decision.policy_decision_id], []

        legal = str(getattr(grant, "legal_basis", "") or "").strip().lower()
        if legal != "consent":
            return False, [], [], []
        basis = getattr(grant, "consent_basis", None)
        if basis is None:
            return True, ["consent_required"], [], []
        # A self-asserted ``consent_basis`` string is NOT verifiable consent. A
        # consent-sensitive family is only satisfied by a server-issued
        # ConsentPolicyDecision / consent receipt that the wired
        # ``consent_evaluator`` confirms (its ``policy_decision_id`` is recorded
        # in ``consent_decision_refs`` above). Without a verifiable decision, fail
        # closed rather than trust the stored string (blueprint §1.5 / §13).
        return (
            True,
            ["consent_required"],
            [],
            [f"consent_basis:{basis}:unverified"],
        )

    # ── Family evaluation ───────────────────────────────────────────────────

    def _family_allowed(
        self, request: RightsDecisionRequest, grant: DataRightsGrant, family: str,
    ) -> tuple[bool, list[str]]:
        deny_token = _FAMILY_DENY_TOKEN.get(family, "denied")
        if family == "olympus_internal":
            return self._evaluate_olympus_internal(request, grant, deny_token)
        if family == "olympus_baseline":
            allowed = self._source_use_flag(
                grant, "olympus_baseline", "olympus_baseline_allowed"
            )
            return allowed, ([] if allowed else [deny_token])
        if family == "export":
            allowed = self._tenant_export_allowed(grant)
            return allowed, ([] if allowed else [deny_token])
        if family in {"tenant_lake", "tenant_graph", "tenant_insights"}:
            structured_attr, legacy_attr = {
                "tenant_lake": ("tenant_lake", "tenant_lake_allowed"),
                "tenant_graph": ("tenant_graph", "tenant_graph_allowed"),
                "tenant_insights": ("tenant_insights", "tenant_insights_allowed"),
            }[family]
            allowed = self._source_use_flag(grant, structured_attr, legacy_attr)
            return allowed, ([] if allowed else [deny_token])
        if family == "derive":
            allowed = self._source_use_flag(
                grant, "tenant_insights", "tenant_insights_allowed"
            )
            generated = self._generated_outputs(grant)
            if generated is not None:
                tenant_license = getattr(generated, "tenant_license", None)
                if _flag(tenant_license, "use", False):
                    allowed = True
            return allowed, ([] if allowed else [deny_token])
        if family in _LEARNING_ATTR:
            allowed = _flag(
                self._effective_learning(grant), _LEARNING_ATTR[family], False
            )
            return allowed, ([] if allowed else [deny_token])
        if family == "disclose":
            return self._evaluate_disclose(request, grant, deny_token)
        return False, [deny_token]

    def _evaluate_olympus_internal(
        self, request: RightsDecisionRequest, grant: DataRightsGrant, deny_token: str,
    ) -> tuple[bool, list[str]]:
        purpose = (request.purpose or "").strip().lower()
        if not purpose or purpose not in _OLYMPUS_PURPOSE_TOKENS:
            return False, ["olympus_purpose_not_allowed"]
        # Authorized by either learning/intelligence authority or olympus
        # generated-output rights (blueprint §7 purpose-bound).
        learning = self._effective_learning(grant)
        intelligence_ok = (
            _flag(learning, "olympus_internal_intelligence", False)
            or self._source_use_flag(grant, "olympus_baseline", "olympus_baseline_allowed")
        )
        generated = self._generated_outputs(grant)
        olympus_rights = getattr(generated, "olympus", None)
        olympus_ok = _flag(olympus_rights, "internal_research", False) or _flag(
            olympus_rights, "platform_improvement", False
        )
        if not (intelligence_ok or olympus_ok):
            return False, [deny_token]
        disclosure_ok = self._disclosure_flag(grant, "olympus_internal")
        if not disclosure_ok:
            return False, [deny_token]
        return True, []

    def _evaluate_disclose(
        self, request: RightsDecisionRequest, grant: DataRightsGrant, deny_token: str,
    ) -> tuple[bool, list[str]]:
        destination = (request.destination or "").strip().lower()
        if "external" in destination:
            allowed = self._disclosure_flag(grant, "external_identifiable") or (
                self._disclosure_flag(grant, "generalized_external")
                and "generalized" in (request.artifact_class or "").lower()
            )
            return allowed, ([] if allowed else [deny_token])
        if "cross_tenant" in destination or "aggregate" in destination:
            allowed = (
                self._disclosure_flag(grant, "cross_tenant_identifiable")
                or self._disclosure_flag(grant, "generalized_cross_tenant")
            )
            return allowed, ([] if allowed else [deny_token])
        if "olympus" in destination:
            allowed = self._disclosure_flag(grant, "olympus_internal")
            return allowed, ([] if allowed else [deny_token])
        # tenant-internal default boundary
        if not destination or destination in {"tenant", "internal", "tenant_internal"}:
            allowed = self._disclosure_flag(grant, "tenant_internal")
            return allowed, ([] if allowed else [deny_token])
        return False, [deny_token]

    # ── Structured/legacy authority access (fail closed) ───────────────────

    def _source_use_flag(
        self, grant: DataRightsGrant, structured_attr: str, legacy_attr: str,
    ) -> bool:
        source_use = getattr(grant, "source_use", None)
        if source_use is not None:
            return _flag(source_use, structured_attr, False)
        # Structured source_use absent → derive 1:1 from legacy booleans via the
        # P-A migration helper (never broadens past the legacy grant).
        derived = derive_source_use_from_legacy(
            tenant_lake_allowed=getattr(grant, "tenant_lake_allowed", False),
            tenant_graph_allowed=getattr(grant, "tenant_graph_allowed", False),
            tenant_insights_allowed=getattr(grant, "tenant_insights_allowed", False),
            olympus_baseline_allowed=getattr(grant, "olympus_baseline_allowed", False),
            cross_tenant_aggregate_allowed=getattr(grant, "cross_tenant_aggregate_allowed", False),
            commercial_reuse_allowed=getattr(grant, "commercial_reuse_allowed", False),
        )
        return _flag(derived, structured_attr, False) or _flag(grant, legacy_attr, False)

    def _effective_learning(self, grant: DataRightsGrant):
        """Effective LearningAuthority (structured if present, else P-A migration)."""
        learning = getattr(grant, "learning_authority", None)
        if learning is not None:
            return learning
        try:
            return effective_learning_authority(grant)
        except Exception:  # pragma: no cover - P-A migration helper
            return None

    def _generated_outputs(self, grant: DataRightsGrant):
        """Structured GeneratedOutputRights only when explicitly present (fail closed)."""
        return getattr(grant, "generated_output_rights", None)

    def _effective_disclosure(self, grant: DataRightsGrant):
        disclosure = getattr(grant, "disclosure_authority", None)
        if disclosure is not None:
            return disclosure
        return None

    def _disclosure_flag(self, grant: DataRightsGrant, attr: str) -> bool:
        disclosure = self._effective_disclosure(grant)
        if disclosure is not None:
            return _flag(disclosure, attr, False)
        return False

    def _tenant_export_allowed(self, grant: DataRightsGrant) -> bool:
        generated = self._generated_outputs(grant)
        if generated is None:
            return False
        tenant_license = getattr(generated, "tenant_license", None)
        return _flag(tenant_license, "export", False)

    def _append_granted_use(
        self, permitted_uses: list[str], family: str, grant: DataRightsGrant,
    ) -> list[str]:
        granted = set(permitted_uses)
        # Map the granted family back to its outward token(s).
        if family == "export":
            granted.add("export")
            granted.add("tenant_export")
        elif family == "tenant_export":
            granted.add("export")
        elif family == "derive":
            granted.add("derive")
        elif family == "olympus_internal":
            granted.add("olympus_internal")
        elif family == "olympus_baseline":
            granted.add("olympus_baseline")
        elif family in {"tenant_lake", "tenant_graph", "tenant_insights"}:
            granted.add(family)
        return sorted(granted)

    def _append_granted_learning(
        self, permitted_learning: list[str], family: str,
    ) -> list[str]:
        if family in _LEARNING_ATTR:
            return list(dict.fromkeys([*permitted_learning, family]))
        return permitted_learning

    def _permitted_lists(
        self, grant: DataRightsGrant,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        uses: list[str] = []
        for token, structured_attr, legacy_attr in _SOURCE_USE_ATTRS:
            if self._source_use_flag(grant, structured_attr, legacy_attr):
                uses.append(token)
        if self._tenant_export_allowed(grant):
            uses.append("export")

        derivations: list[str] = []
        generated = self._generated_outputs(grant)
        if generated is not None:
            tenant_license = getattr(generated, "tenant_license", None)
            for token, attr in _TENANT_LICENSE_ATTRS:
                if _flag(tenant_license, attr, False):
                    derivations.append(token)
        else:
            if self._source_use_flag(grant, "tenant_insights", "tenant_insights_allowed"):
                derivations.append("derive")

        learning = self._effective_learning(grant)
        permitted_learning = [
            token for token, attr in _LEARNING_DISCLOSURE_ATTRS
            if _flag(learning, attr, False)
        ]

        disclosure = self._effective_disclosure(grant)
        permitted_disclosures = [
            token for token, attr in _DISCLOSURE_ATTRS
            if disclosure is not None and _flag(disclosure, attr, False)
        ]

        return uses, derivations, permitted_learning, permitted_disclosures

    def _lifecycle_hints(self, ownership: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Advisory lifecycle strings recorded on the decision.

        Retention/deletion/survival *authority* resolution (blueprint §9) is a
        later phase; the resolver records conservative placeholders so consumers
        have a non-empty, non-permissive signal.
        """
        if ownership == "generalized_knowledge":
            return "governed", None, "conditional_generalized_derivatives"
        if ownership == "aether_generated_intelligence":
            return "governed", "recompute_or_delete", "tenant_retains_exported_outputs"
        return "per_policy", "delete_by_policy", None


# ── Consent seam default (server consent authority) ─────────────────────────

async def _server_consent_evaluator(
    request: RightsDecisionRequest,
    grant: DataRightsGrant,
) -> Optional[ConsentPolicyDecision]:
    """Lazy default consent evaluator for the module singleton.

    Defers to ``services.rights_authority.consent.default_consent_evaluator``
    (a thin adapter over ``services/consent/authority.py::evaluate_consent``).
    The import is lazy so ``main.py`` and bare module imports never pay for the
    consent authority until a resolution actually needs it, and any failure here
    returns ``None`` so the resolver's own fail-closed consent branch (DENIED
    ``consent_required``) governs instead of an exception escaping ``resolve``.
    """
    try:
        from services.rights_authority.consent import default_consent_evaluator

        return await default_consent_evaluator(request, grant)
    except Exception:  # pragma: no cover - fail-safe outer belt
        return None


def configure_consent_evaluator(
    evaluator: Optional[
        Callable[[RightsDecisionRequest, DataRightsGrant], Awaitable[Optional[ConsentPolicyDecision]]]
    ],
    *,
    resolver: Optional[EffectiveRightsResolver] = None,
) -> None:
    """Install/clear the consent evaluator on the module singleton.

    ``evaluator`` follows the resolver seam signature
    ``async (request, grant) -> ConsentPolicyDecision | None``; pass ``None`` to
    return the singleton to the built-in fail-closed (no-evaluator) behavior.
    Bare ``EffectiveRightsResolver()`` construction is untouched — an instance's
    seam is only changed when its own ``consent_evaluator`` was supplied or a
    caller explicitly wires one here.
    """
    target = resolver if resolver is not None else effective_rights_resolver
    target._consent_evaluator = evaluator


# ── Module-level singleton (mirrors data_rights / policy / security) ──────────
# Wired to the server consent authority by default so the live tenant surface
# (routes.py) verifies subject consent through ``evaluate_consent`` instead of
# the self-asserted ``consent_basis:...:unverified`` fallback. Bare
# ``EffectiveRightsResolver()`` instances stay evaluator-less (fail closed).
effective_rights_resolver = EffectiveRightsResolver(
    consent_evaluator=_server_consent_evaluator,
)
