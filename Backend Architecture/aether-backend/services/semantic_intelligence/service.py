"""Internal semantic-intelligence service port.

Both the public API routes and (from Phase A2) the validated-event worker call
this in-process port — never the HTTP API. It owns classification + durable
persistence + the read/aggregation surface, sitting over the pluggable store
(``get_store()`` → in-memory default, or the injected durable store).
"""

from __future__ import annotations

import time
from typing import Any, Optional
from uuid import uuid4

from config.settings import settings
from services.consent.authority import evaluate_consent
from shared.logger.logger import get_logger, metrics

from .eligibility import Eligibility
from .engine import (
    cascades_for_tenant,
    classify_event,
    entity_state,
    get_store,
)
from .models import ObservationStatus, SemanticObservation, SentimentObservation, SubjectType, utc_now
from .providers import SemanticClassifierProvider, get_classifier_provider, get_shadow_provider
from .repositories.replay_repo import SemanticReplayJobRepository
from .repositories.review_queue_repo import SemanticReviewQueueRepository

logger = get_logger("aether.semantic.service")

_MODEL_VERSIONS = [
    "deterministic-semantic-classifier@1.0.0",
    "deterministic-sentiment-classifier@1.0.0",
]

# In-process count of active replay runs backing the
# aether_semantic_replay_jobs_active gauge (per-process, like every Prometheus
# gauge this collector exports).
_active_replay_jobs = 0


def _replay_jobs_active_delta(delta: int) -> None:
    global _active_replay_jobs
    _active_replay_jobs = max(0, _active_replay_jobs + delta)
    metrics.gauge("aether_semantic_replay_jobs_active", float(_active_replay_jobs))


def _record_review_queue_gauge(counts: dict[str, int]) -> None:
    for queue_type, open_count in counts.items():
        metrics.gauge(
            "aether_semantic_review_queue_open",
            float(open_count),
            labels={"queue_type": queue_type},
        )


def _valence_sign(sentiments: list[SentimentObservation]) -> Optional[str]:
    """Sign of the first sentiment valence ('positive'/'negative'/'zero'), None when absent."""
    if not sentiments:
        return None
    valence = sentiments[0].valence
    if valence > 0:
        return "positive"
    if valence < 0:
        return "negative"
    return "zero"


class SemanticIntelligenceService:
    """Classification + durable persistence + read port for semantic intelligence."""

    def __init__(self, review_queue: Optional[SemanticReviewQueueRepository] = None) -> None:
        self._review_queue = review_queue or SemanticReviewQueueRepository()
        self._replay_jobs = SemanticReplayJobRepository()

    # ── replay / historical backfill ─────────────────────────────────────────

    async def create_replay_job(
        self, tenant_id: str, *, dry_run: bool, filters: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a replay job. Dry-run counts inline; a real run is durably
        enqueued on the jobs platform (``semantic.replay``) — never an
        in-process task that a crash/restart would silently lose."""
        from .replay import SemanticReplayRunner

        job = await self._replay_jobs.create(tenant_id, dry_run=dry_run, filters=filters)
        if dry_run:
            runner = SemanticReplayRunner(self._replay_jobs)
            result = await self._run_replay(runner, tenant_id, job["id"])
            return {"job_id": job["id"], "dry_run": True, **result}
        platform_job = await self._enqueue_replay(tenant_id, job["id"])
        return {
            "job_id": job["id"],
            "dry_run": False,
            "status": "queued",
            "platform_job_id": platform_job["id"],
        }

    async def _enqueue_replay(
        self, tenant_id: str, replay_job_id: str, *, cursor: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        """Durably enqueue one ``semantic.replay`` execution for a replay job."""
        from services.jobs.service import get_jobs_service

        from .jobs import SEMANTIC_REPLAY_JOB_TYPE

        payload: dict[str, Any] = {"replay_job_id": replay_job_id}
        # Cursor-scoped idempotency: re-submitting the same execution point
        # dedupes, while a resume from a new cursor is a fresh durable job.
        idempotency_key = f"semantic-replay:{replay_job_id}"
        if cursor:
            payload["cursor"] = cursor
            idempotency_key += (
                f":{cursor.get('received_at', '')}:{cursor.get('event_id', '')}"
            )
        return await get_jobs_service().enqueue(
            tenant_id,
            SEMANTIC_REPLAY_JOB_TYPE,
            payload,
            idempotency_key=idempotency_key,
            correlation_id=replay_job_id,
            requested_by="semantic_intelligence",
        )

    async def run_replay_for_job(
        self,
        tenant_id: str,
        replay_job_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
        checkpoint: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Execute one replay run (jobs-platform handler entry point)."""
        from .replay import SemanticReplayRunner

        runner = SemanticReplayRunner(self._replay_jobs)
        return await self._run_replay(
            runner, tenant_id, replay_job_id, cursor=cursor, checkpoint=checkpoint
        )

    async def _run_replay(
        self,
        runner: Any,
        tenant_id: str,
        job_id: str,
        *,
        cursor: Optional[dict[str, Any]] = None,
        checkpoint: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Execute one replay run holding the replay-jobs-active gauge up."""
        _replay_jobs_active_delta(+1)
        try:
            return await runner.run(tenant_id, job_id, cursor=cursor, checkpoint=checkpoint)
        finally:
            _replay_jobs_active_delta(-1)

    async def get_replay_job(self, tenant_id: str, job_id: str) -> Optional[dict[str, Any]]:
        return await self._replay_jobs.get(tenant_id, job_id)

    # ── data-subject rights ──────────────────────────────────────────────────

    async def erase_subject(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Hard-delete a subject's semantic data; returns a verification result."""
        from .privacy import SemanticPrivacyHandler

        return await SemanticPrivacyHandler().handle_erasure(tenant_id, subject_ref)

    async def restrict_subject(self, tenant_id: str, subject_ref: str) -> dict[str, Any]:
        """Consent revocation → mark a subject's observations CONSENT_RESTRICTED."""
        from .privacy import SemanticPrivacyHandler

        return await SemanticPrivacyHandler().handle_restriction(tenant_id, subject_ref)

    async def control_replay_job(
        self, tenant_id: str, job_id: str, action: str
    ) -> Optional[dict[str, Any]]:
        job = await self._replay_jobs.get(tenant_id, job_id)
        if job is None:
            return None
        status_map = {"pause": "paused", "resume": "running", "cancel": "cancelled"}
        new_status = status_map.get(action)
        if new_status is None:
            return None
        await self._replay_jobs.update(tenant_id, job_id, status=new_status)
        if action == "resume" and not job.get("dry_run", True):
            # Resume durably from the persisted Bronze cursor (progress.cursor)
            # via a fresh jobs-platform execution — never an in-process task.
            cursor = (job.get("progress") or {}).get("cursor") or None
            await self._enqueue_replay(tenant_id, job_id, cursor=cursor)
        return await self._replay_jobs.get(tenant_id, job_id)

    # ── write path ─────────────────────────────────────────────────────────────

    async def classify_and_persist(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        *,
        eligibility: Optional[Eligibility] = None,
    ) -> tuple[SemanticObservation, list[SentimentObservation]]:
        """Classify an event payload and durably persist the results.

        The single write path shared by the API route and the worker (byte-
        identical observations regardless of entry point). Fail-closed on consent;
        eligibility routes structured vs text vs quarantine/abstain.
        """
        store = get_store()

        # 1. Consent — fail closed when authoritative enforcement is enabled.
        blocked = await self._consent_block(payload, tenant_id)
        if blocked is not None:
            obs = self._status_observation(
                payload, tenant_id, ObservationStatus.CONSENT_RESTRICTED, blocked
            )
            return await store.put_semantic(obs), []

        # 2. Eligibility routing (worker path supplies it; route path classifies directly).
        if eligibility is Eligibility.QUARANTINE:
            obs = self._status_observation(
                payload, tenant_id, ObservationStatus.QUARANTINED, "quarantined_unregistered"
            )
            metrics.increment(
                "aether_semantic_observations_quarantined_total",
                labels={"tenant_id": tenant_id, "reason": "quarantined_unregistered"},
            )
            return await store.put_semantic(obs), []
        provider: Optional[SemanticClassifierProvider] = None
        if eligibility is Eligibility.TEXT:
            provider = get_classifier_provider(settings, tenant_id)
            if not provider.available():
                reason = provider.abstention_reason() or "provider_disabled"
                obs = self._status_observation(
                    payload, tenant_id, ObservationStatus.ABSTAINED, reason
                )
                metrics.increment(
                    "aether_semantic_observations_abstained_total",
                    labels={"tenant_id": tenant_id, "reason": reason},
                )
                return await store.put_semantic(obs), []

        # 3. Classify + persist idempotently. Model-backed providers do REAL
        #    inference (or abstain, first-class) inside classify_event — the
        #    keyword classifier only ever runs, and is only ever stamped, as the
        #    explicit deterministic mode. A ProviderResponseError (malformed
        #    model output) propagates from classify_event BEFORE any persistence
        #    below — a rejected response is never partially ingested.
        started = time.perf_counter()
        obs, sentiments = await classify_event(payload, tenant_id, provider=provider)
        metrics.timing(
            "aether_semantic_classify_latency_ms", (time.perf_counter() - started) * 1000.0
        )
        if obs.status is ObservationStatus.CLASSIFIED:
            metrics.increment(
                "aether_semantic_observations_classified_total",
                labels={"tenant_id": tenant_id},
            )
        elif obs.status is ObservationStatus.ABSTAINED:
            metrics.increment(
                "aether_semantic_observations_abstained_total",
                labels={"tenant_id": tenant_id, "reason": obs.abstention_reason or "unspecified"},
            )
        stored_obs = await store.put_semantic(obs)
        stored_sentiments = [await store.put_sentiment(s) for s in sentiments]
        await self._shadow_compare(payload, tenant_id, stored_obs, stored_sentiments)
        return stored_obs, stored_sentiments

    async def _shadow_compare(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        primary_obs: SemanticObservation,
        primary_sentiments: list[SentimentObservation],
    ) -> None:
        """Shadow-mode candidate comparison — never affects the primary write.

        When ``settings.semantic.shadow_provider`` is set, the candidate
        provider's classification ALSO runs in-process and stance/intent/valence
        disagreements are recorded to the ``semantic_shadow_divergences`` JSONB
        fact table (one row per primary-observation identity + candidate model).
        The shadow output is never persisted as an observation and any shadow
        failure is logged and swallowed — the primary is already durably stored.

        Honest limit: with only the deterministic and fail-closed disabled
        providers available locally, a real model cannot diverge here; the
        divergence path is exercised in tests via a stub candidate provider.
        """
        shadow = get_shadow_provider(settings)
        if shadow is None:
            return
        try:
            if shadow.available():
                candidate_obs, candidate_sentiments = await classify_event(
                    payload, tenant_id, provider=shadow
                )
                candidate = {
                    "stance": candidate_obs.stance.value,
                    "intent": candidate_obs.intent.value,
                    "valence_sign": _valence_sign(candidate_sentiments),
                    "status": candidate_obs.status.value,
                    "abstention_reason": candidate_obs.abstention_reason,
                }
            else:
                # Fail-closed candidate (e.g. production mode, no creds): the
                # shadow abstains — compared as full disagreement, never keywords.
                candidate = {
                    "stance": None,
                    "intent": None,
                    "valence_sign": None,
                    "status": ObservationStatus.ABSTAINED.value,
                    "abstention_reason": shadow.abstention_reason() or "provider_disabled",
                }
            primary = {
                "stance": primary_obs.stance.value,
                "intent": primary_obs.intent.value,
                "valence_sign": _valence_sign(primary_sentiments),
                "status": primary_obs.status.value,
            }
            agreement = {
                "stance": primary["stance"] == candidate["stance"],
                "intent": primary["intent"] == candidate["intent"],
                "valence": primary["valence_sign"] == candidate["valence_sign"],
            }
            if all(agreement.values()):
                return
            from .repositories.base_fact_repo import SemanticFactRepository

            divergence_id = f"ssd_{uuid4().hex}"
            occurred_at = primary_obs.occurred_at.isoformat()
            await SemanticFactRepository("semantic_shadow_divergences").upsert(
                {
                    "id": divergence_id,
                    "tenant_id": tenant_id,
                    "source_event_id": primary_obs.source_event_id,
                    "subject_ref": primary_obs.primary_subject_ref,
                    "occurred_at": occurred_at,
                    "data": {
                        "id": divergence_id,
                        "idempotency_key": (
                            f"shadow:{primary_obs.idempotency_key}:{shadow.name}"
                        ),
                        "tenant_id": tenant_id,
                        "source_event_id": primary_obs.source_event_id,
                        "subject_ref": primary_obs.primary_subject_ref,
                        "primary_observation_id": primary_obs.observation_id,
                        "primary_model": f"{primary_obs.model_id}@{primary_obs.model_version}",
                        "shadow_model": shadow.name,
                        "primary": primary,
                        "candidate": candidate,
                        "agreement": agreement,
                        "occurred_at": occurred_at,
                        "created_at": utc_now().isoformat(),
                    },
                }
            )
        except Exception:
            logger.exception(
                "semantic shadow comparison failed for event %s", primary_obs.source_event_id
            )

    async def _consent_block(self, payload: dict[str, Any], tenant_id: str) -> Optional[str]:
        """Return a rejection reason if processing is unlawful, else None."""
        if not settings.consent_authority.authoritative_consent_enforcement_enabled:
            return None
        subject_id = payload.get("user_id") or payload.get("actor_ref")
        anonymous_id = payload.get("anonymous_id")
        purposes = payload.get("purposes") or ["analytics"]
        for purpose in purposes:
            allowed, reason = await evaluate_consent(tenant_id, subject_id, anonymous_id, purpose)
            if not allowed:
                return reason or "consent_denied"
        return None

    def _status_observation(
        self,
        payload: dict[str, Any],
        tenant_id: str,
        status: ObservationStatus,
        reason: str,
    ) -> SemanticObservation:
        """Build a content-free observation carrying only a terminal status.

        Used for consent-restricted / quarantined / provider-abstained events so
        the pipeline records that an event was seen without persisting content or
        an inferred interpretation.
        """
        actor_ref = str(payload.get("actor_ref") or payload.get("user_id") or "anonymous")
        subject = str(
            payload.get("primary_subject_ref")
            or payload.get("subject_ref")
            or payload.get("target_ref")
            or "unknown_subject"
        )
        return SemanticObservation(
            tenant_id=tenant_id,
            source_event_id=str(
                payload.get("source_event_id") or payload.get("event_id") or "event_unknown"
            ),
            source_type=str(payload.get("source_type") or payload.get("event_type") or "event"),
            actor_ref=actor_ref,
            actor_type=SubjectType.PROFILE,
            primary_subject_ref=subject,
            purposes=payload.get("purposes") or ["analytics"],
            consent_snapshot_id=payload.get("consent_snapshot_id"),
            classification_confidence=0.0,
            status=status,
            abstention_reason=reason,
        )

    # ── read path ──────────────────────────────────────────────────────────────

    async def get_observation(
        self, tenant_id: str, observation_id: str
    ) -> Optional[SemanticObservation]:
        rows = await get_store().list_semantic(tenant_id)
        for obs in rows:
            if obs.observation_id == observation_id:
                return obs
        return None

    async def list_observations(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 50
    ) -> tuple[list[SemanticObservation], bool]:
        rows = await get_store().list_semantic(tenant_id, subject)
        return rows[:limit], len(rows) > limit

    async def entity_state(self, tenant_id: str, entity_ref: str):
        return await entity_state(tenant_id, entity_ref)

    async def recompute_entity_state(self, tenant_id: str, entity_ref: str):
        """Recompute and durably persist an entity's Gold semantic state."""
        from .reducers import recompute_entity_state

        state = await recompute_entity_state(tenant_id, entity_ref)
        # Entity-level changes shift the tenant's cascades; refresh their Gold
        # projection in the same recompute pass (service-level wiring only).
        await self.recompute_cascades(tenant_id)
        return state

    async def gold_entity_state(
        self, tenant_id: str, entity_ref: str
    ) -> Optional[dict[str, Any]]:
        """Read the durable Gold semantic state for an entity (if any)."""
        from .repositories.base_fact_repo import SemanticFactRepository

        rows = await SemanticFactRepository("gold_entity_semantic_state").list_by_tenant(
            tenant_id, entity_ref, limit=1
        )
        return rows[0] if rows else None

    async def recompute_entity_sentiment(self, tenant_id: str, entity_ref: str) -> dict[str, Any]:
        from .reducers import recompute_entity_sentiment

        return await recompute_entity_sentiment(tenant_id, entity_ref)

    async def entity_sentiment_state(self, tenant_id: str, entity_ref: str) -> dict[str, Any]:
        """Durable Gold sentiment state, falling back to a live reduction."""
        from .repositories.base_fact_repo import SemanticFactRepository

        rows = await SemanticFactRepository("gold_entity_sentiment_state").list_by_tenant(
            tenant_id, entity_ref, limit=1
        )
        if rows:
            return rows[0]
        return await self.recompute_entity_sentiment(tenant_id, entity_ref)

    async def list_sentiment(
        self, tenant_id: str, subject: Optional[str] = None, *, limit: int = 50
    ) -> tuple[list[SentimentObservation], bool]:
        rows = await get_store().list_sentiment(tenant_id, subject)
        return rows[:limit], len(rows) > limit

    async def timeline(
        self, tenant_id: str, entity_ref: str, *, limit: int = 50
    ) -> dict[str, Any]:
        store = get_store()
        semantic = await store.list_semantic(tenant_id, entity_ref)
        sentiment = await store.list_sentiment(tenant_id, entity_ref)
        return {
            "semantic": semantic[:limit],
            "sentiment": sentiment[:limit],
            "partial": len(semantic) > limit or len(sentiment) > limit,
        }

    async def narratives(self, tenant_id: str) -> list[str]:
        rows = await get_store().list_semantic(tenant_id)
        return sorted({n for r in rows for n in r.narrative_frames})

    async def recompute_narrative_states(self, tenant_id: str) -> list[dict[str, Any]]:
        """Recompute and durably persist the tenant's per-narrative Gold state."""
        from .reducers import recompute_narrative_states

        return await recompute_narrative_states(tenant_id)

    async def narrative_states(self, tenant_id: str) -> list[dict[str, Any]]:
        """Durable per-narrative Gold aggregates, recomputing on a Gold miss."""
        from .repositories.base_fact_repo import SemanticFactRepository

        repo = SemanticFactRepository("gold_narrative_state")
        rows = await repo.list_by_tenant(tenant_id)
        if rows:
            return rows
        # No durable projection yet — build it, then serve the persisted rows.
        await self.recompute_narrative_states(tenant_id)
        return await repo.list_by_tenant(tenant_id)

    async def cascades(self, tenant_id: str):
        return await cascades_for_tenant(tenant_id)

    async def recompute_cascades(self, tenant_id: str):
        """Persist the tenant's live cascade projections to Gold (idempotent)."""
        from .reducers import recompute_cascades

        return await recompute_cascades(tenant_id)

    async def recompute_relationship_state(
        self, tenant_id: str, source_ref: str, target_ref: str
    ) -> dict[str, Any]:
        """Recompute and durably persist a directed pair's Gold relationship state."""
        from .reducers import recompute_relationship_sentiment, recompute_relationship_state

        state = await recompute_relationship_state(tenant_id, source_ref, target_ref)
        sentiment = await recompute_relationship_sentiment(tenant_id, source_ref, target_ref)
        return {"relationship_state": state, "sentiment_state": sentiment}

    async def relationship_state(
        self, tenant_id: str, source_ref: str, target_ref: str
    ) -> dict[str, Any]:
        """Durable Gold relationship state (semantic + sentiment), recomputing on miss."""
        from .reducers import relationship_ref
        from .repositories.base_fact_repo import SemanticFactRepository

        rel = relationship_ref(source_ref, target_ref)
        sem_repo = SemanticFactRepository("gold_relationship_semantic_state")
        sent_repo = SemanticFactRepository("gold_relationship_sentiment_state")
        sem_rows = await sem_repo.list_by_tenant(tenant_id, rel, limit=1)
        if not sem_rows:
            # No durable projection yet — recompute persists only observed pairs,
            # so an unobserved pair stays row-less (insufficient_data below).
            await self.recompute_relationship_state(tenant_id, source_ref, target_ref)
            sem_rows = await sem_repo.list_by_tenant(tenant_id, rel, limit=1)
        sent_rows = await sent_repo.list_by_tenant(tenant_id, rel, limit=1)
        return {
            "relationship_ref": rel,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "relationship_state": sem_rows[0] if sem_rows else None,
            "sentiment_state": sent_rows[0] if sent_rows else None,
            "insufficient_data": not sem_rows,
        }

    async def recompute_episodes(self, tenant_id: str, subject_ref: str):
        """Recompute and durably persist a subject's Gold episodes."""
        from .reducers import recompute_episodes

        return await recompute_episodes(tenant_id, subject_ref)

    async def episodes(self, tenant_id: str, subject_ref: str) -> list[dict[str, Any]]:
        """Durable Gold episodes for a subject, recomputing on a Gold miss."""
        from .repositories.base_fact_repo import SemanticFactRepository

        repo = SemanticFactRepository("gold_semantic_episodes")
        rows = await repo.list_by_tenant(tenant_id, subject_ref, limit=200)
        if rows:
            return rows
        # No durable projection yet — build it, then serve the persisted rows
        # (a subject without observations persists nothing and stays empty).
        await self.recompute_episodes(tenant_id, subject_ref)
        return await repo.list_by_tenant(tenant_id, subject_ref, limit=200)

    async def campaign_observations(
        self, tenant_id: str, campaign_id: str
    ) -> list[SemanticObservation]:
        rows = await get_store().list_semantic(tenant_id)
        return [o for o in rows if o.campaign_id == campaign_id]

    async def recompute_campaign_impact(
        self, tenant_id: str, campaign_id: str
    ) -> dict[str, Any]:
        from .reducers import recompute_campaign_impact

        return await recompute_campaign_impact(tenant_id, campaign_id)

    async def campaign_impact(self, tenant_id: str, campaign_id: str) -> dict[str, Any]:
        """Durable campaign semantic impact (Gold), falling back to a live reduction."""
        from .repositories.base_fact_repo import SemanticFactRepository

        gold = await SemanticFactRepository("gold_campaign_semantic_impact").list_by_tenant(
            tenant_id, campaign_id, limit=1
        )
        if gold:
            return gold[0]
        # No durable projection yet — compute on the fly (idempotent to persist later).
        return await self.recompute_campaign_impact(tenant_id, campaign_id)

    async def campaign_sentiment(
        self, tenant_id: str, campaign_id: str
    ) -> list[SentimentObservation]:
        store = get_store()
        semantic_ids = {
            o.observation_id
            for o in await store.list_semantic(tenant_id)
            if o.campaign_id == campaign_id
        }
        return [
            s
            for s in await store.list_sentiment(tenant_id)
            if s.semantic_observation_id in semantic_ids
        ]

    # ── operator surface (honest, DB-sourced) ────────────────────────────────────

    async def fleet_health(self) -> dict[str, Any]:
        store = get_store()
        counts = await store.aggregate_counts()
        semantic = counts.get("semantic", {})
        total = int(semantic.get("total", 0) or 0)
        by_status = semantic.get("by_status", {})
        abstained = int(by_status.get("abstained", 0) or 0)
        quarantined = int(by_status.get("quarantined", 0) or 0)
        consent_restricted = int(by_status.get("consent_restricted", 0) or 0)
        return {
            "enabled_tenants": int(semantic.get("tenants", 0) or 0),
            "classified_observations": total,
            "sentiment_observations": int(counts.get("sentiment", {}).get("total", 0) or 0),
            "abstention_rate": (abstained / total) if total else 0,
            "quarantined_observations": quarantined,
            "consent_restricted_observations": consent_restricted,
            "model_versions": _MODEL_VERSIONS,
            "status_breakdown": by_status,
        }

    async def enqueue_review(
        self,
        tenant_id: str,
        queue_type: str,
        *,
        subject_ref: Optional[str] = None,
        source_event_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        item = await self._review_queue.enqueue(
            tenant_id,
            queue_type,
            subject_ref=subject_ref,
            source_event_id=source_event_id,
            payload=payload,
        )
        _record_review_queue_gauge(await self._review_queue.counts(tenant_id))
        return item

    async def review_queue(
        self, tenant_id: str, queue_type: Optional[str] = None
    ) -> dict[str, Any]:
        items = await self._review_queue.list_open(tenant_id, queue_type)
        counts = await self._review_queue.counts(tenant_id)
        _record_review_queue_gauge(counts)
        return {
            "items": items,
            "count": len(items),
            "counts_by_queue": counts,
        }


_service: Optional[SemanticIntelligenceService] = None


def get_semantic_service() -> SemanticIntelligenceService:
    """Lazy module singleton (mirrors consent/authority repository singletons)."""
    global _service
    if _service is None:
        _service = SemanticIntelligenceService()
    return _service


def set_semantic_service(service: SemanticIntelligenceService) -> None:
    """Test/DI hook to swap the active service."""
    global _service
    _service = service
