"""Semantic identity-restatement consumer.

On identity merge/split, recompute the affected entities' durable Gold semantic +
sentiment state. Immutable Silver observations are never mutated — only the Gold
projections are re-derived (a merge folds the consumed entity's observations into
the survivor's Gold; a split re-derives each resulting entity from its own).
Clones ``services/measurement/identity_consumer.py``'s field extraction.
"""

from __future__ import annotations

from typing import Any

from shared.events.events import Event, Topic
from shared.logger.logger import get_logger

from .reducers import recompute_entity_sentiment, recompute_entity_state

logger = get_logger("aether.semantic.identity_consumer")


class SemanticIdentityConsumer:
    async def on_identity_merged(self, event: Event) -> None:
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        surviving = (
            payload.get("primary_entity_id")
            or payload.get("surviving_profile_id")
            or payload.get("profile_id_a")
        )
        merged = (
            payload.get("secondary_entity_id")
            or payload.get("merged_profile_id")
            or payload.get("profile_id_b")
        )
        if not tenant_id or not surviving:
            return
        surviving = str(surviving)
        refs = [surviving]
        if merged and str(merged) != surviving:
            refs.append(str(merged))
        try:
            # Fold the consumed entity's observations into the survivor's Gold.
            await recompute_entity_state(tenant_id, surviving, aggregate_refs=refs)
            await recompute_entity_sentiment(tenant_id, surviving, aggregate_refs=refs)
            # Recompute the consumed entity's own Gold so it reflects post-merge state.
            if len(refs) > 1:
                await recompute_entity_state(tenant_id, refs[1])
                await recompute_entity_sentiment(tenant_id, refs[1])
        except Exception:
            logger.exception("semantic identity_merged recompute failed for %s", surviving)

    async def on_identity_split(self, event: Event) -> None:
        payload = event.payload or {}
        tenant_id = event.tenant_id or payload.get("tenant_id", "")
        original = payload.get("original_entity_id")
        resulting = payload.get("resulting_entity_id")
        if not tenant_id or not original:
            return
        targets = [str(original)]
        if resulting and str(resulting) != str(original):
            targets.append(str(resulting))
        for entity_id in targets:
            try:
                await recompute_entity_state(tenant_id, entity_id)
                await recompute_entity_sentiment(tenant_id, entity_id)
            except Exception:
                logger.exception("semantic identity_split recompute failed for %s", entity_id)

    def register(self, consumer: Any) -> None:
        consumer.subscribe(Topic.IDENTITY_MERGED, self.on_identity_merged)
        consumer.subscribe(Topic.IDENTITY_SPLIT, self.on_identity_split)
