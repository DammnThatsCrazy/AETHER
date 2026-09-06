"""Consumption-side normalization spine (WS-B5, SDK + Universal Ingestion).

Converge how downstream consumers READ validated-topic payloads so they all go
through ONE spine function (:func:`to_observation_view`) that:

1. projects the additive ``observation_envelope`` key when present (Envelope B,
   WS-A5 — the payload's flat SDK dict always remains alongside it),
2. else maps the legacy flat SDK / comms dict (the shape ``workers`` and the
   Silver projectors read today),
3. else maps a provider-runtime ``AetherEvent`` ``model_dump()`` (the shape
   ``services/provider_runtime/bridge.py`` publishes), whose top-level
   ``subject_id`` / ``actor_id`` become reachable ``user_id`` / ``agent_id``
   subjects that flat-key consumers previously dropped.

Emission convergence (every publisher attaching an envelope) is deliberately
DEFERRED to the family adapters / WS-B2/WS-B3 lanes — nothing here attaches an
envelope, and ``services/ingestion/batch.py`` / ``comms/ingest.py`` /
``provider_runtime/bridge.py`` are untouched.

The view is lossy-safe by construction: every field is Optional and the function
never raises, so a consumer degrades to skipping a payload exactly as it does
today on a missing key. ``envelope_source`` records which resolution branch won.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

# Envelope subject identifier types that consumers surface as top-level view
# fields. Drawn from shared/observation/envelope.py::IDENTIFIER_TYPES; kept as
# a module constant so the spine never needs a runtime import of the model.
_USER_ID_SUBJECT = "user_id"
_ANONYMOUS_ID_SUBJECT = "anonymous_id"
_SESSION_ID_SUBJECT = "session_id"


@dataclass(frozen=True)
class SubjectView:
    """One entity an observation is about (mirrors Envelope-B ``subjects[]``)."""

    identifier_type: Optional[str] = None
    value: Optional[Any] = None
    trust_class: Optional[str] = None
    source: Optional[str] = None


@dataclass(frozen=True)
class ObservationView:
    """Lossy-safe projection of one validated-topic payload for consumers.

    All fields Optional; every field is derived WITHOUT raising. Consumers read
    exactly the view fields they need and keep their existing skip-on-missing
    semantics.
    """

    observation_id: Optional[str] = None
    observation_type: Optional[str] = None
    family: Optional[str] = None
    tenant_id: Optional[str] = None
    occurred_at: Optional[str] = None
    received_at: Optional[str] = None
    ingested_at: Optional[str] = None
    source_type: Optional[str] = None
    subjects: tuple[SubjectView, ...] = ()
    session_id: Optional[Any] = None
    user_id: Optional[Any] = None
    anonymous_id: Optional[Any] = None
    provider: Optional[str] = None
    provider_identity: Optional[str] = None
    correlation_id: Optional[str] = None
    payload_dict: Optional[Mapping[str, Any]] = None
    context: Optional[Mapping[str, Any]] = None
    envelope_source: bool = False


def normalization_spine_enabled() -> bool:
    """Read the WS-B5 adoption flag (cheap; the settings singleton is cached).

    Never raises: a config that cannot be loaded degrades to the legacy path.
    """
    try:
        from config.settings import get_settings

        return bool(get_settings().normalization_spine.enabled)
    except Exception:  # pragma: no cover - defensive; config is always loadable
        return False


def _as_dict(value: Any) -> Optional[dict[str, Any]]:
    return value if isinstance(value, dict) else None


def _first_subject_value(subjects: tuple[SubjectView, ...], identifier_type: str) -> Optional[Any]:
    for subject in subjects:
        if subject.identifier_type == identifier_type and subject.value is not None:
            return subject.value
    return None


def _correlation_id_from_context(context: Any) -> Optional[str]:
    ctx = _as_dict(context)
    if not ctx:
        return None
    correlation = _as_dict(ctx.get("correlation"))
    if correlation:
        return correlation.get("correlationId") or ctx.get("correlationId")
    return ctx.get("correlationId")


# ── Envelope branch (additive observation_envelope key) ─────────────────────


def _from_envelope(envelope: Mapping[str, Any]) -> ObservationView:
    observation = _as_dict(envelope.get("observation")) or {}
    tenancy = _as_dict(envelope.get("tenancy")) or {}
    source = _as_dict(envelope.get("source")) or {}
    correlation = _as_dict(envelope.get("correlation")) or {}
    raw_subjects = envelope.get("subjects") or []

    subjects: tuple[SubjectView, ...] = ()
    if isinstance(raw_subjects, list):
        built = []
        for item in raw_subjects:
            subject = _as_dict(item)
            if not subject:
                continue
            identifier_type = subject.get("identifier_type")
            value = subject.get("identifier_value")
            if identifier_type is None or value is None:
                continue
            built.append(
                SubjectView(
                    identifier_type=identifier_type,
                    value=value,
                    trust_class=subject.get("trust_class"),
                    source=subject.get("source"),
                )
            )
        subjects = tuple(built)

    return ObservationView(
        observation_id=observation.get("observation_id"),
        observation_type=observation.get("observation_type"),
        family=observation.get("family"),
        tenant_id=tenancy.get("tenant_id"),
        occurred_at=observation.get("occurred_at"),
        received_at=observation.get("received_at"),
        ingested_at=observation.get("ingested_at"),
        source_type=source.get("source_type"),
        subjects=subjects,
        session_id=_first_subject_value(subjects, _SESSION_ID_SUBJECT),
        user_id=_first_subject_value(subjects, _USER_ID_SUBJECT),
        anonymous_id=_first_subject_value(subjects, _ANONYMOUS_ID_SUBJECT),
        correlation_id=correlation.get("correlation_id"),
        payload_dict=_as_dict(envelope.get("payload")),
        # The envelope carries the A-side context on the flat dict (still on the
        # payload), not inside the envelope blocks — leave view.context None.
        context=None,
        envelope_source=True,
    )


# ── SDK / comms flat branch (legacy bus dict) ───────────────────────────────


def _looks_like_aether_event(payload: Mapping[str, Any]) -> bool:
    """An ``AetherEvent.model_dump()`` never carries ``properties``/``session_id``
    and always carries a ``data`` dict plus ``occurred_at``."""
    return (
        "occurred_at" in payload
        and isinstance(payload.get("data"), dict)
        and "properties" not in payload
    )


def _from_sdk_flat(payload: Mapping[str, Any]) -> ObservationView:
    context = _as_dict(payload.get("context"))
    subjects: tuple[SubjectView, ...] = ()
    built = []
    for identifier_type, key in (
        (_USER_ID_SUBJECT, "user_id"),
        (_ANONYMOUS_ID_SUBJECT, "anonymous_id"),
    ):
        value = payload.get(key)
        if value is not None and value != "":
            built.append(SubjectView(identifier_type=identifier_type, value=value))
    subjects = tuple(built)

    return ObservationView(
        observation_id=payload.get("event_id"),
        observation_type=payload.get("event_type"),
        family=payload.get("event_family"),
        tenant_id=payload.get("tenant_id"),
        occurred_at=payload.get("timestamp"),
        received_at=payload.get("received_at"),
        ingested_at=payload.get("ingested_at"),
        source_type=payload.get("source_type") or payload.get("source"),
        subjects=subjects,
        session_id=payload.get("session_id"),
        user_id=payload.get("user_id"),
        anonymous_id=payload.get("anonymous_id"),
        provider=payload.get("provider"),
        provider_identity=payload.get("provider_identity"),
        correlation_id=_correlation_id_from_context(context),
        payload_dict=_as_dict(payload.get("properties")),
        context=context,
        envelope_source=False,
    )


# ── AetherEvent dump branch (provider_runtime.bridge) ───────────────────────


def _from_aether_event(payload: Mapping[str, Any]) -> ObservationView:
    subjects: tuple[SubjectView, ...] = ()
    built = []
    subject_id = payload.get("subject_id")
    if subject_id is not None:
        built.append(SubjectView(identifier_type=_USER_ID_SUBJECT, value=subject_id))
    actor_id = payload.get("actor_id")
    if actor_id is not None:
        built.append(SubjectView(identifier_type="agent_id", value=actor_id))
    subjects = tuple(built)

    return ObservationView(
        observation_id=payload.get("event_id"),
        observation_type=payload.get("event_type"),
        family=payload.get("event_family"),
        tenant_id=payload.get("tenant_id"),
        occurred_at=payload.get("occurred_at"),
        provider=payload.get("provider"),
        provider_identity=payload.get("provider_identity"),
        subjects=subjects,
        user_id=_first_subject_value(subjects, _USER_ID_SUBJECT),
        correlation_id=_correlation_id_from_context(payload.get("context")),
        payload_dict=_as_dict(payload.get("data")),
        context=_as_dict(payload.get("context")),
        envelope_source=False,
    )


# ── Entry point ─────────────────────────────────────────────────────────────


def to_observation_view(payload: Mapping[str, Any]) -> ObservationView:
    """Project any validated-topic payload onto the shared observation view.

    Resolution order:
      1. ``observation_envelope`` present and a dict → the envelope owns the view.
      2. ``AetherEvent`` ``model_dump()`` shape (``occurred_at`` + ``data``,
         no ``properties``) → provider-runtime branch.
      3. flat SDK / comms shape (``event_type`` present) → legacy branch.
      4. anything else → an all-None view (consumers skip on missing keys).

    Never raises and accepts a non-dict payload as a defensive no-op.
    """
    if not isinstance(payload, Mapping):
        return ObservationView()
    envelope = _as_dict(payload.get("observation_envelope"))
    if envelope is not None:
        return _from_envelope(envelope)
    if _looks_like_aether_event(payload):
        return _from_aether_event(payload)
    if payload.get("event_type") is not None:
        return _from_sdk_flat(payload)
    return ObservationView()


__all__ = [
    "ObservationView",
    "SubjectView",
    "normalization_spine_enabled",
    "to_observation_view",
]
