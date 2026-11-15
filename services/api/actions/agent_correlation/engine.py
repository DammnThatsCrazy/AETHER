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
            if not await self._observations.is_correlated(obs.tenant_id, obs.observation_id):
                # The first delivery saved the observation but failed before
                # indexing and correlation finished: resume them (both are
                # idempotent) instead of treating the stored row as complete.
                await self._correlate(obs, result)
                await self._observations.mark_correlated(obs.tenant_id, obs.observation_id)
                return result
            # A redelivery completes any graph projection a transient outage left
            # unfinished; observation existence alone is not projection success.
            await self._retry_incomplete_projections(obs.tenant_id, obs.observation_id, result)
            return result
        await self._correlate(obs, result)
        await self._observations.mark_correlated(obs.tenant_id, obs.observation_id)
        return result

    async def _correlate(self, obs: CorrelationObservation, result: "IngestResult") -> None:
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
            if verdict.status == "linked" and (
                    new or not _projection_complete(await self._verdicts.get(obs.tenant_id, verdict_id))):
                decision.projection = await self._project(obs, other, verdict, verdict_id)
            result.decisions.append(decision)

    async def _project(self, left: CorrelationObservation, right: CorrelationObservation,
                       verdict: Any, verdict_id: str) -> dict[str, Any]:
        try:
            report = await self._projector.project(left, right, verdict, verdict_id)
        except Exception as exc:  # noqa: BLE001 - recorded as failed and retried on redelivery
            report = {"graph_projection_status": "failed", "graph_mutations_persisted": 0,
                      "error_type": type(exc).__name__}
        await self._verdicts.mark_projection(left.tenant_id, verdict_id, report)
        return report

    async def _retry_incomplete_projections(self, tenant_id: str, observation_id: str,
                                            result: "IngestResult") -> None:
        from shared.integration_contracts.correlation import CorrelationVerdict

        fields = set(CorrelationVerdict.model_fields)
        for row in await self._verdicts.for_observation(tenant_id, observation_id):
            if row.get("status") != "linked" or _projection_complete(row):
                continue
            left = await self._observations.get_observation(tenant_id, row["left_observation_id"])
            right = await self._observations.get_observation(tenant_id, row["right_observation_id"])
            if left is None or right is None:
                continue
            verdict = CorrelationVerdict.model_validate({k: v for k, v in row.items() if k in fields})
            other = right.observation_id if left.observation_id == observation_id else left.observation_id
            decision = LinkDecision(other_observation_id=other, verdict_id=row["verdict_id"], verdict=verdict,
                                    newly_recorded=False)
            decision.projection = await self._project(left, right, verdict, row["verdict_id"])
            result.decisions.append(decision)


_COMPLETE_PROJECTIONS = frozenset({"persisted", "not_applicable"})


def _projection_complete(row: Optional[dict[str, Any]]) -> bool:
    return bool(row) and row.get("graph_projection_status") in _COMPLETE_PROJECTIONS
