"""Correlation service: register tasks, ingest vendor records, explain chains."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from actions.agent_correlation.engine import CorrelationEngine
from actions.agent_correlation.keys import CorrelationKeyring
from actions.agent_correlation.mappers import AccountBinding, MapperContext, MappingError, map_record
from actions.agent_correlation.repository import (
    _digest,
    CorrelationKeyIndexRepository,
    CorrelationObservationRepository,
    CorrelationTaskRepository,
    CorrelationVerdictRepository,
)
from repositories.repos import BaseRepository
from shared.integration_contracts.correlation_token import issue_correlation_token
from shared.integration_contracts.source_roles import SOURCE_ROLES

MAX_CHAIN_NODES = 100
MAX_CHAIN_DEPTH = 6
_REALMS = ("live", "test")

# Where an agent can carry its token so the downstream record joins exactly.
STAMPING_GUIDANCE: Mapping[str, str] = {
    "stripe": "metadata.aether_correlation on the PaymentIntent, Charge, or Refund",
    "shopify": "the order note or a note attribute, or a product tag",
    "ramp": "the transaction memo, or the limit display name",
    "cloudflare": "AI Gateway request metadata",
    "github": "the pull request or issue body",
    "any": "any free-text or metadata field the system stores and returns",
}

_ROLE_GAP_MESSAGES: Mapping[str, str] = {
    "agent_runtime": "no agent runtime record is linked: who asked and which agent acted is unknown",
    "tool_bridge": "no tool call is linked: how the agent reached the system is unknown",
    "system_of_record": "no system-of-record effect is linked: what changed in the business system is unknown",
    "authority_issuer": "no authority record is linked: what the agent was allowed to do is unknown",
    "network_observer": "no network observation is linked: the traffic is uncorroborated",
}


class CorrelationUnavailable(RuntimeError):
    """Token issuance needs configured keys."""


class AccountBindingRepository(BaseRepository):
    """Tenant-declared provider accounts used to scope agent-side object refs."""

    def __init__(self) -> None:
        super().__init__("agent_correlation_account_bindings")

    async def put(self, tenant_id: str, family: str, account_key: str, realm: str) -> dict[str, Any]:
        return await self.insert("acb_" + _digest(tenant_id, family), {
            "tenant_id": tenant_id, "provider_family": family,
            "source_account_key": account_key, "source_account_realm": realm,
        })

    async def all_for(self, tenant_id: str) -> dict[str, AccountBinding]:
        rows = await self.find_many({"tenant_id": tenant_id}, limit=200)
        return {
            r["provider_family"]: AccountBinding(r["source_account_key"], r["source_account_realm"])
            for r in rows
            if r.get("tenant_id") == tenant_id
        }


def _parse_bindings(raw: Optional[Mapping[str, Any]]) -> dict[str, AccountBinding]:
    out: dict[str, AccountBinding] = {}
    for family, value in (raw or {}).items():
        if not isinstance(value, Mapping) or not str(value.get("source_account_key") or "").strip():
            raise MappingError(f"account binding for {family!r} needs source_account_key")
        realm = str(value.get("source_account_realm") or "live")
        if realm not in _REALMS:
            raise MappingError("source_account_realm must be live or test")
        out[str(family)] = AccountBinding(str(value["source_account_key"]).strip(), realm)
    return out


class CorrelationService:
    def __init__(
        self,
        *,
        keyring: Optional[CorrelationKeyring],
        time_window: timedelta = timedelta(minutes=5),
        engine: Optional[CorrelationEngine] = None,
        tasks: Optional[CorrelationTaskRepository] = None,
        observations: Optional[CorrelationObservationRepository] = None,
        keys: Optional[CorrelationKeyIndexRepository] = None,
        verdicts: Optional[CorrelationVerdictRepository] = None,
        bindings: Optional[AccountBindingRepository] = None,
    ) -> None:
        self.keyring = keyring
        self.observations = observations or CorrelationObservationRepository()
        self.keys = keys or CorrelationKeyIndexRepository()
        self.verdicts = verdicts or CorrelationVerdictRepository()
        self.tasks = tasks or CorrelationTaskRepository()
        self.bindings = bindings or AccountBindingRepository()
        self.engine = engine or CorrelationEngine(
            token_verifier=keyring.verifier() if keyring else None,
            time_window=time_window,
            observations=self.observations,
            keys=self.keys,
            verdicts=self.verdicts,
        )

    # ── tasks ────────────────────────────────────────────────────────────

    async def register_task(
        self,
        tenant_id: str,
        *,
        agent_platform: str,
        agent_ref: Optional[str] = None,
        principal_ref: Optional[str] = None,
        description: Optional[str] = None,
        ttl: timedelta = timedelta(days=7),
        now: Optional[datetime] = None,
    ) -> dict[str, Any]:
        if self.keyring is None:
            raise CorrelationUnavailable("correlation token keys are not configured (AGENT_CORRELATION_TOKEN_KEYS)")
        issued = issue_correlation_token(
            tenant_id=tenant_id,
            key_id=self.keyring.signing_key_id,
            secret=self.keyring.secret(self.keyring.signing_key_id),
            ttl=ttl,
            now=now,
        )
        await self.tasks.save(tenant_id, {
            "task_ref": issued.task_ref,
            "agent_platform": agent_platform,
            "agent_ref": agent_ref,
            # A principal named by the agent is a declaration, never proof.
            "declared_principal_ref": principal_ref,
            "description": (description or "")[:2000],
            "key_id": issued.key_id,
            "issued_at": issued.issued_at.isoformat(),
            "expires_at": issued.expires_at.isoformat(),
        })
        record = {
            "agent_platform": agent_platform,
            "task_ref": issued.task_ref,
            "correlation_token": issued.token,
            "registered_at": issued.issued_at.isoformat(),
        }
        if agent_ref:
            record["agent_ref"] = agent_ref
        ingest = await self.ingest_record(tenant_id, "aether_mcp", "task_registered", record)
        return {
            "task_ref": issued.task_ref,
            "correlation_token": issued.token,
            "expires_at": issued.expires_at.isoformat(),
            "stamp_token_in": dict(STAMPING_GUIDANCE),
            "observation": ingest[0] if ingest else None,
        }

    # ── ingestion ────────────────────────────────────────────────────────

    async def ingest_record(
        self,
        tenant_id: str,
        provider: str,
        kind: str,
        record: Mapping[str, Any],
        *,
        account_bindings: Optional[Mapping[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        bindings = await self.bindings.all_for(tenant_id)
        bindings.update(_parse_bindings(account_bindings))
        ctx = MapperContext(tenant_id=tenant_id, account_bindings=bindings)
        observations = map_record(provider, kind, ctx, record)
        results = []
        for obs in observations:
            result = await self.engine.ingest(obs, provider=provider, kind=kind)
            results.append(result.summary())
        return results

    # ── explanation ──────────────────────────────────────────────────────

    async def chain_for_task(self, tenant_id: str, task_ref: str) -> Optional[dict[str, Any]]:
        task = await self.tasks.get(tenant_id, task_ref)
        seeds = [f"aether_mcp:task:{task_ref}"]
        seeds += await self.keys.observations_for(tenant_id, "task", task_ref)
        chain = await self._chain(tenant_id, seeds)
        if task is None and not chain["observations"]:
            return None
        chain["task"] = (
            {k: task.get(k) for k in (
                "task_ref", "agent_platform", "agent_ref", "declared_principal_ref",
                "description", "issued_at", "expires_at",
            )}
            if task else None
        )
        return chain

    async def chain_for_observation(self, tenant_id: str, observation_id: str) -> Optional[dict[str, Any]]:
        if await self.observations.get(tenant_id, observation_id) is None:
            return None
        return await self._chain(tenant_id, [observation_id])

    async def _chain(self, tenant_id: str, seeds: list[str]) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        proven: dict[str, dict[str, Any]] = {}
        unproven: dict[str, dict[str, Any]] = {}
        queue = deque((s, 0) for s in dict.fromkeys(seeds))
        while queue and len(nodes) < MAX_CHAIN_NODES:
            obs_id, depth = queue.popleft()
            if obs_id in nodes:
                continue
            row = await self.observations.get(tenant_id, obs_id)
            if row is None:
                continue
            nodes[obs_id] = {
                "observation_id": obs_id,
                "source_role": row["source_role"],
                "provider": row["provider"],
                "kind": row["kind"],
                "provider_family": row["observation"]["provider_family"],
                "occurred_at": row["occurred_at"],
            }
            for v in await self.verdicts.for_observation(tenant_id, obs_id):
                link = {
                    "verdict_id": v["verdict_id"],
                    "from": v["left_observation_id"],
                    "to": v["right_observation_id"],
                    "status": v["status"],
                    "evidence_class": v["evidence_class"],
                    "key_kind": v.get("key_kind"),
                    "supporting_keys": v.get("supporting_keys") or [],
                    "reason": v["reason"],
                }
                if v["status"] == "linked":
                    proven[v["verdict_id"]] = link
                    other = v["right_observation_id"] if v["left_observation_id"] == obs_id else v["left_observation_id"]
                    if depth + 1 <= MAX_CHAIN_DEPTH:
                        queue.append((other, depth + 1))
                else:
                    unproven[v["verdict_id"]] = link

        ordered = sorted(nodes.values(), key=lambda n: (n["occurred_at"], n["observation_id"]))
        in_chain = set(nodes)
        roles_linked = {n["source_role"] for n in ordered}
        return {
            "observations": ordered,
            "proven_links": list(proven.values()),
            # Candidates and conflicts touching the chain: shown, never proof.
            "unproven_links": [l for l in unproven.values() if l["from"] in in_chain or l["to"] in in_chain],
            "gaps": [_ROLE_GAP_MESSAGES[r] for r in SOURCE_ROLES if r not in roles_linked],
            "truncated": len(nodes) >= MAX_CHAIN_NODES,
        }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
