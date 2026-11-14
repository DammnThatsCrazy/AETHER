"""Correlation engine: store an observation, find candidates, decide, project.

On every new observation the engine

1. stores it (a repeated observation is a no-op),
2. derives its join keys: verified token task refs, exact object refs, signed
   request IDs, namespaced actor and infrastructure refs, and its time bucket,
3. finds candidates that share any key, or fall in its or an adjacent time
   bucket, bounded so one hostile record cannot fan out without limit,
4. runs the role-pair join rules against each candidate with a rule,
5. appends linked, candidate, and conflicting verdicts, and
6. projects newly linked verdicts into the graph.

No vendor name appears here: everything vendor-specific is in the mappers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional

from actions.agent_correlation.projection import GraphProjector
from actions.agent_correlation.repository import (
    CorrelationKeyIndexRepository,
    CorrelationObservationRepository,
    CorrelationVerdictRepository,
    own_time_bucket,
    time_buckets,
)
from shared.integration_contracts.correlation import (
    CorrelationObservation,
    CorrelationVerdict,
    correlate,
    join_keys_for,
)
from shared.integration_contracts.correlation_token import TokenVerifier

MAX_CANDIDATES = 500
# Rejections that only say "nothing matched" are noise and are not stored.
_STORED_REJECTIONS = frozenset({"conflicting_correlation_tokens"})


def _object_key(ref: Any) -> str:
    material = "|".join((ref.provider_family, ref.source_account_realm, ref.source_account_key, ref.object_type, ref.object_id))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def join_index_keys(obs: CorrelationObservation, verifier: Optional[TokenVerifier]) -> list[tuple[str, str]]:
    """Equality keys under which this observation can be found by others."""
    keys: list[tuple[str, str]] = []
    if verifier is not None:
        for token in obs.correlation_tokens:
            task_ref = verifier(token, obs.tenant_id)
            if task_ref:
                keys.append(("task", task_ref))
    keys.extend(("object", _object_key(ref)) for ref in obs.object_refs)
    if obs.signed_request is not None:
        keys.append(("signed_request", obs.signed_request.request_id))
    keys.extend(("actor", ref) for ref in obs.actor_refs)
    keys.extend(("infra", ref) for ref in obs.infrastructure_refs)
    return list(dict.fromkeys(keys))


@dataclass
class LinkDecision:
    other_observation_id: str
    verdict_id: str
    verdict: CorrelationVerdict
    newly_recorded: bool
    projection: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    observation_id: str
    source_role: str
    duplicate: bool
    decisions: list[LinkDecision] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "source_role": self.source_role,
            "duplicate": self.duplicate,
            "links": [
                {
                    "other_observation_id": d.other_observation_id,
                    "verdict_id": d.verdict_id,
                    "status": d.verdict.status,
                    "evidence_class": d.verdict.evidence_class,
                    "key_kind": d.verdict.key_kind,
                    "proves_link": d.verdict.proves_link,
                    "reason": d.verdict.reason,
                    **d.projection,
                }
                for d in self.decisions
            ],
        }


class CorrelationEngine:
    def __init__(
        self,
        *,
        token_verifier: Optional[TokenVerifier],
        time_window: timedelta = timedelta(minutes=5),
        observations: Optional[CorrelationObservationRepository] = None,
        keys: Optional[CorrelationKeyIndexRepository] = None,
        verdicts: Optional[CorrelationVerdictRepository] = None,
        projector: Optional[GraphProjector] = None,
    ) -> None:
        self._verifier = token_verifier
        self._window = time_window
        self._observations = observations or CorrelationObservationRepository()
        self._keys = keys or CorrelationKeyIndexRepository()
        self._verdicts = verdicts or CorrelationVerdictRepository()
        self._projector = projector or GraphProjector()

    async def ingest(self, obs: CorrelationObservation, *, provider: str, kind: str) -> IngestResult:
        stored = await self._observations.save(obs, provider=provider, kind=kind)
        result = IngestResult(observation_id=obs.observation_id, source_role=obs.source_role, duplicate=not stored)
        if not stored:
            return result

        index_keys = join_index_keys(obs, self._verifier)
        candidate_ids: list[str] = []
        lookups = index_keys + [("time", bucket) for bucket in time_buckets(obs.occurred_at, self._window)]
        for key_kind, key_value in lookups:
            for other_id in await self._keys.observations_for(obs.tenant_id, key_kind, key_value):
                if other_id != obs.observation_id and other_id not in candidate_ids:
                    candidate_ids.append(other_id)
            if len(candidate_ids) >= MAX_CANDIDATES:
                break
        await self._keys.index(
            obs.tenant_id,
            obs.observation_id,
            index_keys + [("time", own_time_bucket(obs.occurred_at, self._window))],
        )

        for other_id in candidate_ids[:MAX_CANDIDATES]:
            other = await self._observations.get_observation(obs.tenant_id, other_id)
            if other is None or not join_keys_for(obs.source_role, other.source_role):
                continue
            verdict = correlate(obs, other, token_verifier=self._verifier, time_window=self._window)
            if verdict.status in ("no_rule",) or (
                verdict.status == "rejected" and verdict.reason not in _STORED_REJECTIONS
            ):
                continue
            verdict_id, new = await self._verdicts.record(obs.tenant_id, obs, other, verdict)
            decision = LinkDecision(other_observation_id=other_id, verdict_id=verdict_id, verdict=verdict, newly_recorded=new)
            if new and verdict.status == "linked":
                decision.projection = await self._projector.project(obs, other, verdict, verdict_id)
            result.decisions.append(decision)
        return result
