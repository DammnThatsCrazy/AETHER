"""Aether — Rights Authority: learning + model governance.

Stream P-B2 (part 2) of the ``rights_irrl`` canonical authority. Implements
blueprint §8 / §38–§40: training gates resolve rights before use; ``TENANT_LOCAL``
vs ``GENERALIZED_PLATFORM`` learning are distinguished at storage / model-registry
level; revocation states follow the §40 vocabulary. Never claim a model was
"deleted" merely because training rows disappeared.
"""
from __future__ import annotations

import importlib
import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from services.rights_authority.generalization import _grant_learning_classes, _norm_enum_value

logger = get_logger("aether.rights_irrl.model_governance")

POLICY_VERSION = "irrl-2"

# Learning classes (blueprint §3.3), snake_case. ``contributed_model_training``
# is the value P-A exposes as LearningClass.CONTRIBUTED_MODEL_TRAINING.
LEARNING_CLASSES: tuple[str, ...] = (
    "inference",
    "tenant_adaptation",
    "generalized_learning",
    "resolver_calibration",
    "ontology_learning",
    "schema_mapping_learning",
    "benchmarking",
    "contributed_model_training",
    "olympus_internal_intelligence",
)

CONTRIBUTED_MODEL_TRAINING = "contributed_model_training"

# Learning tokens that consume tenant-identifiable material inside the tenant
# only (never platform-generalized).
TENANT_LOCAL_LEARNING_CLASSES = frozenset({"inference", "tenant_adaptation"})
GENERALIZED_LEARNING_CLASSES = frozenset({
    "generalized_learning", "contributed_model_training", "resolver_calibration",
    "ontology_learning", "schema_mapping_learning", "benchmarking",
    "olympus_internal_intelligence",
})

# Model revocation states (blueprint §40 / P-A ModelRevocationState values).
MODEL_REVOCATION_STATES: tuple[str, ...] = (
    "no_action_required",
    "retrain_required",
    "model_quarantine_required",
    "evaluation_required",
    "legal_review_required",
    "blocked",
)

_TRAINING_REQUESTED_USES = frozenset({
    "train", "training", "model_training", "contributed_model_training",
    "fine_tuning", "evaluation",
})


def _pb1_repositories():
    """P-B1: ``services.rights_authority.repositories`` singleton stores."""
    return importlib.import_module("services.rights_authority.repositories")


def _pa_models():
    """P-A: ``services.integrations.data_rights.models`` (LearningClass)."""
    return importlib.import_module("services.integrations.data_rights.models")


# ═══════════════════════════════════════════════════════════════════════════
# Contracts
# ═══════════════════════════════════════════════════════════════════════════

class TrainingDataManifest(BaseModel):
    """Blueprint §38 training-data manifest.

    ``exclusion_count`` records how many records were excluded from training for
    rights reasons — it is recorded, never converted from an unknown to 0.
    """

    run_id: str
    model_ref: str
    dataset_artifact_refs: list[str] = Field(default_factory=list)
    rights_decision_refs: list[str] = Field(default_factory=list)
    grant_refs: list[str] = Field(default_factory=list)
    learning_authority_classes: list[str] = Field(default_factory=list)
    exclusion_count: int = 0
    transformation_refs: list[str] = Field(default_factory=list)
    temporal_snapshot: str = ""
    policy_version: str = POLICY_VERSION
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())


class LearningEligibilityReport(BaseModel):
    """Blueprint §39 rights-eligibility report for a training use."""

    tenant_id: str
    source_id: str = ""
    artifact_ref: Optional[str] = None
    learning_class: str = CONTRIBUTED_MODEL_TRAINING
    eligible: bool = False
    denial_reason_codes: list[str] = Field(default_factory=list)
    allowed_classes: list[str] = Field(default_factory=list)
    tenant_local_only: bool = False
    manifest_refs: list[str] = Field(default_factory=list)
    policy_version: str = POLICY_VERSION


class ModelRevocationAssessment(BaseModel):
    """Model revocation impact (state + reasons), blueprint §40.

    ``state`` carries the ModelRevocationState *value* (snake_case). Use
    :meth:`as_state` to map it onto the P-A enum member when importable.
    """

    model_ref: str = ""
    state: str = "no_action_required"
    reasons: list[str] = Field(default_factory=list)

    def as_state(self) -> Any:
        """Map ``state`` onto the P-A ``ModelRevocationState`` enum when present."""
        try:
            enum_cls = _pa_models().ModelRevocationState
            for member in enum_cls:
                if _norm_enum_value(member) == self.state:
                    return member
        except Exception:  # pragma: no cover — P-A not landed
            pass
        return self.state


# ═══════════════════════════════════════════════════════════════════════════
# Eligibility
# ═══════════════════════════════════════════════════════════════════════════

def _grant_source_match(grant: Any, tenant_id: str, source_id: str) -> bool:
    g_tenant = getattr(grant, "tenant_id", None)
    if g_tenant is not None and _norm_enum_value(g_tenant) != _norm_enum_value(tenant_id):
        return False
    g_source = getattr(grant, "source_id", None)
    if g_source is not None and _norm_enum_value(g_source) != _norm_enum_value(source_id):
        return False
    if getattr(grant, "status", None) is not None:
        status = _norm_enum_value(getattr(grant, "status"))
        if status != "active":
            return False
    return True


async def model_training_eligibility(
    tenant_id: str,
    source_id: str = "",
    learning_class: str = CONTRIBUTED_MODEL_TRAINING,
    artifact_ref: Optional[str] = None,
    *,
    grants: Optional[list[Any]] = None,
    manifest_refs: Optional[list[str]] = None,
) -> LearningEligibilityReport:
    """Rights eligibility for a training use over a tenant's source material.

    Consulted authorities: effective learning authority over the matching grant(s)
    (P-A ``effective_learning_authority`` helper honoured) and, when grant records
    are not supplied, the P-B1 effective rights resolver. ``contributed_model_training``
    must be EXPLICITLY True (the legacy ``model_training_allowed=True`` migration
    maps here; absent → deny). TENANT_LOCAL vs GENERALIZED_PLATFORM learning is
    distinguished: tenant-local uses need ``inference``/``tenant_adaptation`` only;
    generalized uses need ``generalized_learning`` / ``contributed_model_training``.
    """
    lc = _norm_enum_value(learning_class)
    report = LearningEligibilityReport(
        tenant_id=tenant_id,
        source_id=source_id,
        artifact_ref=artifact_ref,
        learning_class=lc,
        manifest_refs=list(manifest_refs or []),
    )

    grant_list = list(grants or [])
    if not grant_list:
        grant_list = await _resolve_grants_for(tenant_id, source_id, artifact_ref)

    matching = [g for g in grant_list if _grant_source_match(g, tenant_id, source_id)]
    if not grant_list:
        report.denial_reason_codes.append("missing_grant_evidence")
    elif not matching:
        report.denial_reason_codes.append("no_active_grant_for_source")

    allowed: set[str] = set()
    for grant in matching:
        allowed |= set(_grant_learning_classes(grant))
    report.allowed_classes = sorted(allowed)

    if lc == CONTRIBUTED_MODEL_TRAINING and CONTRIBUTED_MODEL_TRAINING not in allowed:
        report.denial_reason_codes.append("contributed_training_not_authorized")

    # Distinguish TENANT_LOCAL vs GENERALIZED_PLATFORM (§39).
    tenant_local = bool(allowed & TENANT_LOCAL_LEARNING_CLASSES)
    generalized = bool(allowed & GENERALIZED_LEARNING_CLASSES)
    if lc in GENERALIZED_LEARNING_CLASSES and not generalized:
        report.denial_reason_codes.append("generalized_learning_not_authorized")
    report.tenant_local_only = tenant_local and not generalized
    if report.tenant_local_only and lc in GENERALIZED_LEARNING_CLASSES:
        report.denial_reason_codes.append("tenant_local_only")

    report.eligible = not report.denial_reason_codes
    return report


async def _resolve_grants_for(
    tenant_id: str, source_id: str, artifact_ref: Optional[str]
) -> list[Any]:
    """Secondary grant resolution via the P-B1 resolver when reachable."""
    try:
        resolver = importlib.import_module("services.rights_authority.resolver")
        resolved = await resolver.effective_rights_resolver.resolve(
            tenant=tenant_id,
            source=[source_id] if source_id else [],
            artifact=artifact_ref or "",
            actor="system",
            requested_use="train",
            purpose="model_training",
            destination="model_training",
        )
        if resolved is not None and getattr(resolved, "allowed", None) is True:
            return []  # resolver allowed but no structured grant objects reachable
    except Exception as exc:  # pragma: no cover — resolver seam absent
        logger.debug("resolver consult unavailable for training eligibility: %s", exc)
    return []


# ═══════════════════════════════════════════════════════════════════════════
# Manifest validation
# ═══════════════════════════════════════════════════════════════════════════

async def validate_training_manifest(
    manifest: TrainingDataManifest,
    *,
    decision_repository: Optional[Any] = None,
) -> LearningEligibilityReport:
    """Validate a training manifest against persisted rights decisions.

    Every ``dataset_artifact_ref`` must be backed by an *allowed*, training-use
    ``RightsDecision`` persisted in the canonical decision store whose reference
    appears in ``rights_decision_refs``; otherwise the manifest is denied with
    ``missing_rights_evidence``. ``exclusion_count`` is recorded as declared —
    never inferred, never converted from unknown to 0.
    """
    repo = decision_repository or _pb1_repositories().rights_decision_repository
    report = LearningEligibilityReport(
        tenant_id="",
        source_id="",
        artifact_ref=None,
        learning_class=CONTRIBUTED_MODEL_TRAINING,
        manifest_refs=[manifest.run_id],
    )
    reasons: list[str] = []
    if not manifest.dataset_artifact_refs:
        reasons.append("missing_dataset_artifact_refs")

    if manifest.exclusion_count < 0:
        reasons.append("negative_exclusion_count")

    # Load every persisted decision referenced by the manifest.
    verified: set[str] = set()
    decision_rows: list[tuple[str, Optional[Any]]] = []
    for decision_ref in manifest.rights_decision_refs or []:
        try:
            row = await repo.get(decision_ref)
        except Exception:  # pragma: no cover — repository row absent
            row = None
        decision_rows.append((decision_ref, row))

    for decision_ref, row in decision_rows:
        if row is None:
            reasons.append("missing_rights_evidence")
            continue
        allowed = row.get("allowed") if isinstance(row, dict) else getattr(row, "allowed", None)
        requested_use = (
            row.get("requested_use") if isinstance(row, dict)
            else getattr(row, "requested_use", "")
        )
        requested_use_norm = _norm_enum_value(requested_use)
        if allowed is not True:
            reasons.append("decision_not_allowed")
            continue
        if requested_use_norm not in _TRAINING_REQUESTED_USES:
            reasons.append("decision_not_for_training")
            continue
        dataset = (
            row.get("dataset_artifact_ref") if isinstance(row, dict)
            else getattr(row, "dataset_artifact_ref", None)
        )
        artifact = (
            row.get("artifact_ref") if isinstance(row, dict)
            else getattr(row, "artifact_ref", None)
        )
        resolved = dataset or artifact
        if resolved:
            verified.add(str(resolved))

    for dataset_ref in manifest.dataset_artifact_refs:
        if dataset_ref not in verified:
            reasons.append("missing_rights_evidence")

    report.denial_reason_codes = sorted(set(reasons))
    report.eligible = not report.denial_reason_codes
    # Learning authority classes recorded from the manifest (never guessed).
    report.allowed_classes = sorted({
        _norm_enum_value(c) for c in manifest.learning_authority_classes
    })
    report.tenant_local_only = bool(
        set(report.allowed_classes) & TENANT_LOCAL_LEARNING_CLASSES
    ) and not (set(report.allowed_classes) & GENERALIZED_LEARNING_CLASSES)
    return report


# ═══════════════════════════════════════════════════════════════════════════
# Model revocation assessment (§40)
# ═══════════════════════════════════════════════════════════════════════════

def assess_model_revocation(
    model_ref: str,
    revoked_grant_ids: list[str],
    decisions: list[Any],
    *,
    reconstructable: Optional[bool] = None,
    quarantine_required: Optional[bool] = None,
    legal_issue: Optional[bool] = None,
    hard_conflict: Optional[bool] = None,
) -> ModelRevocationAssessment:
    """Pure model-revocation decision over the §40 vocabulary.

    ``decisions`` are model/training records (dicts or objects) each carrying
    ``model_ref``, ``training_grant_ids``, and optionally ``reconstructable``,
    ``quarantine_required``, ``legal_issue``, ``hard_conflict``. Positional
    keyword overrides let a caller state evidence directly.

    Ordering:
    * no affected / reconstructable model info for the revoked source →
      ``no_action_required``;
    * training data affected and weights reconstructable → ``retrain_required``
      (``model_quarantine_required`` when the model must stay available;
      ``blocked`` on a hard conflict; ``legal_review_required`` on a legal issue);
    * ambiguous reconstructability → ``evaluation_required`` / ``legal_review_required``.
    """
    revoked = {str(g) for g in revoked_grant_ids or []}
    reasons: list[str] = []

    affected = []
    for record in decisions or []:
        rec_model = (
            record.get("model_ref") if isinstance(record, dict)
            else getattr(record, "model_ref", None)
        )
        if model_ref and rec_model and _norm_enum_value(rec_model) != _norm_enum_value(model_ref):
            continue
        affected.append(record)

    if not affected:
        return ModelRevocationAssessment(
            model_ref=model_ref,
            state="no_action_required",
            reasons=["no_model_training_record_for_revoked_source"],
        )

    def _flag(record: Any, key: str, default: Optional[bool]) -> Optional[bool]:
        if default is not None:
            return default
        if isinstance(record, dict):
            raw = record.get(key)
            return raw if isinstance(raw, bool) else None
        raw = getattr(record, key, None)
        return raw if isinstance(raw, bool) else None

    # Does any affected record touch the revoked grants at training time?
    involved = False
    for record in affected:
        grant_ids = (
            record.get("training_grant_ids") if isinstance(record, dict)
            else getattr(record, "training_grant_ids", None)
        )
        if grant_ids and (revoked & {str(g) for g in grant_ids}):
            involved = True
    if not involved:
        return ModelRevocationAssessment(
            model_ref=model_ref,
            state="no_action_required",
            reasons=["training_data_unaffected_by_revoked_grants"],
        )

    recon = any(
        _flag(record, "reconstructable", reconstructable) is True for record in affected
    )
    recon_unknown = any(
        _flag(record, "reconstructable", reconstructable) is None for record in affected
    )
    quarantine = any(
        _flag(record, "quarantine_required", quarantine_required) is True for record in affected
    )
    legal = any(
        _flag(record, "legal_issue", legal_issue) is True for record in affected
    )
    conflict = any(
        _flag(record, "hard_conflict", hard_conflict) is True for record in affected
    )

    if recon:
        reasons.append("model_reconstructable_from_revoked_source")
        if conflict:
            return ModelRevocationAssessment(
                model_ref=model_ref, state="blocked",
                reasons=[*reasons, "hard_conflict"],
            )
        if quarantine:
            return ModelRevocationAssessment(
                model_ref=model_ref, state="model_quarantine_required",
                reasons=[*reasons, "model_served_quarantine_required"],
            )
        if legal:
            return ModelRevocationAssessment(
                model_ref=model_ref, state="legal_review_required",
                reasons=[*reasons, "legal_obligation_conflict"],
            )
        return ModelRevocationAssessment(
            model_ref=model_ref, state="retrain_required",
            reasons=[*reasons, "training_data_affected"],
        )

    if recon_unknown:
        reasons.append("reconstructability_ambiguous")
        if legal:
            return ModelRevocationAssessment(
                model_ref=model_ref, state="legal_review_required",
                reasons=[*reasons, "legal_obligation_conflict"],
            )
        return ModelRevocationAssessment(
            model_ref=model_ref, state="evaluation_required",
            reasons=[*reasons, "requires_evaluation"],
        )

    # Training data was involved but no retained model info is reconstructable
    # to the revoked source.
    return ModelRevocationAssessment(
        model_ref=model_ref,
        state="no_action_required",
        reasons=["no_retained_model_info_reconstructable"],
    )


__all__ = [
    "CONTRIBUTED_MODEL_TRAINING",
    "GENERALIZED_LEARNING_CLASSES",
    "LEARNING_CLASSES",
    "LearningEligibilityReport",
    "MODEL_REVOCATION_STATES",
    "ModelRevocationAssessment",
    "TENANT_LOCAL_LEARNING_CLASSES",
    "TrainingDataManifest",
    "assess_model_revocation",
    "model_training_eligibility",
    "validate_training_manifest",
]
