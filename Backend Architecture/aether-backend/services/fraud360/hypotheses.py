"""Fraud360 Phase-6 synthesis generator — deterministic hypothesis production.

This module is the first REAL producer of ``FraudHypothesis`` records: it reads
the fraud-synthesis authorities for a subject (risk360 assessments, fraud-network
memberships, flow-of-funds traces, fraud decisions) and projects typed,
evidence-grounded, suspicion-state hypotheses through the
:class:`~services.fraud360.contracts.FraudHypothesis` contract. Phase-4's
provider echoes hypotheses that already exist in the store; nothing before this
module synthesised NEW hypotheses from authorities.

Honesty contract (the no-silent-fraud-declaration rule)
-------------------------------------------------------

* Matching a ``FraudPattern`` is a *heuristic convergence*, never a probability.
  :func:`evaluate_pattern` reports *which* real alignment channels fired
  (matched network types / member roles / family signals) and which canonical
  evidence types back the match — it never invents a numeric likelihood.
* A generated hypothesis is always in ``candidate`` state with a claim state
  drawn ONLY from the suspicion vocabulary (:data:`SUSPICION_CLAIM_STATES` —
  ``derived`` / ``inferred`` / ``predicted`` / ``correlated`` / ``attributed``).
  :func:`generate_hypotheses` refuses a factual ``claim_state``; reaching
  ``confirmed`` later is the state machine's job (factual claim + evidence).
* Determinism: hypothesis ids, synthesized ``EvidenceRef`` ids, and the run
  ``context_hash`` derive from CONTENT ONLY (tenant + subject + evidence +
  matched pattern). Identical evidence ⇒ identical ids/hash; changed evidence
  ⇒ a different, superseding identity. Run rows are minted per call
  (``new_run_id``) on the canonical ``computation_runs`` substrate.
* Zero matched patterns ⇒ an empty hypothesis list — nothing is fabricated.
* Absent authorities degrade to empty, never to an invented id. EvidenceRef ids
  are content-derived from real authority ids; no id is invented.

Every subsystem repository is imported lazily INSIDE the method that needs it so
importing this module never requires a database or a live stack.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Literal, Optional, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from shared.computation.context import ComputationContext
from shared.contracts_models.epistemic import EpistemicStatus

from services.fraud360.contracts import (
    FraudHypothesis,
    FraudHypothesisRun,
    FraudHypothesisState,
    SUSPICION_CLAIM_STATES,
)
from services.fraud360.patterns import FRAUD_PATTERNS
from services.operational_intelligence.models import EvidenceRef
from services.risk360.contracts import RiskAssessment

#: computation_runs ``definition_id`` this synthesis writes under.
SYNTHESIS_DEFINITION_ID = "fraud360.hypothesis"
SYNTHESIS_DEFINITION_VERSION = "1"

#: Content-derived EvidenceRef ``source`` tags (one per synthesis authority).
SOURCE_NETWORKS = "fraud360:networks"
SOURCE_FLOW_TRACE = "fraud360:flow_trace"
SOURCE_DECISIONS = "fraud360:decisions"
SOURCE_ASSESSMENTS = "risk360:assessments"
SOURCE_ACTIVITY = "fraud360:activity"

#: Evidence types a real authority can ground, keyed by authority (honest map).
_AUTHORITY_EVIDENCE_TYPES: dict[str, tuple[str, ...]] = {
    "networks": ("relationship", "entity"),  # a fraud-network membership
    "flow_trace": ("transaction",),  # a flow-of-funds trace
    "decisions": ("model_output", "event"),  # a fraud-engine decision over events
    "assessments": ("annotation",),  # a risk360 aggregation over observations
    "activity": ("event",),  # an ordered behavior-sequence family
}

#: Per-pattern family semantics — keyword vocabulary that aligns a decision
#: signal / flow trace pattern tag / activity family / risk dimension to a
#: Day-1 pattern family when the fraud-network taxonomy does not (honest,
#: documented heuristic convergence; never a numeric likelihood).
_FAMILY_SIGNAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "promotion_abuse": ("promotion", "campaign_abuse", "beneficiary_velocity"),
    "referral_abuse": ("referral", "referee", "self_referral"),
    "synthetic_identity": ("synthetic", "identity_fabrication"),
    "account_takeover": ("account_takeover", "ato", "compromised_account", "login_anomaly"),
    "payment_fraud": ("payment_fraud", "card_testing", "stolen_card", "chargeback_precursor"),
    "refund_chargeback_abuse": ("chargeback", "refund_abuse"),
    "bot_activity": ("bot", "automated", "headless", "bot_score"),
    "device_farm": ("device_farm", "emulator", "farmed_device", "shared_device"),
    "conversion_manipulation": ("conversion", "fake_click", "inorganic_traffic", "attribution"),
    "credential_abuse": ("credential_stuffing", "brute_force", "otp", "session_reuse"),
    "agent_abuse": ("agentic_delegation_abuse", "prompt_inject", "agent_abuse"),
    "counterparty_fraud": ("counterparty", "bad_merchant", "commerce_abuse"),
    "collusion": ("collusion", "coordinated", "ring"),
    "circular_value_flow": ("layering", "smurfing", "round_trip", "wash", "structuring", "cycle"),
    "wallet_abuse": ("wallet_abuse", "shared_wallet", "sweep", "cash_out", "collection"),
    "reward_extraction": ("reward_farming", "airdrop", "reward", "loyalty"),
}


def _canonical_sorted(values: Iterable[str]) -> list[str]:
    """Dedupe + sort string iterables (deterministic over unordered inputs)."""
    return sorted({v for v in values if v})


def _content_digest(payload: dict[str, Any]) -> str:
    """Stable 32-hex digest of a JSON payload (content-identity helper)."""
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:32]


class FraudHypothesisEvidence(BaseModel):
    """Typed, per-subject fraud-synthesis authorities the generator consumes.

    ``extra="forbid"``: a misspelled field raises instead of silently passing.
    Fields are the *real* authorities a reader can populate — typed risk360
    assessments plus derived fraud-network / flow / decision facts — NOT
    invented probabilities. Lists may be empty; an empty authority is an honest
    absence and never fabricates evidence.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    subject_kind: Literal["entity", "relationship", "agent"]
    subject_id: str

    #: risk360 assessments for the subject (typed canonical records).
    risk_assessments: list[RiskAssessment] = Field(default_factory=list)
    #: fraud-network membership authorities (ids + aligned taxonomy values).
    network_ids: list[str] = Field(default_factory=list)
    network_types: list[str] = Field(default_factory=list)
    network_member_roles: list[str] = Field(default_factory=list)
    #: flow-of-funds trace authorities anchored at the subject.
    flow_trace_ids: list[str] = Field(default_factory=list)
    flow_pattern_tags: list[str] = Field(default_factory=list)
    #: fraud-decision authorities for the subject.
    decision_ids: list[str] = Field(default_factory=list)
    decision_signals: list[str] = Field(default_factory=list)
    #: ordered-behavior (canonical activity) families (optional source).
    activity_families: list[str] = Field(default_factory=list)

    def _evidence_context(self) -> dict[str, Any]:
        """Category-tagged, order-normalized identity of the evidence."""
        return {
            "assessments": _canonical_sorted(
                a.assessment_id for a in self.risk_assessments
            ),
            "networks": _canonical_sorted(self.network_ids),
            "network_types": _canonical_sorted(self.network_types),
            "network_member_roles": _canonical_sorted(self.network_member_roles),
            "flow_traces": _canonical_sorted(self.flow_trace_ids),
            "flow_pattern_tags": _canonical_sorted(self.flow_pattern_tags),
            "decisions": _canonical_sorted(self.decision_ids),
            "decision_signals": _canonical_sorted(self.decision_signals),
            "activity_families": _canonical_sorted(self.activity_families),
        }


@dataclass(frozen=True)
class PatternMatch:
    """Honest result of scoring one ``FraudPattern`` against subject evidence.

    ``matched`` is a heuristic convergence (never a probability): it is True
    only when the pattern is enabled, its required canonical evidence types are
    all present, and at least one real alignment channel fired (matched network
    type AND role, OR a family signal). ``signal_names`` / ``evidence_type_hits``
    name the real channels that fired so the alignment is reviewable.
    """

    pattern_id: str
    matched: bool
    signal_names: tuple[str, ...] = ()
    network_type_hits: tuple[str, ...] = ()
    role_hits: tuple[str, ...] = ()
    family_signal_hits: tuple[str, ...] = ()
    evidence_type_hits: tuple[str, ...] = ()
    notes: str = ""


def _subject_evidence_types(evidence: FraudHypothesisEvidence) -> set[str]:
    """Canonical ``EvidenceType`` values the subject's authorities support."""
    hits: set[str] = set()
    if evidence.subject_kind == "relationship":
        hits.add("relationship")
    elif evidence.subject_kind in ("entity", "agent"):
        hits.add("entity")
    if evidence.network_ids:
        hits.update(_AUTHORITY_EVIDENCE_TYPES["networks"])
    if evidence.flow_trace_ids:
        hits.update(_AUTHORITY_EVIDENCE_TYPES["flow_trace"])
    if evidence.decision_ids:
        hits.update(_AUTHORITY_EVIDENCE_TYPES["decisions"])
    if evidence.risk_assessments:
        hits.update(_AUTHORITY_EVIDENCE_TYPES["assessments"])
    if evidence.activity_families:
        hits.update(_AUTHORITY_EVIDENCE_TYPES["activity"])
    return hits


def _family_signal_corpus(evidence: FraudHypothesisEvidence) -> list[str]:
    """Lower-cased decision signals + flow tags + activity families."""
    return [
        *[str(s).lower() for s in evidence.decision_signals],
        *[str(t).lower() for t in evidence.flow_pattern_tags],
        *[str(f).lower() for f in evidence.activity_families],
    ]


def _family_signal_hits(
    evidence: FraudHypothesisEvidence, keywords: Sequence[str]
) -> list[str]:
    """Signal/flow/activity tokens that carry a pattern-family keyword."""
    corpus = _family_signal_corpus(evidence)
    matched: set[str] = set()
    for token in corpus:
        for keyword in keywords:
            if keyword in token or token in keyword:
                matched.add(token)
    return sorted(matched)


def evaluate_pattern(
    evidence: FraudHypothesisEvidence,
    pattern: Any,
) -> PatternMatch:
    """Score whether one ``FraudPattern`` aligns to the subject's evidence.

    Alignment is reported honestly (never a numeric probability): the match
    requires the pattern's declared canonical evidence types to all be present
    AND at least one alignment channel — a matched ``network_type_ref`` paired
    with a matched ``member_role_ref`` (the fraud-network taxonomy is the
    strongest signal), OR a pattern-family keyword in the subject's decision
    signals / flow pattern tags / activity families.
    """
    from services.fraud360.contracts import FraudPattern  # local: type guard only

    if not isinstance(pattern, FraudPattern):
        return PatternMatch(
            pattern_id=str(getattr(pattern, "pattern_id", "?")),
            matched=False,
            notes="not a registered FraudPattern",
        )
    if not pattern.enabled:
        return PatternMatch(
            pattern_id=pattern.pattern_id,
            matched=False,
            notes="pattern disabled",
        )

    required = set(pattern.required_evidence_types)
    hits = _subject_evidence_types(evidence)
    required_present = required <= hits if required else True

    network_type_hits = _canonical_sorted(
        set(evidence.network_types) & set(pattern.network_type_refs)
    )
    role_hits = _canonical_sorted(
        set(evidence.network_member_roles) & set(pattern.member_role_refs)
    )
    family_hits = _family_signal_hits(
        evidence, _FAMILY_SIGNAL_KEYWORDS.get(pattern.pattern_id, ())
    )

    taxonomy_aligned = bool(network_type_hits and role_hits)
    matched = bool(required_present and (taxonomy_aligned or family_hits))
    evidence_hits = _canonical_sorted(hits & required)

    reasons: list[str] = []
    if matched:
        if taxonomy_aligned:
            reasons.append("fraud-network taxonomy aligned (type + role)")
        if family_hits:
            reasons.append("family signals aligned")
    elif not required_present:
        reasons.append(f"missing required evidence types: {sorted(required - hits)}")
    else:
        reasons.append(
            "no alignment to this pattern's fraud-network taxonomy or family signals"
        )

    return PatternMatch(
        pattern_id=pattern.pattern_id,
        matched=matched,
        signal_names=_canonical_sorted([*network_type_hits, *role_hits, *family_hits]),
        network_type_hits=tuple(network_type_hits),
        role_hits=tuple(role_hits),
        family_signal_hits=tuple(family_hits),
        evidence_type_hits=tuple(evidence_hits),
        notes="; ".join(reasons),
    )


def _synthesize_evidence_refs(
    evidence: FraudHypothesisEvidence,
    required_evidence_types: Sequence[str],
) -> list[EvidenceRef]:
    """Content-derived EvidenceRefs for the real authorities backing the match.

    One ref per real authority id whose evidence type the pattern requires.
    Ref ids are derived from the authority id (content-only); no id is invented.
    """
    required = set(required_evidence_types)
    refs: list[EvidenceRef] = []

    if {"relationship", "entity"} & required:
        for network_id in _canonical_sorted(evidence.network_ids):
            refs.append(
                EvidenceRef(
                    id=f"{SOURCE_NETWORKS}:{network_id}",
                    type="relationship",
                    source=SOURCE_NETWORKS,
                )
            )
    if "transaction" in required:
        for trace_id in _canonical_sorted(evidence.flow_trace_ids):
            refs.append(
                EvidenceRef(
                    id=f"{SOURCE_FLOW_TRACE}:{trace_id}",
                    type="transaction",
                    source=SOURCE_FLOW_TRACE,
                )
            )
    if {"model_output", "event"} & required:
        for decision_id in _canonical_sorted(evidence.decision_ids):
            refs.append(
                EvidenceRef(
                    id=f"{SOURCE_DECISIONS}:{decision_id}",
                    type="model_output",
                    source=SOURCE_DECISIONS,
                )
            )
    if "annotation" in required:
        for assessment in sorted(
            evidence.risk_assessments, key=lambda a: a.assessment_id
        ):
            refs.append(
                EvidenceRef(
                    id=f"{SOURCE_ASSESSMENTS}:{assessment.assessment_id}",
                    type="annotation",
                    source=SOURCE_ASSESSMENTS,
                )
            )
    return sorted(refs, key=lambda ref: (ref.id, ref.source))


def _hypothesis_id(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    pattern_id: str,
    evidence: FraudHypothesisEvidence,
) -> str:
    digest = _content_digest(
        {
            "tenant_id": tenant_id,
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "pattern_id": pattern_id,
            "evidence": evidence._evidence_context(),
        }
    )
    return f"fh_{digest}"


@dataclass(frozen=True)
class HypothesisGenerationResult:
    """One deterministic synthesis call: the run + the hypotheses it produced."""

    run: FraudHypothesisRun
    hypotheses: tuple[FraudHypothesis, ...]
    matches: tuple[PatternMatch, ...] = ()


def generate_hypotheses(
    *,
    evidence: FraudHypothesisEvidence,
    tenant_id: Optional[str] = None,
    subject_kind: Optional[str] = None,
    subject_id: Optional[str] = None,
    patterns: Optional[Sequence[Any]] = None,
    claim_state: EpistemicStatus | str = EpistemicStatus.DERIVED,
) -> HypothesisGenerationResult:
    """Deterministically synthesise suspicion-state hypotheses for a subject.

    Emits one ``candidate`` ``FraudHypothesis`` per matched pattern, grounded in
    content-derived ``EvidenceRef``(s) from the real authority ids. ``claim_state``
    must be a suspicion-band member — a factual claim state is refused here
    (escalation is the state machine's job). Zero matched patterns ⇒ an empty
    hypothesis list (never a fabricated hypothesis).
    """
    resolved_claim = EpistemicStatus(claim_state)
    if resolved_claim not in SUSPICION_CLAIM_STATES:
        raise ValueError(
            "generate_hypotheses only produces suspicion-state hypotheses; "
            "claim_state must be one of "
            f"{sorted(s.value for s in SUSPICION_CLAIM_STATES)}, got "
            f"{resolved_claim.value!r} (no-silent-escalation)."
        )

    tenant = tenant_id if tenant_id is not None else evidence.tenant_id
    kind = subject_kind if subject_kind is not None else evidence.subject_kind
    sid = subject_id if subject_id is not None else evidence.subject_id
    if tenant != evidence.tenant_id or kind != evidence.subject_kind or sid != evidence.subject_id:
        raise ValueError(
            "generate_hypotheses subject arguments must match the evidence "
            f"subject (got {tenant}/{kind}/{sid}, evidence "
            f"{evidence.tenant_id}/{evidence.subject_kind}/{evidence.subject_id})."
        )

    pattern_rows = list(patterns) if patterns is not None else list(FRAUD_PATTERNS)
    # Deterministic evaluation order regardless of caller ordering.
    pattern_rows.sort(key=lambda p: str(getattr(p, "pattern_id", "")))

    matches = [evaluate_pattern(evidence, pattern) for pattern in pattern_rows]

    produced: list[FraudHypothesis] = []
    for pattern, match in zip(pattern_rows, matches):
        if not match.matched:
            continue
        refs = _synthesize_evidence_refs(evidence, pattern.required_evidence_types)
        if not refs:
            # A matched pattern with NO real authority id to ground it must not
            # mint an evidence-less hypothesis (honest absence wins).
            continue
        hypothesis = FraudHypothesis(
            hypothesis_id=_hypothesis_id(
                tenant_id=tenant,
                subject_kind=kind,
                subject_id=sid,
                pattern_id=pattern.pattern_id,
                evidence=evidence,
            ),
            tenant_id=tenant,
            subject_kind=kind,  # type: ignore[arg-type]
            subject_id=sid,
            state=FraudHypothesisState.CANDIDATE,
            claim_state=resolved_claim,
            confidence=None,
            matched_pattern_ids=[pattern.pattern_id],
            materiality=None,
            evidence_refs=refs,
            risk_assessment_ids=_canonical_sorted(
                a.assessment_id for a in evidence.risk_assessments
            ),
            network_ids=_canonical_sorted(evidence.network_ids),
            flow_trace_ids=_canonical_sorted(evidence.flow_trace_ids),
            decision_ids=_canonical_sorted(evidence.decision_ids),
        )
        produced.append(hypothesis)

    grounded_pattern_ids = [
        hypothesis.matched_pattern_ids[0] for hypothesis in produced
    ]
    context_hash = _synthesis_context_hash(
        evidence=evidence,
        matched_pattern_ids=grounded_pattern_ids,
    )
    run = FraudHypothesisRun(
        tenant_id=tenant,
        context_hash=context_hash,
        definition_id=SYNTHESIS_DEFINITION_ID,
        hypothesis_count=len(produced),
    )
    produced = [
        hypothesis.model_copy(update={"run_id": run.run_id})
        for hypothesis in produced
    ]
    return HypothesisGenerationResult(
        run=run,
        hypotheses=tuple(produced),
        matches=tuple(matches),
    )


def _synthesis_context_hash(
    *,
    evidence: FraudHypothesisEvidence,
    matched_pattern_ids: Sequence[str],
) -> str:
    """Deterministic run identity: subject + sorted evidence + matched patterns.

    Mirrors the risk360 pipeline pattern — identical evidence + matched pattern
    set ⇒ identical ``context_hash``; a restatement (late data / changed
    evidence) changes the hash and therefore supersedes rather than silently
    overwrites.
    """
    context = ComputationContext(
        tenant_id=evidence.tenant_id,
        subject_type=evidence.subject_kind,
        subject_id=evidence.subject_id,
        grain="subject",
        dimensions={
            "fraud360": {
                "evidence": evidence._evidence_context(),
                "patterns": sorted(matched_pattern_ids),
            }
        },
        model_version="fraud360.hypothesis.1",
    )
    return context.context_hash()


# ═══════════════════════════════════════════════════════════════════════════
# Materiality rubric (honest, evidence-backed only)
# ═══════════════════════════════════════════════════════════════════════════

#: Documented exposure-magnitude rubric (USD value → 0..1 contribution).
_EXPOSURE_BANDS: tuple[tuple[float, float], ...] = (
    (1_000_000.0, 0.30),
    (100_000.0, 0.25),
    (10_000.0, 0.20),
    (1_000.0, 0.15),
    (100.0, 0.10),
)


def _exposure_contribution(exposure_usd: float) -> float:
    """Monotonic USD-magnitude contribution, capped at 0.30 (documented rubric)."""
    for threshold, contribution in _EXPOSURE_BANDS:
        if exposure_usd >= threshold:
            return contribution
    return 0.05 if exposure_usd > 0 else 0.0


def hypothesis_materiality(
    hypothesis: FraudHypothesis,
    *,
    risk_assessment: Optional[RiskAssessment] = None,
    exposure_usd: Optional[float] = None,
) -> Optional[float]:
    """Honest, evidence-backed materiality estimate in [0, 1], else None.

    Rubric (documented, deterministic):

    * matched patterns — +0.15 each, capped at +0.45 (3+ add nothing);
    * a provided risk360 ``risk_assessment`` — +0.25 scaled by the strongest
      value-bearing component score in its vector (never a fabricated zero);
    * provided ``exposure_usd`` magnitude — +0.05..+0.30 via
      :data:`_EXPOSURE_BANDS`.

    Returns None when nothing backs an estimate (no matched pattern, no risk
    assessment, no exposure) — an unscored hypothesis is never silently scored
    as low-severity. This does NOT call the comparison-plane materiality module
    (that is downstream's job).
    """
    matched_count = len(hypothesis.matched_pattern_ids or [])
    if matched_count == 0 and risk_assessment is None and exposure_usd is None:
        return None

    score = 0.0
    if matched_count:
        score += min(0.45, matched_count * 0.15)

    if risk_assessment is not None:
        best = max(
            (
                float(c.score)
                for c in risk_assessment.vector.components
                if c.score is not None
            ),
            default=None,
        )
        if best is not None:
            score += 0.25 * best

    if exposure_usd is not None and exposure_usd > 0:
        score += _exposure_contribution(float(exposure_usd))

    return round(min(1.0, score), 4)


# ═══════════════════════════════════════════════════════════════════════════
# Evidence reader seam
# ═══════════════════════════════════════════════════════════════════════════

class FraudEvidenceReader(Protocol):
    """Canonical fraud-synthesis read seam for one subject.

    Implementations are tenant-scoped and MUST degrade per-authority to empty on
    any store error (never raise, never fabricate). ``read_evidence`` folds the
    raw authorities into the typed :class:`FraudHypothesisEvidence` the
    generator consumes.
    """

    async def risk_assessments(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[RiskAssessment]: ...

    async def network_memberships(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]: ...

    async def flow_traces(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]: ...

    async def fraud_decisions(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]: ...

    async def activity_families(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[str]: ...

    async def read_evidence(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> FraudHypothesisEvidence: ...


def _default_profile_resolver(subject_kind: str, subject_id: str) -> Optional[str]:
    """Default: subject-to-profile mapping is NOT available → activity degrades.

    An honest absence (never a fabricated family). Operators who can map a
    subject to a canonical-activity profile pass their own resolver.
    """
    return None


class RepositoryFraudEvidenceReader:
    """Default canonical reader over the real fraud/risk authorities.

    Reads the tenant's ``risk_assessments``, ``fraud_network_members`` /
    ``fraud_networks``, ``flow_traces``, and ``fraud_decisions`` repositories
    defensively; every authority degrades to empty on a store error (never
    raises). Flow traces and fraud-network memberships are only resolvable for
    entity-kind subjects — other subject kinds degrade those authorities
    honestly. Ordered-behavior activity needs a subject→profile mapping; the
    default resolver provides none (see :data:`_default_profile_resolver`).
    """

    def __init__(
        self,
        *,
        profile_resolver: Optional[Callable[[str, str], Optional[str]]] = None,
    ) -> None:
        self._profile_resolver = profile_resolver or _default_profile_resolver

    async def risk_assessments(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[RiskAssessment]:
        try:
            from services.risk360.store import RiskAssessmentRepository

            rows = await RiskAssessmentRepository().list_by_subject(
                tenant_id, subject_kind, subject_id, limit=20
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        parsed: list[RiskAssessment] = []
        for row in rows:
            try:
                parsed.append(RiskAssessment(**row))
            except Exception:  # noqa: BLE001 - one malformed row -> skip, never raise
                continue
        return parsed

    async def network_memberships(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]:
        if subject_kind != "entity":
            # Network membership is an entity-graph fact; other subject kinds
            # degrade honestly (no invented membership).
            return []
        try:
            from repositories.repos import (
                FraudNetworkMemberRepository,
                FraudNetworkRepository,
            )

            rows = await FraudNetworkMemberRepository().list_by_entity(
                subject_id, tenant_id
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        enriched: list[dict[str, Any]] = []
        for row in rows:
            if row.get("tenant_id") != tenant_id or row.get("entity_id") != subject_id:
                continue
            entry = dict(row)
            try:
                network = await FraudNetworkRepository().get(row["network_id"])
                if network is not None and network.get("tenant_id") == tenant_id:
                    entry["network_type"] = network.get("network_type")
            except Exception:  # noqa: BLE001 - one network unreadable -> keep the member
                entry["network_type"] = None
            enriched.append(entry)
        return enriched

    async def flow_traces(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]:
        if subject_kind != "entity":
            return []
        try:
            from repositories.repos import FlowTraceRepository

            rows = await FlowTraceRepository().find_many(
                {"tenant_id": tenant_id, "anchor_entity_id": subject_id}, limit=20
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        return [
            row
            for row in rows
            if row.get("tenant_id") == tenant_id
            and row.get("anchor_entity_id") == subject_id
        ]

    async def fraud_decisions(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[dict[str, Any]]:
        try:
            from repositories.repos import FraudDecisionRepository

            repo = FraudDecisionRepository()
            if subject_kind == "entity":
                rows = await repo.list_for_entity(tenant_id, subject_id, limit=20)
            else:
                rows = await repo.find_many(
                    {
                        "tenant_id": tenant_id,
                        "subject_type": subject_kind,
                        "subject_id": subject_id,
                    },
                    limit=20,
                )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        return [row for row in rows if row.get("tenant_id") == tenant_id]

    async def activity_families(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> list[str]:
        profile_id = self._profile_resolver(subject_kind, subject_id)
        if not profile_id:
            return []
        try:
            from services.measurement.repositories.activity_repo import ActivityRepository

            rows = await ActivityRepository().list_by_profile(
                tenant_id, profile_id, limit=200
            )
        except Exception:  # noqa: BLE001 - backing source unavailable -> degrade
            return []
        return _canonical_sorted(
            str(row["activity_family"])
            for row in rows
            if row.get("tenant_id") == tenant_id and row.get("activity_family")
        )

    async def read_evidence(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> FraudHypothesisEvidence:
        """Fold the raw authorities into a typed evidence bundle (never raises)."""
        assessments = await self.risk_assessments(
            tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
        )
        memberships = await self.network_memberships(
            tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
        )
        flows = await self.flow_traces(
            tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
        )
        decisions = await self.fraud_decisions(
            tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
        )
        activity_families = await self.activity_families(
            tenant_id=tenant_id, subject_kind=subject_kind, subject_id=subject_id
        )

        return FraudHypothesisEvidence(
            tenant_id=tenant_id,
            subject_kind=subject_kind,  # type: ignore[arg-type]
            subject_id=subject_id,
            risk_assessments=assessments,
            network_ids=_canonical_sorted(
                row.get("network_id")
                for row in memberships
                if row.get("network_id")
            ),
            network_types=_canonical_sorted(
                row.get("network_type")
                for row in memberships
                if row.get("network_type")
            ),
            network_member_roles=_canonical_sorted(
                row.get("role") for row in memberships if row.get("role")
            ),
            flow_trace_ids=_canonical_sorted(
                row.get("id") for row in flows if row.get("id")
            ),
            flow_pattern_tags=_canonical_sorted(
                tag for row in flows for tag in (row.get("pattern_tags") or [])
            ),
            decision_ids=_canonical_sorted(
                row.get("decision_id")
                for row in decisions
                if row.get("decision_id")
            ),
            decision_signals=_canonical_sorted(
                signal
                for row in decisions
                for signal in (row.get("signal_types") or [])
            ),
            activity_families=activity_families,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Persistence + lifecycle helpers (fraud360's ONLY write path)
# ═══════════════════════════════════════════════════════════════════════════

def _record_id(tenant_id: str, hypothesis_id: str) -> str:
    """Tenant-qualified repository id (mirrors ``FraudHypothesisRepository``)."""
    return f"{tenant_id}:{hypothesis_id}"


async def persist_hypotheses(
    result: HypothesisGenerationResult,
    *,
    tenant_id: str,
    repo: Optional[Any] = None,
    runs_repo: Optional[Any] = None,
) -> HypothesisGenerationResult:
    """Persist one synthesis run end-to-end (the fraud360 write path).

    Writes:

    * ONE ``computation_runs`` row via ``ComputedResultsRepository.insert_run``
      (``definition_id: fraud360.hypothesis``, deterministic ``context_hash``);
      identical evidence mints a FRESH run whose ``data.supersedes_run_id``
      records the prior run for the same grounded hypotheses (a restatement
      never silently overwrites);
    * each generated hypothesis via ``FraudHypothesisRepository.create`` —
      an id that already exists is skipped (already-evaluated content; never
      overwritten).

    All repositories are injectable; defaults construct the local JSONB stores /
    in-memory computation substrate.
    """
    from services.computation.repositories import ComputedResultsRepository
    from services.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    runs_repo = runs_repo or ComputedResultsRepository()

    run = result.run
    prior_run_id: Optional[str] = None
    for hypothesis in result.hypotheses:
        prior = await repo.get(tenant_id, hypothesis.hypothesis_id)
        if prior is not None and prior.run_id not in (None, run.run_id):
            prior_run_id = prior.run_id
            break

    await runs_repo.insert_run(
        {
            "run_id": run.run_id,
            "tenant_id": tenant_id,
            "definition_id": run.definition_id or SYNTHESIS_DEFINITION_ID,
            "definition_version": SYNTHESIS_DEFINITION_VERSION,
            "context_hash": run.context_hash,
            "status": "completed",
            "data": {
                "definition_id": run.definition_id or SYNTHESIS_DEFINITION_ID,
                "definition_version": SYNTHESIS_DEFINITION_VERSION,
                "subject_kind": next(
                    (h.subject_kind for h in result.hypotheses), None
                ),
                "subject_id": next((h.subject_id for h in result.hypotheses), None),
                "hypothesis_ids": [h.hypothesis_id for h in result.hypotheses],
                "supersedes_run_id": prior_run_id,
            },
        }
    )

    stored: list[FraudHypothesis] = []
    for hypothesis in result.hypotheses:
        existing = await repo.get(tenant_id, hypothesis.hypothesis_id)
        if existing is None:
            stored.append(await repo.create(tenant_id, hypothesis))
        else:
            # Already-evaluated content: never overwrite, never duplicate.
            stored.append(existing)

    return HypothesisGenerationResult(
        run=run,
        hypotheses=tuple(stored),
        matches=result.matches,
    )


async def supersede_hypothesis(
    tenant_id: str,
    hypothesis_id: str,
    *,
    replacement_hypothesis_id: Optional[str] = None,
    reason: Optional[str] = None,
    evidence_refs: Optional[list] = None,
    repo: Optional[Any] = None,
) -> Optional[FraudHypothesis]:
    """Mark a hypothesis ``superseded`` (legal extra via the state machine).

    When ``replacement_hypothesis_id`` is supplied the superseded record's
    ``superseded_by_hypothesis_id`` and (if present) the replacement's
    ``supersedes_hypothesis_id`` are linked. ``reason`` is accepted for operator
    audit but is NOT persisted — the ``FraudHypothesis`` contract is
    ``extra="forbid"`` and has no free-text field; annotations belong on the
    case/finding plane, never smuggled into the fraud record.
    """
    from services.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    updated = await repo.update_state(
        tenant_id,
        hypothesis_id,
        FraudHypothesisState.SUPERSEDED,
        evidence_refs=evidence_refs,
    )
    if updated is None:
        return None
    if replacement_hypothesis_id:
        await repo.update(
            _record_id(tenant_id, hypothesis_id),
            {"superseded_by_hypothesis_id": replacement_hypothesis_id},
        )
        replacement = await repo.get(tenant_id, replacement_hypothesis_id)
        if replacement is not None:
            await repo.update(
                _record_id(tenant_id, replacement_hypothesis_id),
                {"supersedes_hypothesis_id": hypothesis_id},
            )
    return await repo.get(tenant_id, hypothesis_id)


async def dispute_hypothesis(
    tenant_id: str,
    hypothesis_id: str,
    *,
    reason: Optional[str] = None,
    evidence_refs: Optional[list] = None,
    repo: Optional[Any] = None,
) -> Optional[FraudHypothesis]:
    """Mark a hypothesis ``disputed`` (legal extra; evidence optional)."""
    from services.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    return await repo.update_state(
        tenant_id,
        hypothesis_id,
        FraudHypothesisState.DISPUTED,
        evidence_refs=evidence_refs,
    )


async def mark_stale(
    tenant_id: str,
    hypothesis_id: str,
    *,
    reason: Optional[str] = None,
    evidence_refs: Optional[list] = None,
    repo: Optional[Any] = None,
) -> Optional[FraudHypothesis]:
    """Mark a hypothesis ``stale`` (legal extra; evidence optional)."""
    from services.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    return await repo.update_state(
        tenant_id,
        hypothesis_id,
        FraudHypothesisState.STALE,
        evidence_refs=evidence_refs,
    )


async def correct_hypothesis(
    tenant_id: str,
    hypothesis_id: str,
    *,
    reason: Optional[str] = None,
    claim_state: Optional[EpistemicStatus | str] = None,
    evidence_refs: Optional[list] = None,
    repo: Optional[Any] = None,
) -> Optional[FraudHypothesis]:
    """Mark a hypothesis ``corrected`` (legal extra; evidence optional)."""
    from services.fraud360.store import FraudHypothesisRepository

    repo = repo or FraudHypothesisRepository()
    return await repo.update_state(
        tenant_id,
        hypothesis_id,
        FraudHypothesisState.CORRECTED,
        claim_state=claim_state,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "FraudEvidenceReader",
    "FraudHypothesisEvidence",
    "HypothesisGenerationResult",
    "PatternMatch",
    "RepositoryFraudEvidenceReader",
    "SOURCE_ACTIVITY",
    "SOURCE_ASSESSMENTS",
    "SOURCE_DECISIONS",
    "SOURCE_FLOW_TRACE",
    "SOURCE_NETWORKS",
    "SYNTHESIS_DEFINITION_ID",
    "SYNTHESIS_DEFINITION_VERSION",
    "correct_hypothesis",
    "dispute_hypothesis",
    "evaluate_pattern",
    "generate_hypotheses",
    "hypothesis_materiality",
    "mark_stale",
    "persist_hypotheses",
    "supersede_hypothesis",
]
