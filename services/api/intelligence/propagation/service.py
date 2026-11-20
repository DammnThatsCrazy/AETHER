"""Propagation run orchestration: sources -> adoptions/exposures -> engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from intelligence.propagation.adoption import adoptions_from_fill_events
from intelligence.propagation.contracts import PropagationQuery, PropagationRun
from intelligence.propagation.engine import compute_propagation
from intelligence.propagation.exposure import exposures_from_edges, exposures_from_in_app_events
from intelligence.propagation.sources import PropagationSources, RepositoryPropagationSources


@dataclass(frozen=True)
class RunInputs:
    """What a run was computed from, kept with a saved run to judge staleness."""

    grant_refs: tuple[str, ...]
    population_digest: str


def population_digest(subjects_by_account: dict[tuple[str, str], str]) -> str:
    material = "\n".join(f"{v}\x1f{a}\x1f{s}" for (v, a), s in sorted(subjects_by_account.items()))
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


class PropagationService:
    """Runs one bounded, read-only propagation computation for a tenant."""

    def __init__(self, sources: Optional[PropagationSources] = None) -> None:
        self._sources = sources or RepositoryPropagationSources()
        self.last_inputs: Optional[RunInputs] = None

    async def run(self, query: PropagationQuery, *, include_live: bool = False) -> PropagationRun:
        bundle = await self._sources.load(query, include_live=include_live)
        self.last_inputs = RunInputs(
            grant_refs=tuple(sorted({
                str((e.get("payload") or {}).get("source_grant_ref"))
                for e in bundle.fill_events if (e.get("payload") or {}).get("source_grant_ref")
            })),
            population_digest=population_digest(bundle.subjects_by_account),
        )
        reasons = set(bundle.reasons)
        adoptions, adoption_reasons = adoptions_from_fill_events(
            query.tenant_id, bundle.fill_events, bundle.subjects_by_account,
        )
        edge_exposures, edge_reasons = exposures_from_edges(query.tenant_id, bundle.edges, channels=query.channels)
        app_exposures, app_reasons = exposures_from_in_app_events(query.tenant_id, bundle.in_app_rows)
        reasons |= adoption_reasons | edge_reasons | app_reasons
        if not bundle.subjects_by_account:
            reasons.add("no_linked_accounts")
        return compute_propagation(
            query,
            adoptions,
            [*edge_exposures, *app_exposures],
            bundle.population,
            limitations=sorted(reasons),
        )


__all__ = ["PropagationService", "RunInputs", "population_digest"]
