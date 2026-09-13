"""episode360 intelligence-projection provider (WS-D item 2 surface).

Projects durable :class:`~shared.backend_interpretation.primitives.EpisodeRecord`
rows into the six ``episode360`` registry output sections (``evidence``,
``interactions``, ``outcomes``, ``state``, ``summary``, ``timeline``). A 360 is
an intelligence projection over canonical truth — never a competing system of
record — so the provider is ``read_only`` and every claim stays grounded in the
episode's own :class:`EvidenceRef` lineage.

Registry row ``episode360`` is ``in_flight`` (``implementationBlueprint:
docs/blueprints/episode360.md``); this provider is the WS-D read surface that
row was waiting on. It follows the outcome360 fail-isolated contract: a missing
store degrades sections to typed ``missing``/``empty`` and never raises, so the
plane stays up when the episode store is empty or unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from shared.backend_interpretation.primitives import EpisodeRecord
from shared.backend_interpretation.stores import EpisodeStore
from shared.intelligence_projections.contracts import (
    ClaimEnvelope,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.provider import IntelligenceProjectionProvider
from shared.intelligence_projections.registry import ProviderRegistry
from services.operational_intelligence.models import PageInfo

_EPISODE360_SECTIONS = ("evidence", "interactions", "outcomes", "state", "summary", "timeline")

_SECTION_TITLES = {
    "summary": "Episode summary",
    "state": "Episode state distribution",
    "evidence": "Episode evidence",
    "interactions": "Episode interactions",
    "outcomes": "Episode outcomes",
    "timeline": "Episode timeline",
}


class Episode360Provider:
    """The ``episode360`` intelligence projection provider (read_only)."""

    projection_id = "episode360"
    contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    def __init__(self, episode_store: Optional[EpisodeStore] = None) -> None:
        """``episode_store`` may be injected (tests); defaults to the durable
        :class:`EpisodeStore` (WS-D item 2)."""
        self._episode_store = episode_store

    def _load_store(self) -> Optional[EpisodeStore]:
        if self._episode_store is not None:
            return self._episode_store
        try:
            return EpisodeStore()
        except Exception:  # noqa: BLE001 - fail-isolated: never crash the plane
            return None

    async def _load_episodes(self, request: ProjectionRequest) -> list[EpisodeRecord]:
        from shared.backend_interpretation.stores import subject_matches_request

        store = self._load_store()
        if store is None:
            return []
        episodes = await store.list_by_tenant(request.tenantId)
        subject = request.subject
        return [
            e
            for e in episodes
            if subject_matches_request(e.subject, subject.kind, subject.id)
        ]

    async def project(
        self,
        request: ProjectionRequest,
        context: ProjectionContext,
    ) -> ProjectionResult:
        """Run one tenant-scoped episode360 projection."""
        episodes = await self._load_episodes(request)
        store_present = self._load_store() is not None
        availability = _availability(store_present, bool(episodes))
        sections = self._build_sections(episodes, availability)
        claims = self._build_claims(request, episodes)
        return ProjectionResult(
            projectionId=self.projection_id,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=sections,
            claims=claims,
            dependencyState=context.dependencyState,
            asOf=context.asOf,
            generatedAt=datetime.now(timezone.utc).isoformat(),
            page=PageInfo(hasNextPage=False, totalEstimate=len(episodes))
            if request.page is not None
            else None,
            degradedReasons=[],
            temporalMode=request.temporalMode or "window",
        )

    # ── Rendering ────────────────────────────────────────────────────────────

    def _build_sections(
        self, episodes: list[EpisodeRecord], availability: str
    ) -> list[ProjectionSection]:
        by_kind = _kind_counts(episodes)
        by_status = _status_distribution(episodes)
        evidence = _collect_evidence(episodes)
        interaction_count = sum(len(e.observation_ids) for e in episodes)
        outcome_count = sum(len(e.outcome_ids) for e in episodes)
        return [
            ProjectionSection(
                id="summary",
                state=availability,
                title=_SECTION_TITLES["summary"],
                content={
                    "episodeCount": len(episodes),
                    "openCount": by_status.get("open", 0),
                    "interactionCount": interaction_count,
                    "outcomeCount": outcome_count,
                    "kinds": by_kind,
                    "stateDistribution": by_status,
                },
            ),
            ProjectionSection(
                id="state",
                state=availability,
                title=_SECTION_TITLES["state"],
                content={"distribution": by_status},
            ),
            ProjectionSection(
                id="evidence",
                state=_availability(availability != "missing", bool(evidence)),
                title=_SECTION_TITLES["evidence"],
                content={
                    "evidence": [ref.model_dump() for ref in evidence],
                    "evidenceCount": len(evidence),
                },
            ),
            ProjectionSection(
                id="interactions",
                state=availability,
                title=_SECTION_TITLES["interactions"],
                content={
                    "interactionCount": interaction_count,
                    "observationIds": _flatten(e.observation_ids for e in episodes),
                },
            ),
            ProjectionSection(
                id="outcomes",
                state=availability,
                title=_SECTION_TITLES["outcomes"],
                content={
                    "outcomeCount": outcome_count,
                    "outcomeIds": _flatten(e.outcome_ids for e in episodes),
                },
            ),
            ProjectionSection(
                id="timeline",
                state=availability,
                title=_SECTION_TITLES["timeline"],
                content={
                    "timeline": [
                        {
                            "episodeId": e.episode_id,
                            "kind": e.kind,
                            "status": e.status,
                            "occurredFrom": e.occurred_from,
                            "occurredTo": e.occurred_to,
                            "observationCount": len(e.observation_ids),
                            "outcomeCount": len(e.outcome_ids),
                        }
                        for e in sorted(
                            episodes,
                            key=lambda e: e.occurred_from or e.created_at or "",
                        )
                    ]
                },
            ),
        ]

    def _build_claims(
        self, request: ProjectionRequest, episodes: list[EpisodeRecord]
    ) -> list[ClaimEnvelope]:
        claims: list[ClaimEnvelope] = []
        for episode in episodes:
            claims.append(
                ClaimEnvelope(
                    id=f"episode.{episode.episode_id}.span",
                    kind="episode",
                    subject=request.subject,
                    evidenceRefs=episode.evidence_refs,
                    claims=[
                        f"episode {episode.episode_id!r} ({episode.kind!r}) "
                        f"spans {episode.observation_ids and len(episode.observation_ids) or 0} "
                        f"observations and is {episode.status}"
                    ],
                )
            )
        return claims


def register_provider(registry: ProviderRegistry) -> str:
    """Register the Episode360 provider on a ``ProviderRegistry`` instance."""
    return registry.register(
        Episode360Provider(),
        source="services/measurement/episodes",
    )


# ── Module helpers ───────────────────────────────────────────────────────────


def _availability(store_present: bool, present: bool) -> str:
    if present:
        return "available"
    return "empty" if store_present else "missing"


def _kind_counts(episodes: list[EpisodeRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in episodes:
        counts[e.kind] = counts.get(e.kind, 0) + 1
    return dict(sorted(counts.items()))


def _status_distribution(episodes: list[EpisodeRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in episodes:
        counts[e.status] = counts.get(e.status, 0) + 1
    return dict(sorted(counts.items()))


def _collect_evidence(episodes: list[EpisodeRecord]) -> list[Any]:
    seen: set[str] = set()
    refs: list[Any] = []
    for e in episodes:
        for ref in e.evidence_refs:
            if ref.id in seen:
                continue
            seen.add(ref.id)
            refs.append(ref)
    return refs


def _flatten(lists: Any) -> list[str]:
    result: list[str] = []
    for item in lists:
        for value in item:
            if value not in result:
                result.append(value)
    return result


__all__ = ["Episode360Provider", "register_provider"]
