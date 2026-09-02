"""Durable, retryable resolution-replay worker (identity assurance layer).

Promotes resolution replay from an inline best-effort call in
:mod:`services.identity.evidence` to an event-driven worker. When verified
ownership evidence is issued or revoked, ``EvidenceService`` publishes
``IDENTITY_RESOLUTION_REPLAY_REQUESTED``; this consumer picks it up off the
request path and runs :class:`ResolutionReplayService.request_replay`.

Retry / dead-letter: the shared :class:`EventConsumer` retries a *raising*
handler up to its ``MAX_HANDLER_RETRIES`` and then dead-letters the event
(``services.runtime.consumer_specs`` sets the retry budget for this spec). So a
transient failure raises to trigger a retry, while success or a durably-recorded
idempotent no-op returns cleanly. The ``identity_resolution_replay_jobs`` ledger
keyed on ``{tenant}:{trigger}:{policy_version}`` makes a redelivery safe — a
completed job is never re-run, so a retry after a partial success cannot
double-merge.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger

from .metrics import IdentityMetrics

logger = get_logger("aether.identity.replay_consumer")


class IdentityReplayError(RuntimeError):
    """Raised by the handler to signal a retryable replay failure.

    Raising (rather than swallowing) is what drives the shared consumer's
    bounded retry + dead-letter path for this event.
    """


class IdentityReplayConsumer:
    """Runs resolution replay from ``IDENTITY_RESOLUTION_REPLAY_REQUESTED``."""

    def __init__(
        self,
        replay_service: Any = None,
        metrics: Optional[IdentityMetrics] = None,
    ) -> None:
        # Optional injected replay service (tests). None means build the real
        # resolver-backed service lazily on first event and cache it.
        self._replay_service = replay_service
        self._metrics = metrics or IdentityMetrics()

    def _build_replay_service(self) -> Any:
        """Lazily construct the real resolver-backed replay service (cached)."""
        if self._replay_service is not None:
            return self._replay_service
        from .resolution_replay import ResolutionReplayService
        from .repository import IdentityResolutionRepository
        from .graph_writer import IdentityGraphWriter
        from .audit import IdentityAuditWriter
        from .conflicts import IdentityConflictManager
        from .resolver import IdentityResolutionService

        repo = IdentityResolutionRepository()
        metrics = self._metrics
        resolver = IdentityResolutionService(
            repo=repo,
            graph_writer=IdentityGraphWriter(repo, metrics),
            audit_writer=IdentityAuditWriter(repo),
            conflict_manager=IdentityConflictManager(repo),
            metrics=metrics,
        )
        self._replay_service = ResolutionReplayService(
            resolver=resolver, repo=repo, metrics=metrics
        )
        return self._replay_service

    async def on_replay_requested(self, event: Event) -> None:
        """Handle one replay-requested event.

        Raises :class:`IdentityReplayError` on a replay error so the consumer
        retries and, once its budget is exhausted, dead-letters the event.
        """
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        identifier_type = payload.get("identifier_type", "")
        identifier_hash = payload.get("identifier_hash", "")
        trigger_type = payload.get("trigger_type", "verification_evidence_issued")
        trigger_id = payload.get("trigger_id", "")

        if not tenant_id or not identifier_hash or not trigger_id:
            # A structurally invalid event can never succeed on retry — record it
            # and return so it is dropped rather than pointlessly dead-lettered.
            logger.warning(
                "replay-requested event missing required fields: tenant=%s "
                "identifier_hash_present=%s trigger_id=%s event_id=%s",
                tenant_id, bool(identifier_hash), trigger_id, event.event_id,
            )
            self._metrics.record_resolution_replay("invalid")
            return

        replay = self._build_replay_service()
        result = await replay.request_replay(
            tenant_id=tenant_id,
            identifier_type=identifier_type,
            identifier_hash=identifier_hash,
            trigger_type=trigger_type,
            trigger_id=trigger_id,
            policy_version=payload.get("policy_version", "1.0.0"),
            consent_snapshot=payload.get("consent_snapshot"),
            verification=payload.get("verification"),
        )
        status = (result or {}).get("status")
        if status == "error":
            self._metrics.record_resolution_replay("retry")
            raise IdentityReplayError(
                f"resolution replay failed for trigger={trigger_id}: "
                f"{(result or {}).get('error')}"
            )
        self._metrics.record_resolution_replay("completed")

    def register(self, consumer: Any) -> None:
        """Register this handler with an :class:`EventConsumer` instance."""
        consumer.subscribe(
            Topic.IDENTITY_RESOLUTION_REPLAY_REQUESTED, self.on_replay_requested
        )
        logger.info(
            "IdentityReplayConsumer registered for "
            "IDENTITY_RESOLUTION_REPLAY_REQUESTED"
        )


__all__ = ["IdentityReplayConsumer", "IdentityReplayError"]
