"""Aether — Rights Authority: Generalization Gateway.

Stream P-B2 (part 2) of the ``rights_irrl`` canonical authority. This module
implements blueprint §6 / §28–§31 / §32 / §78 : the Generalization Gateway, the
runtime adapter owned by ``rights_irrl`` that governs whether tenant-derived
intelligence may be generalized (de-identified, aggregated, coarse-grained) and
then travel to destinations such as the Olympus graph, platform learning,
benchmarking, or contributed model training.

Doctrine
--------
* Fail closed. Unknown destination / use / evidence / authority → deny. Unknowns
  are never converted into zeros or "allow".
* No tenant-derived intelligence enters generalized Olympus knowledge except via
  :meth:`GeneralizationGateway.is_eligible_for_olympus_knowledge` (blueprint §32
  / §78 exit).
* This gateway is an *adapter over* the canonical authorities (``DataRightsGrant``
  nested rights components, ``ConsentPolicyDecision``, ``RightsDecision``). It is
  NOT a parallel graph or a second rights registry.

The parallel streams P-A (``services.integrations.data_rights`` structured grant
contracts) and P-B1 (``services.rights_authority`` contracts/repositories/
resolver) may not yet exist when this module is imported. All access to their
symbols therefore goes through the module-level *accessor* functions
(``_pa_models`` / ``_pb1_repositories`` / ``_pb1_resolver``) which are resolved
lazily at call time so tests can inject faithful stand-ins and the orchestrator
can integrate P-A → P-B1 → this stream without edit.

Persistence rides the canonical repository pattern (BaseRepository in-memory on
AETHER_ENV=local, Postgres otherwise); never a bare dict.
"""
from __future__ import annotations

import hashlib
import importlib
import uuid
from enum import Enum
from typing import Any, Callable, Literal, Optional, Union

from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from services.security.repositories import _ScopedRepo

logger = get_logger("aether.rights_irrl.generalization")

GENERALIZATION_POLICY_VERSION = "irrl-2"

# Blueprint §31 / §32 default minimum population for a cohort before a
# generalized artifact may be considered non-re-identifiable. Anything below is
# denied unless explicitly satisfied by caller-provided evidence.
MINIMUM_POPULATION_THRESHOLD = 25

# Re-identification risk vocabulary (snake_case, matching RightsDecision uses).
REIDENTIFICATION_RISK_VALUES = ("none", "low", "medium", "high")

# Generalization request destinations (blueprint §28).
GENERALIZATION_DESTINATIONS: tuple[str, ...] = (
    "olympus_graph",
    "platform_learning",
    "benchmark",
    "model_training",
)

# Registered transformation vocabulary (blueprint §6). All are registered and
# evidence-linked in TRANSFORMATION_REGISTRY.
GENERALIZATION_TRANSFORMATION_KINDS: tuple[str, ...] = (
    "pii_strip",
    "tenant_identifier_removal",
    "tenant_metadata_strip",
    "subject_pseudonymization",
    "bucketing",
    "cohort_thresholding",
    "k_anonymity_minimum_population",
    "distribution_aggregation",
    "outlier_suppression",
    "edge_abstraction",
    "feature_coarsening",
    "temporal_coarsening",
    "geographic_coarsening",
    "sensitivity_reduction",
)

# Transformations that directly de-risk tenant identifiability / PII presence.
_IDENTIFIER_TRANSFORMATIONS = frozenset(
    {"pii_strip", "tenant_identifier_removal", "tenant_metadata_strip",
     "subject_pseudonymization"}
)
# Kinds that remove / rewrite subject-level PII (blueprint §6 de-identification).
_PII_KINDS = frozenset({"pii_strip", "subject_pseudonymization"})
_POPULATION_TRANSFORMATIONS = frozenset(
    {"bucketing", "cohort_thresholding", "k_anonymity_minimum_population",
     "distribution_aggregation", "outlier_suppression", "edge_abstraction",
     "feature_coarsening", "temporal_coarsening", "geographic_coarsening",
     "sensitivity_reduction"}
)

# Per-destination authority requirements over the structured grant components.
# ``learning``: any of these effective learning classes is sufficient.
# ``source_use``: olympus-level source-use authority required to take material
#   out of pure tenant scope for platform destinations.
# ``disclosure``: disclosure class that must be permitted for the destination.
DESTINATION_AUTHORITY_REQUIREMENTS: dict[str, dict[str, frozenset[str]]] = {
    "olympus_graph": {
        "learning": frozenset({"generalized_learning", "olympus_internal_intelligence"}),
        "source_use": frozenset({"olympus_baseline", "cross_tenant_aggregate"}),
        "disclosure": frozenset({"generalized_cross_tenant"}),
    },
    "platform_learning": {
        "learning": frozenset({
            "generalized_learning", "resolver_calibration", "ontology_learning",
            "schema_mapping_learning", "benchmarking",
        }),
        "source_use": frozenset({"olympus_baseline", "cross_tenant_aggregate"}),
        "disclosure": frozenset({"generalized_cross_tenant"}),
    },
    "benchmark": {
        "learning": frozenset({"benchmarking", "generalized_learning"}),
        "source_use": frozenset({"olympus_baseline", "cross_tenant_aggregate"}),
        "disclosure": frozenset({"generalized_cross_tenant"}),
    },
    "model_training": {
        # contributed_model_training must be EXPLICIT (never inferred).
        "learning": frozenset({"contributed_model_training"}),
        "source_use": frozenset(),
        "disclosure": frozenset({"generalized_cross_tenant", "generalized_external"}),
    },
}

# Derivation classes that are tenant-reconstructable and therefore require the
# strictest generalization evidence (RightsDerivationClass values, snake_case).
_STRICT_DERIVATION_CLASSES = frozenset({"model_derived", "tenant_identifiable_derivative"})


# ═══════════════════════════════════════════════════════════════════════════
# Parallel-stream accessors (P-A / P-B1) — resolved lazily at call time.
# ═══════════════════════════════════════════════════════════════════════════

def _pa_models():
    """P-A: ``services.integrations.data_rights.models`` structured contracts."""
    return importlib.import_module("services.integrations.data_rights.models")


def _pb1_repositories():
    """P-B1: ``services.rights_authority.repositories`` singleton stores."""
    return importlib.import_module("services.rights_authority.repositories")


def _pb1_resolver():
    """P-B1: ``services.rights_authority.resolver`` effective rights resolver."""
    return importlib.import_module("services.rights_authority.resolver")


def _pb1_contracts():
    """P-B1: ``services.rights_authority.contracts`` RightsDecision surface."""
    return importlib.import_module("services.rights_authority.contracts")


def _norm_enum_value(value: Any) -> str:
    """Normalise an enum member / raw value to canonical lowercase snake.

    P-A declares snake_case *values*; members may be UPPER. Never guessing an
    unknown into an allowed value — this only normalises spelling.
    """
    if isinstance(value, Enum):
        value = value.value
    return str(value).strip().lower()


def _enum_value_set(enum_cls: Any) -> frozenset[str]:
    """All values of a (possibly absent / partial) P-A enum class as snake set."""
    try:
        return frozenset(_norm_enum_value(m) for m in enum_cls)
    except Exception:  # pragma: no cover — defensive against enum shape drift
        return frozenset()


def _grant_learning_classes(grant: Any) -> frozenset[str]:
    """Effective learning classes permitted by a grant (fail-closed).

    Prefers the canonical P-A ``effective_learning_authority`` helper when the
    parallel module exposes it; falls back to reading explicit True fields off a
    structured ``grant.learning_authority`` component; honours the legacy
    ``model_training_allowed`` → ``contributed_model_training`` migration map
    without broadening. Unknown components contribute nothing.
    """
    models = None
    try:
        models = _pa_models()
    except Exception:
        models = None
    if models is not None and hasattr(models, "effective_learning_authority"):
        try:
            authority = models.effective_learning_authority(grant)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("effective_learning_authority(grant) failed: %s", exc)
            authority = getattr(grant, "learning_authority", None)
        if authority is not None:
            return _true_component_fields(authority)
    component = getattr(grant, "learning_authority", None)
    if component is not None:
        return _true_component_fields(component)
    # Legacy migration: model_training_allowed=True maps to contributed_model_training.
    if getattr(grant, "model_training_allowed", False) is True:
        return frozenset({"contributed_model_training"})
    return frozenset()


def _grant_disclosure_classes(grant: Any) -> frozenset[str]:
    component = getattr(grant, "disclosure_authority", None)
    if component is not None:
        return _true_component_fields(component)
    return frozenset()


def _grant_source_use_classes(grant: Any) -> frozenset[str]:
    component = getattr(grant, "source_use", None)
    if component is not None:
        return _true_component_fields(component)
    return frozenset()


def _true_component_fields(component: Any) -> frozenset[str]:
    """Collect the *explicit True* boolean fields of a nested rights component.

    Fields on a structured component mirror their nested name (``inference``,
    ``contributed_model_training``, ``generalized_cross_tenant``, ...) so a True
    value is authoritative; anything absent / unknown contributes nothing.
    """
    out: set[str] = set()
    for name in dir(component):
        if name.startswith("_"):
            continue
        try:
            if getattr(component, name) is True:
                out.add(_norm_enum_value(name))
        except Exception:  # pragma: no cover
            continue
    if isinstance(component, BaseModel):
        data = component.model_dump(exclude_none=True)
        for key, value in data.items():
            if value is True:
                out.add(_norm_enum_value(key))
    return frozenset(out)


def _grant_is_active(grant: Any) -> bool:
    status = getattr(grant, "status", None)
    status = _norm_enum_value(status) if status is not None else None
    revoked_at = getattr(grant, "revoked_at", None)
    if status is not None and status != "active":
        return False
    if revoked_at is not None:
        return False
    expires_at = getattr(grant, "expires_at", None)
    if expires_at:
        try:
            from shared.common.common import parse_iso
            if parse_iso(str(expires_at)) <= utc_now():
                return False
        except Exception:  # pragma: no cover — unparseable expiry denies
            return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Transformation registry + pure functional TRANSFORMATION_APPLY helpers.
# ═══════════════════════════════════════════════════════════════════════════

_TRANSFORMATION_META: dict[str, tuple[str, tuple[str, ...]]] = {
    "pii_strip": (
        "Remove keys tagged as PII from the payload.",
        ("pii_schema", "evidence.pii_present"),
    ),
    "tenant_identifier_removal": (
        "Remove keys that identify the contributing tenant.",
        ("tenant_id_schema", "evidence.tenant_identifiability"),
    ),
    "tenant_metadata_strip": (
        "Remove tenant metadata keys (namespaces, labels, config).",
        ("tenant_metadata_schema", "evidence.tenant_identifiability"),
    ),
    "subject_pseudonymization": (
        "Replace subject identifiers with keyed pseudonyms.",
        ("pseudonym_key", "evidence.pii_present"),
    ),
    "bucketing": (
        "Coarsen a continuous field into labelled buckets.",
        ("bucket_definition", "evidence.minimum_population"),
    ),
    "cohort_thresholding": (
        "Suppress cohorts smaller than a minimum population.",
        ("minimum_population", "evidence.minimum_population"),
    ),
    "k_anonymity_minimum_population": (
        "Enforce k-anonymity-style minimum population on quasi-identifiers.",
        ("k_value", "evidence.minimum_population"),
    ),
    "distribution_aggregation": (
        "Replace rows with aggregate distribution statistics.",
        ("aggregate_function", "evidence.minimum_population"),
    ),
    "outlier_suppression": (
        "Suppress outlier values that would re-identify a cohort member.",
        ("outlier_rule", "evidence.reidentification_risk"),
    ),
    "edge_abstraction": (
        "Abstraction / removal of low-support graph edges.",
        ("edge_support_threshold", "evidence.lineage"),
    ),
    "feature_coarsening": (
        "Coarsen model-derived feature values.",
        ("feature_bucket_definition", "evidence.semantic_derivation"),
    ),
    "temporal_coarsening": (
        "Coarsen timestamps to a lower temporal resolution.",
        ("temporal_granularity", "evidence.minimum_population"),
    ),
    "geographic_coarsening": (
        "Coarsen geocodes to a larger region.",
        ("geo_granularity", "evidence.minimum_population"),
    ),
    "sensitivity_reduction": (
        "Reduce the declared sensitivity of a derived field.",
        ("sensitivity_override", "evidence.semantic_derivation"),
    ),
}

TRANSFORMATION_REGISTRY: dict[str, dict[str, Any]] = {
    kind: {"description": meta[0], "required_checks": list(meta[1])}
    for kind, meta in _TRANSFORMATION_META.items()
}

assert set(TRANSFORMATION_REGISTRY) == set(GENERALIZATION_TRANSFORMATION_KINDS), (
    "transformation registry and vocabulary must stay in lockstep"
)


def _pii_strip(payload: dict[str, Any], pii_keys: list[str]) -> tuple[dict[str, Any], str]:
    """Pure: remove PII-tagged keys. Returns (payload copy, evidence note)."""
    block = {str(k) for k in (pii_keys or [])}
    out = {k: v for k, v in payload.items() if k not in block}
    return out, f"pii_strip removed {len(payload) - len(out)} PII key(s)"


def _tenant_identifier_removal(
    payload: dict[str, Any], tenant_id_keys: list[str]
) -> tuple[dict[str, Any], str]:
    """Pure: remove tenant-identifying keys. Returns (payload copy, evidence)."""
    block = {str(k) for k in (tenant_id_keys or [])}
    out = {k: v for k, v in payload.items() if k not in block}
    return out, f"tenant_identifier_removal removed {len(payload) - len(out)} tenant key(s)"


def _bucketing(
    payload: dict[str, Any], field: str, buckets: list[tuple[Any, Any, str]]
) -> tuple[dict[str, Any], str]:
    """Pure: coarsen ``field`` into labelled buckets.

    ``buckets`` is a list of ``(low, high, label)``; the first bucket whose
    inclusive range contains the current value wins. An out-of-range value is
    mapped to the sentinel ``None`` (never an invented coarse value).
    """
    raw = payload.get(field)
    if raw is None:
        return dict(payload), f"bucketing {field}: value absent, left unchanged"
    for low, high, label in buckets or []:
        if low is not None and raw < low:
            continue
        if high is not None and raw > high:
            continue
        out = dict(payload)
        out[field] = label
        return out, f"bucketing {field} -> {label}"
    out = dict(payload)
    out[field] = None
    return out, f"bucketing {field}: out-of-range value set to None (no invented bucket)"


def _distribution_aggregation(
    rows: list[dict[str, Any]],
    numeric_field: str,
    *,
    min_population: int,
    cohort_label: Optional[str] = None,
) -> tuple[Optional[dict[str, Any]], str]:
    """Pure: aggregate numeric rows into a single distribution summary.

    Refuses to aggregate a cohort below the minimum population — the summary is
    ``None`` and the evidence note says suppression happened (fail closed, never
    a fabricated aggregate over a tiny cohort).
    """
    values = [r[numeric_field] for r in rows if numeric_field in r]
    if len(values) < min_population:
        return None, (
            f"distribution_aggregation suppressed: cohort size {len(values)} "
            f"< min_population {min_population}"
        )
    total = sum(values)
    mean = total / len(values)
    # Coarse summary only — no distribution reconstruction.
    summary = {
        "cohort": cohort_label or "aggregate",
        "n": len(values),
        "sum": round(total, 6),
        "mean": round(mean, 6),
    }
    return summary, f"distribution_aggregation over n={len(values)}"


def _subject_pseudonymization(
    payload: dict[str, Any], subject_keys: list[str]
) -> tuple[dict[str, Any], str]:
    """Pure: replace subject identifiers with keyed one-way pseudonyms."""
    out = dict(payload)
    replaced = 0
    for key in subject_keys or []:
        if key in out and out[key] is not None:
            seed = str(out[key]).encode("utf-8", errors="ignore")
            digest = __import__("hashlib").sha256(seed).hexdigest()[:16]
            out[key] = f"psn_{digest}"
            replaced += 1
    return out, f"subject_pseudonymization replaced {replaced} subject identifier(s)"


def _tenant_metadata_strip(
    payload: dict[str, Any], tenant_metadata_keys: list[str]
) -> tuple[dict[str, Any], str]:
    """Pure: remove tenant-metadata keys (namespaces, labels, config)."""
    block = {str(k) for k in (tenant_metadata_keys or [])}
    out = {k: v for k, v in payload.items() if k not in block}
    return out, (
        f"tenant_metadata_strip removed {len(payload) - len(out)} "
        "tenant metadata key(s)"
    )


TRANSFORMATION_APPLY: dict[str, Callable[..., tuple[Any, str]]] = {
    "pii_strip": _pii_strip,
    "tenant_identifier_removal": _tenant_identifier_removal,
    "tenant_metadata_strip": _tenant_metadata_strip,
    "bucketing": _bucketing,
    "distribution_aggregation": _distribution_aggregation,
    "subject_pseudonymization": _subject_pseudonymization,
}

# The subset of the registry TRANSFORMATION_APPLY implements functionally.
TRANSFORMATION_APPLY_SUBSET: frozenset[str] = frozenset(TRANSFORMATION_APPLY)


def _execute_deidentification(
    payload: dict[str, Any],
    kinds: list[str],
    keys: dict[str, list[str]],
) -> tuple[dict[str, Any], list[str]]:
    """Execute registered de-identification transformations over a payload copy.

    Every kind in ``kinds`` must have a functional executor in
    ``TRANSFORMATION_APPLY`` and a non-empty key list in ``keys`` (the payload
    keys that kind removes / rewrites). Fail closed: an unknown kind, a missing
    executor, or an empty key list raises :class:`GeneralizationDeniedError`
    rather than certify a de-identification that did not run.
    """
    current = dict(payload)
    notes: list[str] = []
    for kind in kinds:
        fn = TRANSFORMATION_APPLY.get(kind)
        if fn is None:
            raise GeneralizationDeniedError(
                f"required transformation {kind!r} has no functional executor"
            )
        key_list = list(keys.get(kind) or [])
        if not key_list:
            raise GeneralizationDeniedError(
                f"required transformation {kind!r} needs its key list in "
                "deidentification_keys but none was supplied"
            )
        try:
            if kind == "pii_strip":
                current, note = fn(current, pii_keys=key_list)
            elif kind == "tenant_identifier_removal":
                current, note = fn(current, tenant_id_keys=key_list)
            elif kind == "tenant_metadata_strip":
                current, note = fn(current, tenant_metadata_keys=key_list)
            elif kind == "subject_pseudonymization":
                current, note = fn(current, subject_keys=key_list)
            else:
                raise GeneralizationDeniedError(
                    f"required transformation {kind!r} has no functional executor"
                )
        except GeneralizationDeniedError:
            raise
        except Exception as exc:  # pragma: no cover — defensive
            raise GeneralizationDeniedError(
                f"required transformation {kind!r} failed to execute: {exc}"
            ) from exc
        notes.append(note)
    return current, notes


# ═══════════════════════════════════════════════════════════════════════════
# Contracts
# ═══════════════════════════════════════════════════════════════════════════

class GeneralizationRequest(BaseModel):
    """Blueprint §28 generalization eligibility request."""

    artifact_ref: str
    tenant_id: str
    requested_destination: Literal[
        "olympus_graph", "platform_learning", "benchmark", "model_training"
    ]
    requested_use: str
    evidence_refs: list[str] = Field(default_factory=list)
    rights_refs: list[str] = Field(default_factory=list)
    actor: str
    purpose: str


class GeneralizationEligibilityContext(BaseModel):
    """Runtime signals the gateway needs that a RightsDecision cannot carry.

    Every field is *optional* and every absent field is treated as UNVERIFIABLE
    which, per the fail-closed prime directive, is a denial (never converted to
    a permissive default). In production the caller builds this from lineage,
    data-profiling evidence and grant records; tests supply faithful stand-ins.
    """

    grants: list[Any] = Field(default_factory=list)
    grant_refs: list[str] = Field(default_factory=list)
    consent_decision_refs: list[str] = Field(default_factory=list)
    consent_allowed: Optional[bool] = None
    pii_present: Optional[bool] = None
    tenant_identifiable: Optional[bool] = None
    reidentification_risk: Optional[str] = None
    minimum_population: Optional[int] = None
    minimum_population_satisfied: Optional[bool] = None
    lineage_complete: Optional[bool] = None
    data_sensitivity: Optional[str] = None
    derivation_class: Optional[str] = None


class GeneralizationTransformation(BaseModel):
    """One registered, evidence-linked transformation applied to an artifact."""

    transformation_id: str = Field(default_factory=lambda: f"gtrans_{uuid.uuid4().hex}")
    kind: Literal[
        "pii_strip",
        "tenant_identifier_removal",
        "tenant_metadata_strip",
        "subject_pseudonymization",
        "bucketing",
        "cohort_thresholding",
        "k_anonymity_minimum_population",
        "distribution_aggregation",
        "outlier_suppression",
        "edge_abstraction",
        "feature_coarsening",
        "temporal_coarsening",
        "geographic_coarsening",
        "sensitivity_reduction",
    ]
    evidence_refs: list[str] = Field(default_factory=list)


class GeneralizationDecision(BaseModel):
    """Gateway evaluation result (also the durable generalization RightsDecision).

    Persisted into the canonical ``rights_decisions`` store (via the P-B1
    rights_decision_repository) under ``decision_id``.
    """

    decision_id: str = Field(default_factory=lambda: f"rdec_{uuid.uuid4().hex}")
    tenant_id: str
    artifact_ref: str
    requested_destination: str
    requested_use: str
    allowed: bool
    disposition: str = "deny"
    denial_reason_codes: list[str] = Field(default_factory=list)
    eligible_transformations: list[str] = Field(default_factory=list)
    required_transformations: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    minimum_population_met: bool = False
    source_grant_refs: list[str] = Field(default_factory=list)
    rights_decision_ref: Optional[str] = None
    consent_decision_refs: list[str] = Field(default_factory=list)
    policy_version: str = GENERALIZATION_POLICY_VERSION
    evaluated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    effective_as_of: str = Field(default_factory=lambda: utc_now().isoformat())
    evidence_refs: list[str] = Field(default_factory=list)


class GeneralizedArtifact(BaseModel):
    """Blueprint §31 output of a successful generalization application."""

    generalized_artifact_id: str = Field(
        default_factory=lambda: f"gart_{uuid.uuid4().hex}"
    )
    tenant_id: str
    parent_artifact_refs: list[str] = Field(default_factory=list)
    transformation_refs: list[str] = Field(default_factory=list)
    generalization_policy_version: str = GENERALIZATION_POLICY_VERSION
    rights_decision_ref: Optional[str] = None
    source_grant_refs: list[str] = Field(default_factory=list)
    tenant_identifiable: bool = True
    reidentification_risk: str = "high"
    minimum_population_met: bool = False
    lineage_ref: Optional[str] = None
    permitted_destinations: list[str] = Field(default_factory=list)
    retention_policy_ref: Optional[str] = None
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class GeneralizationDeniedError(RuntimeError):
    """Raised when ``apply`` is asked to materialise a disallowed decision."""


class GeneralizationGateway:
    """Runtime adapter that decides + materialises generalization.

    Deliberately thin over the canonical authorities — it composes grants,
    consent, learning/disclosure/source-use authority and evidence, then stamps a
    ``GeneralizedArtifact``. It does NOT own a parallel rights registry.
    """

    def __init__(
        self,
        *,
        minimum_population_threshold: int = MINIMUM_POPULATION_THRESHOLD,
        decision_repository: Optional[Any] = None,
        artifact_repository: Optional[Any] = None,
    ) -> None:
        self._minimum_population_threshold = minimum_population_threshold
        self._decision_repository = decision_repository
        self._artifact_repository = artifact_repository

    # ── lazy collaborators ──────────────────────────────────────────────────

    def _decisions(self) -> Any:
        if self._decision_repository is not None:
            return self._decision_repository
        return _pb1_repositories().rights_decision_repository

    def _artifacts(self) -> Any:
        if self._artifact_repository is not None:
            return self._artifact_repository
        return _artifacts_repository

    # ── Public API ──────────────────────────────────────────────────────────

    async def evaluate(
        self,
        request: GeneralizationRequest,
        context: Optional[GeneralizationEligibilityContext] = None,
    ) -> GeneralizationDecision:
        """Evaluate whether ``request`` may be generalized to its destination.

        Fail closed: every required signal that cannot be verified (missing
        evidence, unknown grant authority, unverifiable PII / identifiability /
        population) yields a denial with explicit ``denial_reason_codes`` and
        the ``required_evidence`` needed to make it eligible.
        """
        ctx = context or GeneralizationEligibilityContext()
        now_iso = utc_now().isoformat()

        decision = GeneralizationDecision(
            tenant_id=request.tenant_id,
            artifact_ref=request.artifact_ref,
            requested_destination=request.requested_destination,
            requested_use=request.requested_use,
            allowed=True,
            disposition="allow",
            evidence_refs=list(request.evidence_refs),
            evaluated_at=now_iso,
            effective_as_of=now_iso,
        )

        # Layers 1-2: request shape / evidence presence.
        if request.requested_destination not in GENERALIZATION_DESTINATIONS:
            decision.denial_reason_codes.append("unknown_destination")
        if not request.evidence_refs and not ctx.lineage_complete:
            decision.denial_reason_codes.append("missing_evidence")

        # Layer 3: source grants + revocation state.
        grants = list(ctx.grants)
        source_grant_refs: list[str] = list(ctx.grant_refs)
        if not grants:
            # Secondary consult: surface the P-B1 resolver's denial reasons when
            # no grant records were supplied (grant loading is an integration
            # seam — the context is the primary structured-authority input).
            decision.denial_reason_codes.extend(await self._resolver_consult(request))
        if not grants:
            decision.denial_reason_codes.append("missing_active_grant")
        # Never union authority from unrelated grants.  A grant is eligible
        # only when it belongs to this tenant and is explicitly linked by the
        # request's grant/source refs (or is the governing grant for the
        # requested artifact).  Status, expiry and revocation are checked here
        # before any authority classes are aggregated.
        requested_refs = set(ctx.grant_refs) | set(request.rights_refs)
        active_grants = []
        for grant in grants:
            gtenant = getattr(grant, "tenant_id", None)
            gid = str(getattr(grant, "data_rights_grant_id", "") or "")
            if gtenant is None or str(gtenant) != request.tenant_id:
                continue
            if requested_refs and gid not in requested_refs:
                continue
            if _grant_is_active(grant):
                active_grants.append(grant)
        if grants and not active_grants:
            decision.denial_reason_codes.append("no_matching_tenant_grant")
        if not active_grants:
            decision.denial_reason_codes.append("grant_not_active")
        if not decision.source_grant_refs:
            decision.source_grant_refs = source_grant_refs or [
                str(getattr(g, "data_rights_grant_id", ""))
                for g in active_grants
                if getattr(g, "data_rights_grant_id", None)
            ]

        # Layer 4: consent.
        if ctx.consent_allowed is not True:
            decision.denial_reason_codes.append("consent_not_verified")
        if ctx.consent_decision_refs:
            decision.consent_decision_refs = list(ctx.consent_decision_refs)

        # Layer 5: destination authority requirements (learning / source-use /
        # disclosure over the structured grant components).
        self._assess_destination_authority(request, ctx, active_grants, decision)

        # Layer 6: PII presence (conservative when unverifiable).
        if ctx.pii_present is None:
            decision.denial_reason_codes.append("pii_unverifiable")
            decision.required_evidence.append("evidence.pii_present")

        # Layer 7: tenant identifiability.
        if ctx.tenant_identifiable is None:
            decision.denial_reason_codes.append("tenant_identifiability_unverifiable")
            decision.required_evidence.append("evidence.tenant_identifiability")
        elif ctx.tenant_identifiable is True:
            # Only removable when transformations can demonstrably strip it.
            if self._residual_risk(ctx) == "high":
                decision.denial_reason_codes.append("tenant_identifiable_not_removable")
                decision.denial_reason_codes.append("reidentification_risk_high")
                decision.required_evidence.append("evidence.reidentification_risk")
            else:
                for kind in ("tenant_identifier_removal", "pii_strip", "tenant_metadata_strip"):
                    if kind not in decision.required_transformations:
                        decision.required_transformations.append(kind)

        # Layer 8: minimum population.
        population_ok = (
            ctx.minimum_population_satisfied is True
            or (
                ctx.minimum_population is not None
                and ctx.minimum_population >= self._minimum_population_threshold
            )
        )
        if population_ok:
            decision.minimum_population_met = True
        else:
            decision.denial_reason_codes.append("minimum_population_not_met")
            decision.required_evidence.append("evidence.minimum_population")

        # Layer 9: re-identification risk ("high" is always denied).
        if self._residual_risk(ctx) == "high":
            decision.denial_reason_codes.append("reidentification_risk_high")
            decision.required_evidence.append("evidence.reidentification_risk")

        # Layer 10: lineage completeness.
        if ctx.lineage_complete is not True:
            decision.denial_reason_codes.append("lineage_incomplete")
            decision.required_evidence.append("evidence.lineage")

        # Layer 11: semantic / derivation class (stricter for reconstructable
        # derivatives such as MODEL_DERIVED / TENANT_IDENTIFIABLE_DERIVATIVE).
        derivation = _norm_enum_value(ctx.derivation_class) if ctx.derivation_class else ""
        if derivation in _STRICT_DERIVATION_CLASSES:
            decision.denial_reason_codes.append("derivation_class_requires_evidence")
            decision.required_evidence.append("evidence.semantic_derivation")

        # Layer 12: eligible transformations.
        decision.eligible_transformations = self._eligible_transformations(ctx)

        decision.allowed = not decision.denial_reason_codes
        decision.disposition = "allow" if decision.allowed else "deny"

        await self._persist_decision(request, decision)
        return decision

    # ── internal evaluation helpers ─────────────────────────────────────────

    async def _resolver_consult(self, request: GeneralizationRequest) -> list[str]:
        """Best-effort P-B1 resolver consult; returns extra denial reason codes.

        When the effective rights resolver is reachable it produces the durable
        RightsDecision for the generalize action. A denial there is authoritative
        and its ``reason_codes`` are surfaced into the gateway decision. Anything
        unavailable contributes nothing extra (the gateway's own fail-closed
        checks still deny on missing grant records).
        """
        try:
            resolver = _pb1_resolver()
        except Exception:
            return []
        try:
            resolved = await resolver.effective_rights_resolver.resolve(
                tenant=request.tenant_id,
                source=request.rights_refs,
                artifact=request.artifact_ref,
                actor=request.actor,
                requested_use="generalize",
                purpose=request.purpose,
                destination=request.requested_destination,
            )
        except Exception as exc:  # pragma: no cover — resolver absent/unavailable
            logger.warning(
                "effective rights resolver unavailable for %s: %s",
                request.artifact_ref, exc,
            )
            return []
        if resolved is None or getattr(resolved, "allowed", None) is not False:
            return []
        reasons = getattr(resolved, "reason_codes", None) or []
        return [str(r) for r in reasons]

    def _assess_destination_authority(
        self,
        request: GeneralizationRequest,
        ctx: GeneralizationEligibilityContext,
        grants: list[Any],
        decision: GeneralizationDecision,
    ) -> None:
        requirements = DESTINATION_AUTHORITY_REQUIREMENTS.get(
            request.requested_destination
        )
        if requirements is None:
            decision.denial_reason_codes.append("unknown_destination")
            return
        learning = _union_learning(grants)
        disclosure = _union_disclosure(grants)
        source_use = _union_source_use(grants)
        if not (learning & requirements["learning"]):
            decision.denial_reason_codes.append("learning_authority_denied")
        if requirements["source_use"] and not (source_use & requirements["source_use"]):
            decision.denial_reason_codes.append("olympus_baseline_denied")
        if requirements["disclosure"] and not (disclosure & requirements["disclosure"]):
            decision.denial_reason_codes.append("disclosure_denied")

    def _residual_risk(self, ctx: GeneralizationEligibilityContext) -> str:
        risk = _norm_enum_value(ctx.reidentification_risk) if ctx.reidentification_risk else ""
        if risk == "high":
            return "high"
        if risk in ("low", "none"):
            return "low"
        return "medium"

    def _eligible_transformations(
        self, ctx: GeneralizationEligibilityContext
    ) -> list[str]:
        eligible: list[str] = []
        derivation = _norm_enum_value(ctx.derivation_class) if ctx.derivation_class else ""
        if ctx.pii_present is not None:
            eligible.append("pii_strip")
            eligible.append("subject_pseudonymization")
        if ctx.tenant_identifiable is not None:
            eligible.append("tenant_identifier_removal")
            eligible.append("tenant_metadata_strip")
        eligible.extend(sorted(_POPULATION_TRANSFORMATIONS))
        if derivation in _STRICT_DERIVATION_CLASSES:
            eligible.append("feature_coarsening")
        return eligible

    async def _persist_decision(
        self, request: GeneralizationRequest, decision: GeneralizationDecision
    ) -> None:
        """Durable RightsDecision record for the generalize action."""
        repos = _pb1_repositories()
        await repos.rights_decision_repository.record(
            _decision_row(decision)
        )
        decision.rights_decision_ref = decision.decision_id

    # ── apply ───────────────────────────────────────────────────────────────

    async def apply(
        self,
        request: GeneralizationRequest,
        decision: Optional[GeneralizationDecision] = None,
        *,
        context: Optional[GeneralizationEligibilityContext] = None,
        payload: Optional[dict[str, Any]] = None,
        deidentification_keys: Optional[dict[str, list[str]]] = None,
        transformation_ids: Optional[dict[str, str]] = None,
    ) -> GeneralizedArtifact:
        """Materialise a generalized artifact for an authoritatively allowed use.

        The authorization source is a FRESH :meth:`evaluate` — never the
        caller-supplied ``decision``, so a fabricated ``allowed=True`` decision
        cannot materialise an artifact. ``decision`` is accepted only for two-step
        callers that already evaluated; apply re-derives the decision and binds
        the artifact to that fresh durable record.

        De-identification is *executed, not recorded*: when the authoritative
        evaluation finds the source tenant-identifiable or PII-bearing, every
        required transformation is actually run over ``payload`` through
        ``TRANSFORMATION_APPLY`` before the artifact is stamped non-identifiable.
        ``deidentification_keys`` names, per kind, the payload keys that kind
        removes / rewrites. If the payload is absent, a required key list is empty,
        or a required kind has no functional executor, ``apply`` raises
        :class:`GeneralizationDeniedError` rather than certify a transform that
        did not run (fail closed, blueprint §1.5 / §32).
        """
        ctx = context or GeneralizationEligibilityContext()

        # (1) Authoritative re-evaluation. Never trust a caller-supplied decision
        #     as the authorization source; reject an outright destination mismatch
        #     on any supplied decision as defence in depth.
        if decision is not None and decision.requested_destination != request.requested_destination:
            raise GeneralizationDeniedError(
                f"generalization refused for {request.artifact_ref}: caller "
                f"decision destination {decision.requested_destination!r} does not "
                f"match request destination {request.requested_destination!r}"
            )
        authoritative = await self.evaluate(request, context=ctx)
        if not authoritative.allowed:
            raise GeneralizationDeniedError(
                f"generalization refused for {request.artifact_ref} "
                f"(decision {authoritative.decision_id}): allowed=False "
                f"reasons={sorted(authoritative.denial_reason_codes)}"
            )

        # (2) Executed de-identification. ``required_transformations`` is the
        #     authoritative set the source needs before it may be exported as
        #     non-identifiable; a PII-bearing source additionally needs a PII kind.
        #     Every required kind must actually run over the payload — never stamp
        #     de-identified from recorded-but-unexecuted transformation intent.
        required = list(authoritative.required_transformations)
        need: set[str] = set(required)
        if ctx.pii_present is True and not (need & _PII_KINDS):
            need.add("pii_strip")
        executed_kinds: list[str] = []
        if need:
            missing_exec = sorted(k for k in need if k not in TRANSFORMATION_APPLY)
            if missing_exec:
                raise GeneralizationDeniedError(
                    f"generalization refused for {request.artifact_ref}: required "
                    f"transformation(s) {missing_exec} have no functional executor"
                )
            if payload is None:
                raise GeneralizationDeniedError(
                    f"generalization refused for {request.artifact_ref}: "
                    f"de-identification requires the payload (transformations "
                    f"{sorted(need)}) but none was supplied"
                )
            keys = dict(deidentification_keys or {})
            for kind in sorted(need):
                if not keys.get(kind):
                    raise GeneralizationDeniedError(
                        f"generalization refused for {request.artifact_ref}: "
                        f"required transformation {kind!r} needs its key list in "
                        "deidentification_keys but none was supplied"
                    )
            _, notes = _execute_deidentification(payload, sorted(need), keys)
            executed_kinds = sorted(need)
            logger.info(
                "de-identified payload for %s (decision %s): %s",
                request.artifact_ref, authoritative.decision_id, notes,
            )

        transformation_records: list[GeneralizationTransformation] = []
        for kind in executed_kinds:
            transformation_records.append(
                GeneralizationTransformation(
                    kind=kind,  # type: ignore[arg-type]
                    evidence_refs=[authoritative.decision_id],
                )
            )

        # Evidence entry appended to the durable decision (audit trail).
        evidence_id = f"ev_{uuid.uuid4().hex}"
        await self._append_decision_evidence(authoritative.decision_id, evidence_id)

        # (3) Honest stamping: the output is only non-tenant-identifiable when it
        #     was never tenant-identifiable OR every required tenant-identifying
        #     transformation executed above (belt-and-suspenders — the deny paths
        #     above already guarantee execution when ``tenant_identifiable`` is
        #     True).
        tenant_identifiable = bool(
            ctx.tenant_identifiable is True and not executed_kinds
        )
        population_met = (
            ctx.minimum_population_satisfied is True
            or (
                ctx.minimum_population is not None
                and ctx.minimum_population >= self._minimum_population_threshold
            )
        )
        risk = self._residual_risk(ctx) if population_met else "high"
        if risk == "high":
            risk = "low" if required else "medium"
        risk = risk if risk in ("low", "medium") else "low"

        artifact = GeneralizedArtifact(
            tenant_id=request.tenant_id,
            parent_artifact_refs=[request.artifact_ref],
            transformation_refs=[t.transformation_id for t in transformation_records],
            rights_decision_ref=authoritative.decision_id,
            source_grant_refs=list(authoritative.source_grant_refs),
            tenant_identifiable=tenant_identifiable,
            reidentification_risk=risk,
            minimum_population_met=population_met,
            lineage_ref=request.artifact_ref,
            permitted_destinations=[request.requested_destination],
            retention_policy_ref=None,
            evidence_refs=[evidence_id],
        )
        if transformation_ids:
            artifact.transformation_refs = [
                transformation_ids.get(kind, t.transformation_id)
                for kind, t in zip(executed_kinds, transformation_records)
            ]
        await self._artifacts().record(_artifact_row(artifact))
        return artifact

    async def _append_decision_evidence(self, decision_id: str, evidence_id: str) -> None:
        repos = _pb1_repositories()
        repo = repos.rights_decision_repository
        existing: list[str] = []
        try:
            record = await repo.get(decision_id)
            if record is not None:
                existing = list(_field_list(record, "evidence_refs"))
        except Exception:  # pragma: no cover — decision row may be absent
            existing = []
        evidence_refs = [*existing, evidence_id]
        await repo.update_state(decision_id, {"evidence_refs": evidence_refs})

    # ── olympus knowledge exit ──────────────────────────────────────────────

    async def is_eligible_for_olympus_knowledge(self, artifact: GeneralizedArtifact) -> bool:
        """The ONLY path for tenant-derived material into Olympus knowledge.

        Requires the artifact (a) was produced through the gateway (carries a
        durable allowed decision reference), (b) is non-tenant-identifiable with
        bounded re-identification risk, (c) met the minimum population, (d) has a
        lineage reference, and (e) explicitly permits the olympus_graph
        destination. Fail closed on any unknown.
        """
        if artifact is None:
            return False
        if artifact.tenant_identifiable is not False:
            return False
        if _norm_enum_value(artifact.reidentification_risk) not in ("low", "none"):
            return False
        if artifact.minimum_population_met is not True:
            return False
        if not artifact.lineage_ref:
            return False
        if artifact.rights_decision_ref is None:
            return False
        if "olympus_graph" not in (artifact.permitted_destinations or []):
            return False
        # Cross-check the durable decision exists and allowed the destination.
        try:
            repos = _pb1_repositories()
            record = await repos.rights_decision_repository.get(artifact.rights_decision_ref)
        except Exception:  # pragma: no cover
            return False
        if record is None:
            return False
        allowed = _row_field(record, "allowed")
        requested_destination = _row_field(record, "requested_destination")
        if allowed is not True:
            return False
        if requested_destination not in ("olympus_graph", None):
            return False
        return True


# Module-level artifact repository + gateway singleton.
class GeneralizedArtifactRepository(_ScopedRepo):
    """Tenant-scoped store of generalized artifacts (table: generalized_artifacts)."""

    def __init__(self) -> None:
        super().__init__("generalized_artifacts")

    async def record(self, row: dict[str, Any]) -> dict[str, Any]:
        artifact_id = row.get("generalized_artifact_id") or row.get("id")
        if not artifact_id:
            artifact_id = f"gart_{uuid.uuid4().hex}"
            row["generalized_artifact_id"] = artifact_id
        return await self.insert(artifact_id, row)

    async def get(self, artifact_id: str) -> Optional[dict[str, Any]]:
        return await self.find_by_id(artifact_id)


# Module-level singleton gateway bound to the canonical repositories.
_artifacts_repository = GeneralizedArtifactRepository()
generalized_artifact_repository = _artifacts_repository
generalization_gateway = GeneralizationGateway()


# ═══════════════════════════════════════════════════════════════════════════
# Persistence helpers
# ═══════════════════════════════════════════════════════════════════════════

def _decision_row(decision: GeneralizationDecision) -> dict[str, Any]:
    """Durable RightsDecision-shaped row for a generalization decision."""
    return {
        "decision_id": decision.decision_id,
        "tenant_id": decision.tenant_id,
        "allowed": decision.allowed,
        "disposition": decision.disposition,
        "reason_codes": list(decision.denial_reason_codes),
        "source_grant_refs": list(decision.source_grant_refs),
        "consent_decision_refs": list(decision.consent_decision_refs),
        "permitted_uses": [],
        "permitted_derivations": [],
        "permitted_learning": list(decision.required_transformations)
        if decision.allowed
        else [],
        "permitted_disclosures": [],
        "retention": "",
        "deletion": "",
        "survival": "",
        "evaluated_at": decision.evaluated_at,
        "effective_as_of": decision.effective_as_of,
        "policy_version": decision.policy_version,
        "evidence_refs": list(decision.evidence_refs),
        "requested_use": decision.requested_use,
        "artifact_ref": decision.artifact_ref,
        "requested_destination": decision.requested_destination,
        "required_evidence": list(decision.required_evidence),
        "eligible_transformations": list(decision.eligible_transformations),
        "required_transformations": list(decision.required_transformations),
    }


def _artifact_row(artifact: GeneralizedArtifact) -> dict[str, Any]:
    return {
        "generalized_artifact_id": artifact.generalized_artifact_id,
        "tenant_id": artifact.tenant_id,
        "parent_artifact_refs": list(artifact.parent_artifact_refs),
        "transformation_refs": list(artifact.transformation_refs),
        "generalization_policy_version": artifact.generalization_policy_version,
        "rights_decision_ref": artifact.rights_decision_ref,
        "source_grant_refs": list(artifact.source_grant_refs),
        "tenant_identifiable": artifact.tenant_identifiable,
        "reidentification_risk": artifact.reidentification_risk,
        "minimum_population_met": artifact.minimum_population_met,
        "lineage_ref": artifact.lineage_ref,
        "permitted_destinations": list(artifact.permitted_destinations),
        "retention_policy_ref": artifact.retention_policy_ref,
        "evidence_refs": list(artifact.evidence_refs),
        "created_at": artifact.created_at,
    }


def _union_learning(grants: list[Any]) -> frozenset[str]:
    out: set[str] = set()
    for grant in grants:
        out |= set(_grant_learning_classes(grant))
    return frozenset(out)


def _union_disclosure(grants: list[Any]) -> frozenset[str]:
    out: set[str] = set()
    for grant in grants:
        out |= set(_grant_disclosure_classes(grant))
    return frozenset(out)


def _union_source_use(grants: list[Any]) -> frozenset[str]:
    out: set[str] = set()
    for grant in grants:
        out |= set(_grant_source_use_classes(grant))
    return frozenset(out)


def _field_list(record: Any, field: str) -> list[Any]:
    if isinstance(record, dict):
        return list(record.get(field) or [])
    return list(getattr(record, field, None) or [])


def _row_field(record: Any, field: str) -> Any:
    if isinstance(record, dict):
        return record.get(field)
    return getattr(record, field, None)


__all__ = [
    "DESTINATION_AUTHORITY_REQUIREMENTS",
    "GENERALIZATION_DESTINATIONS",
    "GENERALIZATION_POLICY_VERSION",
    "GENERALIZATION_TRANSFORMATION_KINDS",
    "GeneralizationDecision",
    "GeneralizationDeniedError",
    "GeneralizationEligibilityContext",
    "GeneralizationGateway",
    "GeneralizationRequest",
    "GeneralizationTransformation",
    "GeneralizedArtifact",
    "GeneralizedArtifactRepository",
    "generalized_artifact_repository",
    "MINIMUM_POPULATION_THRESHOLD",
    "TRANSFORMATION_APPLY",
    "TRANSFORMATION_APPLY_SUBSET",
    "TRANSFORMATION_REGISTRY",
    "generalization_gateway",
]
