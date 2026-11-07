"""Canonical episodes for authenticated, explicit case journey-link observations."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from graph.operational_intelligence.models import EntityRef, EvidenceRef
from journeys.support360.context_authorities import SupportCaseContextAuthorityError
from shared.backend_interpretation.primitives import EpisodeRecord
from shared.backend_interpretation.stores import EpisodeStore


async def publish_journey_link_episode(record: dict[str, Any]) -> EpisodeRecord:
    """Replay repairs a failed second write without inventing a business episode."""
    tenant_id = record["tenant_id"]
    event_id = record["context_event_id"]
    reference = EvidenceRef(
        id=event_id, type="event", source="support_case_context_events",
        uri=f"store://support_case_context_events/{quote(event_id, safe='')}",
        observedAt=record["received_at"],
    )
    evidence = [EvidenceRef.model_validate(raw) for raw in record["evidence_refs"]]
    if reference not in evidence or record["context_kind"] != "journey_links":
        raise SupportCaseContextAuthorityError("exact persisted journey context evidence is required")
    episode_id = str(uuid5(NAMESPACE_URL, f"support-journey-link:{tenant_id}:{event_id}"))
    episode = EpisodeRecord(
        episode_id=episode_id, tenant_id=tenant_id,
        subject=EntityRef(kind="resource", id=f"store://support_cases/{record['case_id']}"),
        kind="support_journey_link_observation", status="closed",
        occurred_from=record["effective_at"], occurred_to=record["effective_at"],
        journey_id=record["payload"]["journey_id"],
        observation_ids=[event_id], evidence_refs=evidence,
        source_event_id=record["source_event_id"],
        model_version="support-journey-link-observation.v1",
        created_at=record["received_at"], closed_at=record["received_at"],
    )
    document = episode.model_dump(mode="json")

    def preserve_exact(existing: dict[str, Any] | None) -> dict[str, Any]:
        if existing is not None and existing != document:
            raise SupportCaseContextAuthorityError("canonical support episode replay conflicts")
        return document

    try:
        store = EpisodeStore()
        await store._store.atomic_update(store._key(tenant_id, episode_id), preserve_exact)
    except SupportCaseContextAuthorityError:
        raise
    except Exception as exc:
        raise SupportCaseContextAuthorityError(
            "support episode persistence unavailable; replay the same context event"
        ) from exc
    return episode
