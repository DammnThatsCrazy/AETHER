"""ReplayIngressAdapter — the replay family adapter (WS-B4).

Maps a durable Bronze SDK event being replayed to a
:class:`UniversalObservationEnvelope` (Envelope B) with **original-time
preservation** (Invariant #15). It is the canonical identity for the
``replay`` family that the operator replay runner
(``services/ingestion/replay.py``) routes through.

Credential class: ``OPERATOR_REPLAY`` — the blueprint's operator-initiated
replay credential (blueprint §11 / Envelope-B credential-class vocabulary).
The universal ingestion gateway stamps it (with the adapter identity) as the
envelope's provenance / trust basis, exactly as ``PUBLIC_CLIENT`` is the trust
basis for the SDK family.

Why this is an adapter and not a second pass through the SDK adapter: a replay
is not a fresh SDK observation — it is a *re-delivery of an already-observed
event*. The observed-vs-received split (Invariant #15) is exactly the
difference: ``observation.occurred_at`` and the flat ``timestamp`` stay the
ORIGINAL occurrence, while ``observation.received_at``/``ingested_at`` are the
fresh replay-time stamps injected by the runner via ``normalized["_replay"]``.
``source.source_type`` becomes ``"replay"`` (so Envelope-B consumers can tell
a replay delivery apart from a live one), ``source.source_provider`` carries
the original ingress family (e.g. ``sdk``), ``source.source_native_id`` and
``observation.observation_id`` keep the ORIGINAL event_id (downstream
projectors/normalizers therefore recompute idempotently), and
``lineage.raw_record_ref`` points back to the durable Bronze row the event was
replayed from (Invariant #14).

Build rule: when the stored normalized payload carries the
``observation_envelope`` the original pass persisted (flag-gated Envelope-B
adoption), re-validate THAT envelope and rewrite it; otherwise rebuild the
SDK-equivalent mapping (``services/ingestion/observation_envelope.py``) and
rewrite. Either way the rewrite set below is applied unconditionally, so the
two source shapes converge on the same replay envelope. Returns None (warn +
metric) when the core cannot be built — never raises — so the replay runner can
degrade per-row without taking the run down.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import ValidationError

from shared.logger.logger import get_logger, metrics
from shared.observation.envelope import (
    CorrelationBlock,
    LineageBlock,
    ObservationBlock,
    ProvenanceBlock,
    SourceBlock,
    UniversalObservationEnvelope,
)
from shared.temporal.instant import coerce_utc_lenient

from services.ingestion.adapters.base import UniversalIngressAdapter
from services.ingestion.observation_envelope import (
    build_sdk_observation_envelope as _build_sdk_observation_envelope,
)

logger = get_logger("aether.service.ingestion.adapters.replay")

DEFAULT_REPLAY_INGRESS_PATH = "/v1/ingest/replay"

# The runner injects this key into the per-row normalized copy it hands the
# adapter; it is stripped from the payload that is actually published.
REPLAY_CONTEXT_KEY = "_replay"


class ReplayIngressAdapter(UniversalIngressAdapter):
    """Replay-family adapter: durable Bronze SDK event -> replayed Envelope B.

    Original-time preservation (Invariant #15): the occurrence instant never
    changes on replay; only received/ingested + replay provenance are fresh.
    """

    adapter_id = "replay"
    family = "replay"
    credential_class = "OPERATOR_REPLAY"
    adapter_version = "1.0.0"
    description = (
        "Operator ingestion-level replay (Invariant #15 original-time "
        "preservation): re-delivers a durable Bronze SDK event through the "
        "universal gateway with the ORIGINAL occurrence timestamp and event_id "
        "kept intact (downstream recompute stays idempotent); only the "
        "received/ingested instants and replay provenance are fresh. "
        "OPERATOR_REPLAY credential, /v1/kyber/ingest/replay operator route."
    )

    def build_observation_envelope(
        self,
        normalized: Mapping[str, Any],
        *,
        ingress_path: Optional[str] = None,
    ) -> Optional[UniversalObservationEnvelope]:
        """Build a replayed Envelope-B observation with original occurrence.

        ``normalized`` is the per-row flat SDK payload copy with a
        ``_replay`` context (original_event_id, replay_received_at,
        replay_ingested_at, bronze_ref, replay_run_id) injected by the runner.
        """
        ingress = ingress_path or DEFAULT_REPLAY_INGRESS_PATH
        replay = normalized.get(REPLAY_CONTEXT_KEY) if isinstance(normalized, Mapping) else None
        if not isinstance(replay, dict):
            logger.warning(
                "replay adapter: missing _replay context, skipping envelope build"
            )
            metrics.increment("ingestion_replay_adapter_skipped_total")
            return None

        envelope = self._base_envelope(normalized)
        if envelope is None:
            return None

        original_event_id = replay.get("original_event_id") or envelope.observation.observation_id
        # Runner-injected operational stamps: the kernel's lenient coercer
        # (shared/temporal/instant) accepts an ISO-8601 string or datetime,
        # assuming UTC on a naive value and returning None on empty/unparseable
        # input — never raising, so a bad stamp degrades per-row not per-run.
        replay_received = coerce_utc_lenient(replay.get("replay_received_at"))
        replay_ingested = coerce_utc_lenient(replay.get("replay_ingested_at"))
        if replay_received is None or replay_ingested is None:
            logger.warning(
                "replay adapter: unparseable replay instants, skipping event %s",
                original_event_id,
            )
            metrics.increment("ingestion_replay_adapter_skipped_total")
            return None

        # ── The original source identity BEFORE the replay rewrite ─────────
        # ``source.source_provider`` carries the original ingress family so a
        # downstream reader can tell "this arrived via replay" (source_type)
        # from "what it originally was" (source_provider / native id).
        original_source = envelope.source
        original_family = original_source.source_provider or original_source.source_type

        # ── Invariant #15: ALWAYS rewrite the replay-delivery surface ──────
        # occurred_at is left as the ORIGINAL occurrence (never now). The
        # observation_id stays the original event_id so downstream
        # projectors/normalizers recompute idempotently. received/ingested are
        # the fresh replay-time stamps.
        observation_id = str(original_event_id)
        observation = ObservationBlock(
            observation_id=observation_id,
            observation_type=envelope.observation.observation_type,
            family=envelope.observation.family,
            occurred_at=envelope.observation.occurred_at,  # ORIGINAL, never now
            received_at=replay_received,
            ingested_at=replay_ingested,
            schema_version=envelope.observation.schema_version,
        )
        source = SourceBlock(
            source_type="replay",
            source_provider=original_family,
            source_instance=original_source.source_instance,
            source_native_id=observation_id,
            ingress_path=ingress,
        )
        provenance = ProvenanceBlock(
            adapter=self.adapter_id,
            adapter_version=self.adapter_version,
        )
        base_lineage = envelope.lineage
        lineage = LineageBlock(
            raw_record_ref=str(replay.get("bronze_ref") or ""),
            normalization_version=(
                base_lineage.normalization_version if base_lineage else None
            ),
            validation_version=(
                base_lineage.validation_version if base_lineage else None
            ),
        )

        # causation_id = the original observation when it is DISTINCT from the
        # observation_id now assigned. Replay keeps observation_id == original
        # event_id, so this is normally a no-op; the guard keeps the correlation
        # additive if a future replay variant re-keys the observation.
        correlation = envelope.correlation
        original_correlation_id = (
            envelope.observation.observation_id
            if envelope.observation.observation_id != observation_id
            else None
        )
        causation_id = None
        if original_correlation_id is not None:
            causation_id = original_correlation_id
        elif correlation is not None and correlation.causation_id:
            causation_id = correlation.causation_id
        if causation_id is not None or correlation is not None:
            base_corr = correlation.model_dump() if correlation is not None else {}
            correlation = CorrelationBlock(
                correlation_id=base_corr.get("correlation_id"),
                causation_id=causation_id,
                trace_id=base_corr.get("trace_id"),
                span_id=base_corr.get("span_id"),
                parent_observation_id=base_corr.get("parent_observation_id"),
            )

        return envelope.model_copy(
            update={
                "observation": observation,
                "source": source,
                "provenance": provenance,
                "lineage": lineage,
                "correlation": correlation,
            }
        )

    # ── base envelope helpers ───────────────────────────────────────────────

    def _base_envelope(
        self, normalized: Mapping[str, Any]
    ) -> Optional[UniversalObservationEnvelope]:
        """The pre-rewrite envelope: the STORED one when present, else rebuild.

        * stored-envelope row (Envelope-B flag was ON during original ingest):
          re-validate the exact envelope the original pass persisted — the
          replayed occurrence can never drift from what was durably recorded.
        * flag-off row: rebuild the SDK-equivalent mapping so a V1/V2 Bronze
          row recorded before Envelope-B adoption still replays.
        Returns None when neither path can supply the core.
        """
        stored = normalized.get("observation_envelope")
        if isinstance(stored, dict):
            try:
                return UniversalObservationEnvelope(**stored)
            except (ValidationError, ValueError, TypeError) as exc:
                logger.warning(
                    "replay adapter: stored observation_envelope failed "
                    "re-validation, skipping: %s",
                    exc,
                )
                metrics.increment("ingestion_replay_adapter_skipped_total")
                return None
        envelope = _build_sdk_observation_envelope(
            normalized, ingress_path=DEFAULT_REPLAY_INGRESS_PATH
        )
        if envelope is None:
            logger.warning(
                "replay adapter: cannot rebuild SDK-equivalent core for event_id=%s",
                normalized.get("event_id"),
            )
            metrics.increment("ingestion_replay_adapter_skipped_total")
        return envelope
