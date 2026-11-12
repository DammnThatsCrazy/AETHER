"""Episode engine (WS-D item 2 / gap rows 26 + 31).

The canonical episode primitive (:class:`EpisodeRecord`,
``shared/backend_interpretation/primitives.py``) plus the engine that groups
observations/outcomes into episodes. An episode is a time-bounded,
subject-scoped, kind-tagged span that tells one story (a support ticket, a
user journey, an execution run) — NOT a competing system of record: the
underlying observations/outcomes stay canonical, the episode indexes them and
carries its own evidence lineage.

Boundary note (row 24 / execution capture): Noesis' recorder writes
``ai_execution_facts`` directly today, bypassing the ingestion gateway. That
row-24 execution-capture re-wiring is OUT of WS-D reach (it would change the
Noesis write path, which is WS-A/B owned and flag-gated separately); WS-D scopes
item 2 to the episode+episode360 surface. ``EpisodeEngine`` is written so a
future row-24 capture can enqueue into it without changing its contract.

Every method is safe to call with the engine flag OFF — the engine is just a
store over ``EpisodeRecord`` documents; callers decide when to drive it.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from shared.backend_interpretation.primitives import EpisodeRecord, evidence_ref
from shared.backend_interpretation.stores import EpisodeStore
from graph.operational_intelligence.models import EntityRef, EvidenceRef

_EPISODE_KEY_TTLED: dict[str, tuple[str, str, str]] = {}  # (episode_id) -> (tenant, kind, subject_key)
_SEMANTIC_OBSERVATION_AUTHORITY = "semantic_intelligence.silver_semantic_observations"


class EpisodeEngine:
    """Deterministic, tenant-scoped episode builder over the durable store.

    The engine keys an "open episode" by ``(tenant, subject, kind)``: the first
    observation for that key OPENS an episode, later observations append to it,
    and an explicit :meth:`close` (or a completion-kind observation) closes it.
    All writes go through :class:`EpisodeStore` so episodes are durable and
    replayable.
    """

    def __init__(
        self,
        store: Optional[EpisodeStore] = None,
        *,
        journey_source: Optional[Any] = None,
        authority_writer: Optional[Any] = None,
    ) -> None:
        self._store = store or EpisodeStore()
        self._journey_source = journey_source
        self._authority_writer = authority_writer
        self._open_cache: dict[str, Optional[str]] = {}

    @property
    def store(self) -> EpisodeStore:
        return self._store

    def _cache_key(self, tenant_id: str, subject: EntityRef, kind: str) -> str:
        return f"{tenant_id}:{subject.kind}:{subject.id}:{kind}"

    async def ingest_observation(
        self,
        *,
        tenant_id: str,
        subject: EntityRef,
        kind: str,
        evidence: Optional[EvidenceRef] = None,
        observation_id: Optional[str] = None,
        observation_authority: Optional[str] = None,
        journey_touchpoint_ids: Optional[Iterable[str]] = None,
        event_time: Optional[str] = None,
        source_event_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        completion_hint: bool = False,
    ) -> EpisodeRecord:
        """Open-or-append an episode for one observation.

        First observation for ``(tenant, subject, kind)`` creates the episode;
        subsequent ones append ``observation_id`` + ``evidence`` to it.
        ``completion_hint`` (a completion-kind observation or an explicit close
        event) closes the episode after the append.

        A caller that explicitly identifies a semantic Silver observation also
        produces its typed reference after the episode write. The reference
        writer independently verifies the exact tenant-owned observation and
        its backend-stamped namespace; this method never trusts the marker as
        source evidence.
        """
        open_id = await self._open_episode_id(tenant_id, subject, kind)
        if open_id is None:
            genesis = _first_str(
                observation_id, event_time, source_event_id,
                evidence.id if evidence is not None else None,
            )
            record = EpisodeRecord(
                episode_id=_episode_id(tenant_id, subject, kind, genesis),
                tenant_id=tenant_id,
                subject=subject,
                kind=kind,
                title=f"{kind} episode for {subject.kind}:{subject.id}",
                occurred_from=event_time,
                occurred_to=event_time,
                journey_touchpoint_ids=(
                    _unique_ids(journey_touchpoint_ids)
                    if journey_touchpoint_ids is not None
                    else None
                ),
                source_event_id=source_event_id
                or (evidence.id if evidence is not None else None),
                evidence_refs=[evidence] if evidence else [],
                observation_ids=[observation_id] if observation_id else [],
                model_version=None,
            )
            await self._store.upsert(record)
            self._open_cache[self._cache_key(tenant_id, subject, kind)] = record.episode_id
            await self._link_semantic_observation_reference(
                record, observation_id, observation_authority
            )
            if completion_hint:
                return await self.close(tenant_id, record.episode_id)
            return record

        record = await self._store.get(tenant_id, open_id)
        if record is None:
            # Cache pointed at a row that no longer exists: open fresh.
            return await self.ingest_observation(
                tenant_id=tenant_id,
                subject=subject,
                kind=kind,
                evidence=evidence,
                observation_id=observation_id,
                observation_authority=observation_authority,
                journey_touchpoint_ids=journey_touchpoint_ids,
                event_time=event_time,
                source_event_id=source_event_id,
                correlation_id=correlation_id,
                completion_hint=completion_hint,
            )
        return await self.append(
            record,
            evidence=evidence,
            observation_id=observation_id,
            observation_authority=observation_authority,
            journey_touchpoint_ids=journey_touchpoint_ids,
            event_time=event_time,
            completion_hint=completion_hint,
        )

    async def append(
        self,
        record: EpisodeRecord,
        *,
        evidence: Optional[EvidenceRef] = None,
        observation_id: Optional[str] = None,
        observation_authority: Optional[str] = None,
        outcome_id: Optional[str] = None,
        journey_touchpoint_ids: Optional[Iterable[str]] = None,
        event_time: Optional[str] = None,
        completion_hint: bool = False,
    ) -> EpisodeRecord:
        """Append evidence/observations/outcomes to an open episode."""
        if record.status != "open":
            raise ValueError(
                f"episode {record.episode_id!r} is {record.status!r}, not open"
            )
        if observation_id and observation_id not in record.observation_ids:
            record.observation_ids.append(observation_id)
        if outcome_id and outcome_id not in record.outcome_ids:
            record.outcome_ids.append(outcome_id)
        if journey_touchpoint_ids is not None:
            existing_touchpoint_ids = record.journey_touchpoint_ids or []
            record.journey_touchpoint_ids = _unique_ids(
                [*existing_touchpoint_ids, *journey_touchpoint_ids]
            )
        if evidence and evidence.id not in {r.id for r in record.evidence_refs}:
            record.evidence_refs.append(evidence)
        if event_time is not None:
            if record.occurred_from is None or event_time < record.occurred_from:
                record.occurred_from = event_time
            if record.occurred_to is None or event_time > record.occurred_to:
                record.occurred_to = event_time
        await self._store.upsert(record)
        await self._link_semantic_observation_reference(
            record, observation_id, observation_authority
        )
        if completion_hint:
            return await self.close(record.tenant_id, record.episode_id)
        return record

    async def _link_semantic_observation_reference(
        self,
        record: EpisodeRecord,
        observation_id: Optional[str],
        observation_authority: Optional[str],
    ) -> None:
        if (
            not observation_id
            or observation_authority != _SEMANTIC_OBSERVATION_AUTHORITY
        ):
            return
        from shared.backend_interpretation.flags import episode_engine_enabled

        if episode_engine_enabled():
            # The episode row already exists. Propagate a failed authority read
            # or write so a replay retries this idempotent exact link; Episode360
            # treats the row as unresolved until the typed link is present.
            await self.link_observation_reference(
                record.tenant_id, record.episode_id, observation_id
            )

    async def link_outcome(
        self, tenant_id: str, episode_id: str, outcome_id: str
    ) -> EpisodeRecord:
        record = await self._store.get(tenant_id, episode_id)
        if record is None:
            raise KeyError(f"episode {episode_id!r} not found for tenant {tenant_id!r}")
        if outcome_id not in record.outcome_ids:
            record.outcome_ids.append(outcome_id)
            await self._store.upsert(record)
        return record

    async def link_journey_touchpoint(
        self, tenant_id: str, episode_id: str, touchpoint_id: str
    ) -> EpisodeRecord:
        """Record an explicit journey-touchpoint link on one exact episode.

        The episode writer must call this only when it has the canonical
        relationship. Episode360 independently resolves ``touchpoint_id``
        through the tenant-scoped touchpoint authority and will omit missing,
        out-of-scope, or unevidenced rows. This method never joins by time,
        subject labels, campaign labels, or attribution credit.
        """
        normalized_touchpoint_id = _first_str(touchpoint_id)
        if normalized_touchpoint_id is None:
            raise ValueError("link_journey_touchpoint requires a non-empty touchpoint_id")
        record = await self._store.get(tenant_id, episode_id)
        if record is None:
            raise KeyError(f"episode {episode_id!r} not found for tenant {tenant_id!r}")
        record.journey_touchpoint_ids = _unique_ids(
            [*(record.journey_touchpoint_ids or []), normalized_touchpoint_id]
        )
        await self._store.upsert(record)
        return record

    async def link_journey(
        self,
        tenant_id: str,
        episode_id: str,
        journey_id: str,
        *,
        evidence: EvidenceRef,
    ) -> EpisodeRecord:
        """Attach an episode to one exact journey with source evidence.

        The writer must already know the canonical relation. This method does
        not infer it from the episode subject, timestamps, journey steps, or
        matching IDs. Re-linking to a different journey is rejected.
        """
        normalized_journey_id = _first_str(journey_id)
        if normalized_journey_id is None:
            raise ValueError("link_journey requires a non-empty journey_id")
        if not isinstance(evidence, EvidenceRef) or not evidence.id or not evidence.source:
            raise ValueError("link_journey requires source evidence")
        record = await self._store.get(tenant_id, episode_id)
        if record is None:
            raise KeyError(f"episode {episode_id!r} not found for tenant {tenant_id!r}")
        if record.journey_id not in (None, normalized_journey_id):
            raise ValueError("episode is already linked to a different canonical journey")
        source = self._journey_source
        if source is None:
            from journeys.measurement.repositories.journey_repo import JourneyRepository

            source = JourneyRepository()
        try:
            journey = await source.get_current(tenant_id, normalized_journey_id)
        except Exception as exc:  # noqa: BLE001 - writer cannot bind against an unread source
            raise RuntimeError("canonical journey authority is unavailable") from exc
        if (
            not isinstance(journey, dict)
            or journey.get("tenant_id") != tenant_id
            or str(journey.get("journey_id")) != normalized_journey_id
            or journey.get("is_current") is not True
        ):
            raise KeyError(
                f"current journey {normalized_journey_id!r} not found for tenant {tenant_id!r}"
            )
        record.journey_id = normalized_journey_id
        evidence_key = (evidence.id, evidence.type, evidence.source)
        if evidence_key not in {
            (ref.id, ref.type, ref.source) for ref in record.evidence_refs
        }:
            record.evidence_refs.append(evidence)
        await self._store.upsert(record)
        return record

    async def link_agent_handoff(
        self,
        tenant_id: str,
        episode_id: str,
        execution_id: str,
    ) -> Any:
        """Persist an execution/delegation link after exact source validation.

        A link is accepted only when the canonical agent execution names an
        observation already attached to this agent episode and the execution
        references a tenant-owned delegation valid at execution time.
        """
        writer = self._authority_writer
        if writer is None:
            from journeys.measurement.episodes.related_authorities import (
                EpisodeJourneyAuthorityWriter,
            )

            writer = EpisodeJourneyAuthorityWriter(episode_store=self._store)
        return await writer.link_agent_handoff(
            tenant_id=tenant_id,
            episode_id=episode_id,
            execution_id=execution_id,
        )

    async def link_observation_reference(
        self, tenant_id: str, episode_id: str, observation_id: str
    ) -> Any:
        """Bind a recorded observation to its exact canonical source namespace.

        The writer reads the tenant-owned semantic Silver row and refuses to
        create a typed link when its source namespace or event lineage is absent.
        """
        writer = self._authority_writer
        if writer is None:
            from journeys.measurement.episodes.related_authorities import (
                EpisodeJourneyAuthorityWriter,
            )

            writer = EpisodeJourneyAuthorityWriter(episode_store=self._store)
        return await writer.link_observation_reference(
            tenant_id=tenant_id,
            episode_id=episode_id,
            observation_id=observation_id,
        )

    async def link_attribution_credit(
        self,
        tenant_id: str,
        episode_id: str,
        outcome_id: str,
        conversion_id: str,
        attribution_run_id: str,
        credit_id: str,
    ) -> Any:
        """Persist one exact outcome → conversion → active credit association."""
        writer = self._authority_writer
        if writer is None:
            from journeys.measurement.episodes.related_authorities import (
                EpisodeJourneyAuthorityWriter,
            )

            writer = EpisodeJourneyAuthorityWriter(episode_store=self._store)
        return await writer.link_attribution_credit(
            tenant_id=tenant_id,
            episode_id=episode_id,
            outcome_id=outcome_id,
            conversion_id=conversion_id,
            attribution_run_id=attribution_run_id,
            credit_id=credit_id,
        )

    async def close(self, tenant_id: str, episode_id: str) -> EpisodeRecord:
        record = await self._store.get(tenant_id, episode_id)
        if record is None:
            raise KeyError(f"episode {episode_id!r} not found for tenant {tenant_id!r}")
        if record.status == "open":
            record.status = "closed"
        await self._store.upsert(record)
        # Drop the open-cache entry so a NEW episode may open for the key.
        self._open_cache.pop(
            self._cache_key(record.tenant_id, record.subject, record.kind), None
        )
        return record

    async def reopen(self, tenant_id: str, episode_id: str) -> EpisodeRecord:
        record = await self._store.get(tenant_id, episode_id)
        if record is None:
            raise KeyError(f"episode {episode_id!r} not found for tenant {tenant_id!r}")
        if record.status in ("closed", "unknown"):
            record.status = "open"
            await self._store.upsert(record)
        return record

    async def _open_episode_id(
        self, tenant_id: str, subject: EntityRef, kind: str
    ) -> Optional[str]:
        cache_key = self._cache_key(tenant_id, subject, kind)
        if cache_key in self._open_cache:
            return self._open_cache[cache_key]
        episodes = await self._store.list_for_subject(
            tenant_id, subject.kind, subject.id
        )
        open_ones = [e for e in episodes if e.kind == kind and e.status == "open"]
        if open_ones:
            # Deterministic: reuse the earliest-open episode for the key.
            chosen = min(open_ones, key=lambda e: e.created_at)
            self._open_cache[cache_key] = chosen.episode_id
            return chosen.episode_id
        self._open_cache[cache_key] = None
        return None

    # ── Batch convenience ────────────────────────────────────────────────────

    async def ingest_batch(
        self,
        *,
        tenant_id: str,
        subject: EntityRef,
        kind: str,
        observations: Iterable[dict[str, Any]],
        extract_evidence: Optional[Any] = None,
        journey_touchpoint_ids: Optional[Iterable[str]] = None,
    ) -> EpisodeRecord:
        """Fold many normalized observation records into one episode.

        ``extract_evidence`` (optional) maps a record to an :class:`EvidenceRef`
        / dict; the default builds one from the record's ``event.id`` when
        present.
        """
        record: Optional[EpisodeRecord] = None
        for obs in observations:
            event_block = obs.get("event") if isinstance(obs.get("event"), dict) else {}
            evidence = None
            if extract_evidence is not None:
                evidence = extract_evidence(obs)
            else:
                event_id = event_block.get("id") or obs.get("event_id")
                if event_id:
                    source_block = (
                        obs.get("source") if isinstance(obs.get("source"), dict) else {}
                    )
                    evidence = evidence_ref(
                        evidence_id=str(event_id),
                        evidence_type="event",
                        source=source_block.get("type") or "sdk",
                    )
            obs_id = event_block.get("id")
            temporal_block = (
                obs.get("temporal") if isinstance(obs.get("temporal"), dict) else {}
            )
            event_time = temporal_block.get("source_time") or temporal_block.get(
                "occurred_at"
            )
            completion_hint = event_block.get("type") == "episode.close"
            record = await self.ingest_observation(
                tenant_id=tenant_id,
                subject=subject,
                kind=kind,
                evidence=evidence,
                observation_id=obs_id,
                journey_touchpoint_ids=journey_touchpoint_ids,
                event_time=event_time,
                source_event_id=obs_id,
                completion_hint=bool(completion_hint),
            )
        if record is None:
            raise ValueError("ingest_batch requires >= 1 observation")
        return record


def _first_str(*values: Any) -> Optional[str]:
    for value in values:
        if value is not None and str(value).strip():
            return str(value)
    return None


def _unique_ids(values: Iterable[Any]) -> list[str]:
    """Normalize an explicit reference list without inventing any IDs."""
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _first_str(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _episode_id(
    tenant_id: str, subject: EntityRef, kind: str, genesis: Optional[str]
) -> str:
    """Deterministic episode id: stable per episode, distinct across episodes.

    Two episodes for the same ``(tenant, subject, kind)`` key are
    distinguished by their *genesis* — the first observation id / event time /
    source event that opened them. Pure (tenant, subject, kind) digesting
    would collide and overwrite a closed row when a second episode opens for
    the same key.
    """
    import hashlib

    digest = hashlib.sha256(
        f"{tenant_id}:{subject.kind}:{subject.id}:{kind}:{genesis or ''}".encode()
    ).hexdigest()[:16]
    return f"ep-{digest}"


__all__ = ["EpisodeEngine"]
