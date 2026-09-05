"""Risk360 producer→RiskSignal convergence adapters (Phase 5).

The shipped risk/fraud subsystems emit detector artifacts — fraud signals,
fraud-network evidence, device risk states, IP/geo lookups, behavioral scans,
and trust vectors. None of them speaks the canonical
:class:`~services.risk360.contracts.RiskSignal` vocabulary, so this module is
the **convergence seam**: each :func:`signal_from_*` adapter maps one producer
artifact into typed ``RiskSignal``(s) with a REGISTERED risk dimension
(``RISK_DIMENSION_KEYS``), an honest ``claim_state`` (heuristic/detector output
is ``derived``/``inferred`` — never ``verified``/``confirmed``), a reused
:class:`EvidenceRef`, and a detector version ONLY when the producer actually
exposes one (never fabricated).

Scoring honesty (mirrors the Risk360/Fraud360 SoT §4 discipline):

* a 0–100 detector score scales to 0–1 (``score / 100``) and a 0–1 score
  passes through, but ONLY when the producer flags the numeric as calibrated;
* an absent OR uncalibrated numeric yields ``score=None`` — never an invented
  probability. ``RiskSignal.value`` stays ``None`` unless the producer gives a
  genuine raw magnitude;
* a producer with no numeric at all (device risk state, network evidence)
  yields ``score=None`` with an honest derived/inferred claim;
* every emitted ``risk_dimension`` is a member of ``RISK_DIMENSION_KEYS`` (the
  contract validator enforces it; these adapters assert it too).

Producer dependencies are imported LAZILY inside functions so importing this
module never requires a subsystem backend. ``signals_from_evidence_bundle`` runs
the dispatcher over a caller-supplied, ``extra="forbid"``
:class:`RiskEvidenceBundle` so the Phase-5 pipeline can be exercised without
live subsystem state.

Signal ids are derived from CONTENT ONLY (no uuid/clock), so identical evidence
⇒ identical ``signal_id`` ⇒ reproducible runs.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.contracts_models.epistemic import EpistemicStatus
from services.operational_intelligence.models import EvidenceRef

from .contracts import RiskContract, RiskSignal
from .dimensions import RISK_DIMENSION_KEYS

#: Producer keys the dispatcher understands.
KNOWN_PRODUCERS: frozenset[str] = frozenset(
    {"fraud", "fraud_network", "device_risk", "geo", "behavioral", "trust"}
)

# ═══════════════════════════════════════════════════════════════════════════
# Producer → registered risk dimension convergence maps
#
# These are the convergence-time decisions of Phase 5: each producer artifact is
# mapped to the canonical Risk360 dimension it feeds. Every target is a member
# of RISK_DIMENSION_KEYS (asserted below for the constant maps).
# ═══════════════════════════════════════════════════════════════════════════

#: Real-time fraud signal names (services/fraud/signals.py) → risk dimension.
_FRAUD_SIGNAL_DIMENSIONS: Mapping[str, str] = {
    "bot_detection": "fraud",
    "sybil_detection": "relationship",
    "velocity": "behavioral",
    "wallet_age": "identity",
    "geographic": "geographic",
    "behavioral": "behavioral",
    "device_fingerprint": "infrastructure",
    "transaction_pattern": "transaction",
}

#: Fallback dimension for a fraud signal name we do not have a row for. All
#: fraud signals are deception/abuse indicators about the subject → ``fraud``.
_FRAUD_SIGNAL_DEFAULT_DIMENSION = "fraud"

#: Fraud-network detector signal names (services/fraud_networks/detectors.py) →
#: risk dimension. The graph-link detectors converge onto the relationship
#: dimension; agentic-delegation abuse and commerce abuse name their own dims.
_FRAUD_NETWORK_DIMENSIONS: Mapping[str, str] = {
    "shared_device": "relationship",
    "shared_ip": "relationship",
    "shared_wallet": "relationship",
    "circular_transfer": "relationship",
    "split_merge": "relationship",
    "reward_farming": "relationship",
    "agentic_delegation_abuse": "agentic",
    "commerce_abuse": "fraud",
}

#: Device risk is not a risk dimension (24-dimension set has no "device");
#: the Risk360 ``infrastructure`` dimension explicitly owns
#: "Device/infrastructure/network fingerprints, hygiene, and proxy/automation
#: indicators", so device risk converges there.
DEVICE_RISK_DIMENSION = "infrastructure"

#: Geo enrichment converges onto the ``geographic`` dimension (location/IP/geo).
GEO_DIMENSION = "geographic"

#: Behavioral-scan family keys (services/behavioral/engines.py scan dict) →
#: risk dimension. Approximate convergence mapping (documented as such).
_BEHAVIORAL_FAMILY_DIMENSIONS: Mapping[str, str] = {
    "intent_residue": "behavioral",
    "wallet_friction": "payment",
    "identity_delta": "identity",
    "pre_post_continuity": "temporal",
    "sequence_scars": "behavioral",
    "source_shadow": "data_quality",
    "reward_near_miss": "campaign",
    "social_chain_lag": "relationship",
    "cex_dex_transition": "transaction",
    "behavioral_twin": "population",
}

#: Trust-vector dimension (shared/scoring/trust_vector.py) → risk dimension.
#: ``automation_likelihood`` is naturally inverted for TRUST (high automation =
#: less trustworthy) but risk-positive here (high automation = higher risk), so
#: it is also excluded from the trust→risk inversion list.
_TRUST_DIMENSION_MAP: Mapping[str, str] = {
    "identity_assurance": "identity",
    "transaction_integrity": "transaction",
    "behavioral_reliability": "behavioral",
    "automation_likelihood": "agentic",
    "source_coverage": "data_quality",
    "evidence_recency": "temporal",
}

#: Trust dimensions for which a HIGH value is a LOW risk posture. Automation
#: likelihood is excluded (high automation is itself the risk).
_TRUST_RISK_INVERTED: frozenset[str] = frozenset(
    {
        "identity_assurance",
        "transaction_integrity",
        "behavioral_reliability",
        "source_coverage",
        "evidence_recency",
    }
)

for _dim_map in (
    _FRAUD_SIGNAL_DIMENSIONS,
    _FRAUD_NETWORK_DIMENSIONS,
    _BEHAVIORAL_FAMILY_DIMENSIONS,
    _TRUST_DIMENSION_MAP,
):
    for _mapped in _dim_map.values():
        if _mapped not in RISK_DIMENSION_KEYS:
            raise AssertionError(
                f"convergence map references unregistered risk dimension {_mapped!r}"
            )
if DEVICE_RISK_DIMENSION not in RISK_DIMENSION_KEYS or GEO_DIMENSION not in RISK_DIMENSION_KEYS:
    raise AssertionError("device/geo convergence dimensions must be registered")

del _dim_map, _mapped  # do not leak loop vars


# ═══════════════════════════════════════════════════════════════════════════
# Deterministic content ids (no uuid/clock) — reproducible-run substrate.
# ═══════════════════════════════════════════════════════════════════════════

def _content_hex(payload: Mapping[str, Any]) -> str:
    """sha256 over sorted-json of ``payload`` (mirrors context_hash style)."""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def _signal_id(*, producer: str, **content: Any) -> str:
    return f"rsk_{_content_hex({'producer': producer, **content})[:24]}"


def _evidence_id(prefix: str, **content: Any) -> str:
    return f"ev_{_content_hex({prefix: True, **content})[:20]}"


# ═══════════════════════════════════════════════════════════════════════════
# Artifact helpers (dict OR typed-object tolerant)
# ═══════════════════════════════════════════════════════════════════════════

def _field(artifact: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` off a dict or an object artifact."""
    if isinstance(artifact, Mapping):
        return artifact.get(name, default)
    return getattr(artifact, name, default)


def _as_observed_at(observed_at: Optional[datetime], fallback: Any = None) -> Optional[str]:
    """ISO string for EvidenceRef.observedAt, or None (never fabricated)."""
    if observed_at is not None:
        return observed_at.isoformat()
    if fallback is not None:
        return str(fallback)
    return None


def _scale_score(value: Any, *, scale: int) -> Optional[float]:
    """Scale ``value`` in ``scale`` units to 0–1 (or None when absent)."""
    if value is None:
        return None
    try:
        scaled = float(value) / float(scale)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, scaled))


#: A detector numeric is usable as a risk score only when the producer flags it
#: calibrated. Uncalibrated heuristics are real output but not a probability,
#: so they stay ``score=None`` (never a fabricated calibration). Works on a
#: ``SignalResult`` dataclass OR a plain dict artifact.
def _calibrated_score(artifact: Any, *, scale: int) -> Optional[float]:
    calibrated = _field(artifact, "calibrated")
    if calibrated is not True:
        return None
    return _scale_score(_field(artifact, "score"), scale=scale)


# ═══════════════════════════════════════════════════════════════════════════
# Evidence bundle (extra="forbid") — lets the pipeline run without live state
# ═══════════════════════════════════════════════════════════════════════════

def _refs_from_network_signal(signal_name: str) -> Optional[EvidenceRef]:
    """The EvidenceRef type the durable-decisions layer assigns this signal."""
    # Mirrors services/fraud_networks/evidence.py SIGNAL_TO_EVIDENCE_TYPE.
    relationship_like = {
        "shared_device",
        "shared_ip",
        "shared_wallet",
        "agentic_delegation_abuse",
    }
    if signal_name in relationship_like:
        return EvidenceRef(id="", type="relationship", source="")
    return EvidenceRef(id="", type="transaction", source="")


class FraudNetworkSignalEvidence(BaseModel):
    """One fraud-network detector output row (EvidenceTuple as a dict).

    Mirror of ``services/fraud_networks/detectors.EvidenceTuple``
    ``(signal_name, entity_ids, detail_dict)`` serialized for the bundle.
    """

    model_config = ConfigDict(extra="forbid")

    signal_name: str
    entity_ids: list[str] = Field(default_factory=list)
    detail: dict[str, Any] = Field(default_factory=dict)


class RiskEvidenceBundle(RiskContract):
    """Caller-supplied evidence snapshot the pipeline converges.

    Each field is the raw producer artifact (dict snapshot of the typed output)
    for one producer seam. ``extra="forbid"`` keeps a misspelled producer field
    from silently passing. The pipeline runs :func:`adapt_producer_signal` over
    every present field without touching live subsystem state.
    """

    fraud_result: Optional[dict[str, Any]] = None
    fraud_network_signals: list[FraudNetworkSignalEvidence] = Field(default_factory=list)
    device_risk: Optional[dict[str, Any]] = None
    geo_lookup: Optional[dict[str, Any]] = None
    behavioral_scan: Optional[dict[str, Any]] = None
    trust_vector: Optional[dict[str, Any]] = None


# ═══════════════════════════════════════════════════════════════════════════
# Adapters
# ═══════════════════════════════════════════════════════════════════════════

def signal_from_fraud_result(
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt a :class:`services.fraud.engine.FraudResult` into RiskSignals.

    One RiskSignal per triggered detector signal. Only a *calibrated* signal
    score is scaled (0–100 → 0–1); uncalibrated heuristics stay ``score=None``
    with an honest ``derived`` claim. The fraud signals themselves are heuristic
    detector output, so the claim state is ``derived`` — never verified.
    """
    audit_id = _field(artifact, "audit_id")
    timestamp = _field(artifact, "timestamp")
    entries = _field(artifact, "signals", []) or []
    signals: list[RiskSignal] = []
    for index, entry in enumerate(entries):
        # A SignalResult dataclass or a dict (engine.to_dict() drops calibrated;
        # a dict with no 'calibrated' key is therefore treated uncalibrated).
        triggered = _field(entry, "triggered")
        if isinstance(entry, Mapping) and "triggered" not in entry:
            triggered = True
        if not triggered:
            continue
        name = _field(entry, "name")
        score = _calibrated_score(entry, scale=100)
        dimension = _FRAUD_SIGNAL_DIMENSIONS.get(
            str(name), _FRAUD_SIGNAL_DEFAULT_DIMENSION
        )
        evidence = EvidenceRef(
            id=_evidence_id(
                "fraud", audit_id=audit_id, name=name, index=index, tenant_id=tenant_id
            ),
            type="model_output",
            source="fraud.signals",
            observedAt=_as_observed_at(observed_at, timestamp),
        )
        signals.append(
            RiskSignal(
                signal_id=_signal_id(
                    producer="fraud",
                    tenant_id=tenant_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    dimension=dimension,
                    source="fraud.signals",
                    name=name,
                    score=score,
                    index=index,
                ),
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                risk_dimension=dimension,
                claim_state=EpistemicStatus.DERIVED,
                evidence_refs=[evidence],
                source="fraud.signals",
                observed_at=observed_at,
                score=score,
            )
        )
    return signals


def _normalize_network_evidence(
    evidence: Any,
) -> list[dict[str, Any]]:
    """Normalize raw EvidenceTuples / FraudNetworkSignalEvidence / dicts."""
    normalized: list[dict[str, Any]] = []
    for entry in evidence or []:
        if isinstance(entry, FraudNetworkSignalEvidence):
            normalized.append(
                {
                    "signal_name": entry.signal_name,
                    "entity_ids": list(entry.entity_ids),
                    "detail": dict(entry.detail),
                }
            )
            continue
        if isinstance(entry, tuple) and len(entry) == 3:
            normalized.append(
                {
                    "signal_name": entry[0],
                    "entity_ids": list(entry[1] or []),
                    "detail": dict(entry[2] or {}),
                }
            )
            continue
        if isinstance(entry, Mapping):
            normalized.append(
                {
                    "signal_name": entry.get("signal_name"),
                    "entity_ids": list(entry.get("entity_ids") or []),
                    "detail": dict(entry.get("detail") or {}),
                }
            )
            continue
        raise TypeError(
            f"unrecognized fraud-network evidence entry {type(entry).__name__!r}"
        )
    return normalized


def _network_signal_confidence(signal_name: str) -> Optional[float]:
    """The operational detector confidence (mirrors fraud_networks/evidence.py).

    Read lazily from the existing mapping so we never fabricate a number and
    never maintain a second copy. Returns ``None`` when unavailable.
    """
    try:
        from services.fraud_networks import evidence as _fraud_net_evidence  # lazy
        return getattr(_fraud_net_evidence, "_SIGNAL_CONFIDENCE", {}).get(signal_name)
    except Exception:  # noqa: BLE001 - detector-confidence lookup is best-effort
        return None


def signals_from_fraud_network_evidence(
    evidence: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt fraud-network detector output into RiskSignals.

    Accepts a list of ``EvidenceTuple`` triples, :class:`FraudNetworkSignalEvidence`
    rows, or plain dicts. Network evidence carries NO score — each emitted
    signal reports an inferred link-structure anomaly (``score=None``), and the
    detector's own confidence is carried on the reused EvidenceRef.
    """
    rows = _normalize_network_evidence(evidence)
    signals: list[RiskSignal] = []
    for index, row in enumerate(rows):
        signal_name = str(row.get("signal_name") or "")
        if not signal_name:
            continue
        dimension = _FRAUD_NETWORK_DIMENSIONS.get(signal_name, "relationship")
        confidence = _network_signal_confidence(signal_name)
        evidence_type = _refs_from_network_signal(signal_name).type
        ref = EvidenceRef(
            id=_evidence_id(
                "fraud_network",
                signal_name=signal_name,
                index=index,
                tenant_id=tenant_id,
            ),
            type=evidence_type,  # type: ignore[arg-type]
            source="fraud_networks.detectors",
            observedAt=_as_observed_at(observed_at),
            confidence=confidence,
        )
        signals.append(
            RiskSignal(
                signal_id=_signal_id(
                    producer="fraud_network",
                    tenant_id=tenant_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    dimension=dimension,
                    source="fraud_networks.detectors",
                    signal_name=signal_name,
                    index=index,
                ),
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                risk_dimension=dimension,
                claim_state=EpistemicStatus.INFERRED,
                confidence=confidence,
                evidence_refs=[ref],
                source="fraud_networks.detectors",
                observed_at=observed_at,
            )
        )
    return signals


def signal_from_device_risk(
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt a device-risk posture into a RiskSignal (or none, honestly).

    The device-risk producer exposes an ordinal state (``ok``/``suspect``/
    ``blocked``) and fired risk-signal name strings — never a numeric score.
    An ``ok`` device with no fired signals yields ``[]`` (nothing risk-worthy to
    claim). A ``suspect``/``blocked`` device (or one with fired signals) yields a
    ``derived`` signal on the ``infrastructure`` dimension with ``score=None``
    and an EvidenceRef naming the device and the fired signals.
    """
    if artifact is None:
        return []
    if isinstance(artifact, str):
        risk_state = artifact
        device_id = None
        fired = []
        evaluated_at = None
    elif isinstance(artifact, Mapping):
        risk_state = artifact.get("risk_state") or artifact.get("state")
        device_id = artifact.get("device_id")
        meta = artifact.get("metadata") or {}
        fired = list(artifact.get("risk_signals") or meta.get("risk_signals") or [])
        evaluated_at = artifact.get("risk_evaluated_at") or meta.get("risk_evaluated_at")
    else:
        risk_state = getattr(artifact, "risk_state", None)
        device_id = getattr(artifact, "device_id", None)
        meta = getattr(artifact, "metadata", None) or {}
        fired = list(meta.get("risk_signals") or [])
        evaluated_at = meta.get("risk_evaluated_at")

    if risk_state in (None, "ok") and not fired:
        return []
    observed_at = observed_at or None

    ref = EvidenceRef(
        id=_evidence_id(
            "device_risk",
            device_id=device_id or subject_id,
            risk_state=risk_state,
            tenant_id=tenant_id,
        ),
        type="entity",
        source="kyber.device_risk",
        observedAt=_as_observed_at(observed_at, evaluated_at),
    )
    return [
        RiskSignal(
            signal_id=_signal_id(
                producer="device_risk",
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                dimension=DEVICE_RISK_DIMENSION,
                source="kyber.device_risk",
                device_id=device_id or subject_id,
                risk_state=risk_state,
                fired=",".join(sorted(fired)),
            ),
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            risk_dimension=DEVICE_RISK_DIMENSION,
            claim_state=EpistemicStatus.DERIVED,
            evidence_refs=[ref],
            source="kyber.device_risk",
            observed_at=observed_at,
        )
    ]


def signal_from_geo_lookup(
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt a :class:`services.ingestion.geo_provider.GeoLookup` into a signal.

    Only a ``ready`` lookup with a genuine datacenter likelihood (>0) yields a
    risk signal: the geographic dimension, ``inferred`` claim (geo enrichment is
    model/DB output, never a fact), score = ``datacenter_likelihood`` (0–1
    passthrough). A non-``ready`` lookup yields ``[]`` — no geo knowledge, and
    the raw IP is never persisted (only the coarse ASN is referenced).
    """
    if artifact is None:
        return []
    state = _field(artifact, "state")
    if state != "ready":
        return []
    likelihood = _field(artifact, "datacenter_likelihood", 0.0)
    try:
        likelihood = float(likelihood)
    except (TypeError, ValueError):
        likelihood = 0.0
    asn = _field(artifact, "asn")
    asn_class = _field(artifact, "asn_class")
    detector_version = _field(artifact, "provider_database_version")
    if likelihood <= 0.0:
        # Residential/unknown IP: no datacenter indicator — nothing risk-worthy
        # to claim (never emit a zero posing as risk).
        return []

    ref = EvidenceRef(
        id=_evidence_id(
            "geo", asn=asn, asn_class=asn_class, tenant_id=tenant_id
        ),
        type="event",
        source="geo.enrichment",
        observedAt=_as_observed_at(observed_at),
    )
    return [
        RiskSignal(
            signal_id=_signal_id(
                producer="geo",
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                dimension=GEO_DIMENSION,
                source="geo.enrichment",
                asn=asn,
                asn_class=asn_class,
                likelihood=likelihood,
            ),
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            risk_dimension=GEO_DIMENSION,
            claim_state=EpistemicStatus.INFERRED,
            evidence_refs=[ref],
            source="geo.enrichment",
            detector_version=detector_version,
            observed_at=observed_at,
            score=likelihood,
        )
    ]


def signal_from_behavioral_scan(
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt a :func:`services.behavioral.engines.run_full_behavioral_scan` dict.

    Each computed behavioral family (non-``None`` scan row) becomes a ``derived``
    RiskSignal on its converged risk dimension. The engine marks its heuristic
    numerics ``calibrated: False``, so no uncalibrated score is promoted to a
    calibrated 0–1 risk score — ``score=None`` with the row's engine confidence
    when the engine supplied one.
    """
    if artifact is None:
        return []
    signals_dict = _field(artifact, "signals") or {}
    scanned_at = _field(artifact, "scanned_at")
    signals: list[RiskSignal] = []
    index = 0
    for family, row in signals_dict.items():
        if row is None:
            continue
        if not isinstance(row, Mapping):
            continue
        dimension = _BEHAVIORAL_FAMILY_DIMENSIONS.get(
            str(family), "behavioral"
        )
        confidence = row.get("confidence")
        confidence = (
            float(confidence)
            if isinstance(confidence, (int, float)) and 0.0 <= float(confidence) <= 1.0
            else None
        )
        ref = EvidenceRef(
            id=_evidence_id(
                "behavioral", family=family, index=index, tenant_id=tenant_id
            ),
            type="model_output",
            source="behavioral.engines",
            observedAt=_as_observed_at(observed_at, scanned_at),
            confidence=confidence,
        )
        signals.append(
            RiskSignal(
                signal_id=_signal_id(
                    producer="behavioral",
                    tenant_id=tenant_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    dimension=dimension,
                    source="behavioral.engines",
                    family=family,
                    index=index,
                ),
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                risk_dimension=dimension,
                claim_state=EpistemicStatus.DERIVED,
                confidence=confidence,
                evidence_refs=[ref],
                source="behavioral.engines",
                observed_at=observed_at,
            )
        )
        index += 1
    return signals


def signal_from_trust_vector(
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Adapt a trust vector into risk signals per observed trust dimension.

    Accepts a :class:`shared.scoring.trust_vector.TrustVector` or its
    ``to_dict()`` snapshot. A TRUST value is not a RISK value: for the trust
    dimensions whose high value means high trust, the risk posture is
    ``1 - value``; ``automation_likelihood`` is already risk-positive (high
    automation = high risk) and passes through. Only ``observed`` dimensions
    with real coverage contribute — a prior-backed unobserved dimension never
    renders as a fabricated risk score.
    """
    if artifact is None:
        return []
    if isinstance(artifact, Mapping):
        dims = artifact.get("dimensions") or {}
        weights_version = artifact.get("weights_version")
    else:
        dims = getattr(artifact, "dimensions", None)
        dims = dims() if callable(dims) else (dims or {})
        weights_version = getattr(artifact, "weights_version", None)

    signals: list[RiskSignal] = []
    for trust_dim in sorted(dims):
        raw = dims[trust_dim]
        if isinstance(raw, Mapping):
            value = raw.get("value")
            observed = raw.get("observed", False)
            coverage = raw.get("coverage")
        else:
            value = getattr(raw, "value", None)
            observed = getattr(raw, "observed", False)
            coverage = getattr(raw, "coverage", None)
        if not observed or coverage in (None, "missing"):
            continue
        if not isinstance(value, (int, float)):
            continue
        value = float(value)
        value = max(0.0, min(1.0, value))
        # Trust is NOT risk: a high trust-positive dimension (e.g. strong
        # identity_assurance) is a LOW risk posture, so risk inverts it
        # (1 - value). ``automation_likelihood`` is already risk-positive (high
        # automation = high risk) and passes through unconverted.
        risk_value = (1.0 - value) if trust_dim in _TRUST_RISK_INVERTED else value
        risk_dim = _TRUST_DIMENSION_MAP.get(trust_dim, "reputation")
        risk_value = round(max(0.0, min(1.0, risk_value)), 4)
        ref = EvidenceRef(
            id=_evidence_id(
                "trust", trust_dim=trust_dim, tenant_id=tenant_id
            ),
            type="model_output",
            source="trust.vector",
            observedAt=_as_observed_at(observed_at),
        )
        signals.append(
            RiskSignal(
                signal_id=_signal_id(
                    producer="trust",
                    tenant_id=tenant_id,
                    subject_kind=subject_kind,
                    subject_id=subject_id,
                    dimension=risk_dim,
                    source="trust.vector",
                    trust_dim=trust_dim,
                    trust_value=round(value, 4),
                ),
                tenant_id=tenant_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                risk_dimension=risk_dim,
                claim_state=EpistemicStatus.DERIVED,
                evidence_refs=[ref],
                source="trust.vector",
                detector_version=weights_version,
                observed_at=observed_at,
                score=risk_value,
            )
        )
    return signals


# ═══════════════════════════════════════════════════════════════════════════
# Dispatcher + bundle orchestration
# ═══════════════════════════════════════════════════════════════════════════

_PRODUCER_ADAPTERS: Mapping[str, Any] = {
    "fraud": signal_from_fraud_result,
    "fraud_network": signals_from_fraud_network_evidence,
    "device_risk": signal_from_device_risk,
    "geo": signal_from_geo_lookup,
    "behavioral": signal_from_behavioral_scan,
    "trust": signal_from_trust_vector,
}


def adapt_producer_signal(
    producer: str,
    artifact: Any,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Run one producer artifact through its convergence adapter.

    Raises ``KeyError`` (listing the known producers) for an unknown producer —
    a misspelled producer can never silently converge to no signals.
    """
    try:
        adapter = _PRODUCER_ADAPTERS[producer]
    except KeyError:
        raise KeyError(
            f"Unknown producer {producer!r}. Known producers: {sorted(KNOWN_PRODUCERS)}"
        ) from None
    return adapter(
        artifact,
        subject_kind=subject_kind,
        subject_id=subject_id,
        tenant_id=tenant_id,
        observed_at=observed_at,
    )


def signals_from_evidence_bundle(
    bundle: RiskEvidenceBundle,
    *,
    subject_kind: str,
    subject_id: str,
    tenant_id: str,
    observed_at: Optional[datetime] = None,
) -> list[RiskSignal]:
    """Converge every producer artifact in ``bundle`` into RiskSignals.

    Runs the dispatcher over the present fields in a fixed order so identical
    evidence yields an identical, deterministically ordered signal list.
    """
    signals: list[RiskSignal] = []
    if bundle.fraud_result is not None:
        signals.extend(
            adapt_producer_signal(
                "fraud",
                bundle.fraud_result,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    if bundle.fraud_network_signals:
        signals.extend(
            adapt_producer_signal(
                "fraud_network",
                bundle.fraud_network_signals,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    if bundle.device_risk is not None:
        signals.extend(
            adapt_producer_signal(
                "device_risk",
                bundle.device_risk,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    if bundle.geo_lookup is not None:
        signals.extend(
            adapt_producer_signal(
                "geo",
                bundle.geo_lookup,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    if bundle.behavioral_scan is not None:
        signals.extend(
            adapt_producer_signal(
                "behavioral",
                bundle.behavioral_scan,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    if bundle.trust_vector is not None:
        signals.extend(
            adapt_producer_signal(
                "trust",
                bundle.trust_vector,
                subject_kind=subject_kind,
                subject_id=subject_id,
                tenant_id=tenant_id,
                observed_at=observed_at,
            )
        )
    return signals


__all__ = [
    "DEVICE_RISK_DIMENSION",
    "GEO_DIMENSION",
    "FraudNetworkSignalEvidence",
    "KNOWN_PRODUCERS",
    "RiskEvidenceBundle",
    "adapt_producer_signal",
    "signal_from_behavioral_scan",
    "signal_from_device_risk",
    "signal_from_fraud_result",
    "signal_from_geo_lookup",
    "signal_from_trust_vector",
    "signals_from_evidence_bundle",
    "signals_from_fraud_network_evidence",
]
