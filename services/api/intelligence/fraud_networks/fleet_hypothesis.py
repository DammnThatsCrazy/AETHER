"""Evidence-qualified fleet hypotheses: do these agents share a controlling operator?

An orchestrator that spawns 10-20 sub-agents leaves a structural trail (the spawn
tree) and circumstantial ones (shared endpoints, identical tool sequences, spawn
bursts, overlapping targets). Only some of that can support a link to a person.

Rules this module enforces:
- A hypothesis is never "confirmed" by the builder. Status starts at
  ``unconfirmed`` or ``needs_review``; only a human reviewer can move it to
  ``confirmed_by_reviewer`` or ``rejected_by_reviewer``.
- Circumstantial evidence (shared endpoint, tool sequence, timing, targets)
  can never lift confidence above ``CIRCUMSTANTIAL_CAP``. Only an observed
  canonical delegation from a human principal to the orchestrator can, and
  even then confidence stays below ``DELEGATION_CAP``.
- Delegation proves authority was granted, not intent. The person link is
  always accompanied by the competing explanation that the principal may be
  a victim of a hijacked orchestrator.
- Competing explanations are generated from the evidence, never omitted.
"""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import urlparse

from repositories.repos import BaseRepository
from shared.common.common import utc_now

CIRCUMSTANTIAL_CAP = 0.55
DELEGATION_CAP = 0.9
NEEDS_REVIEW_THRESHOLD = 0.35
MIN_FLEET_SIZE = 3
SPAWN_BURST_WINDOW_SECONDS = 120
SPAWN_BURST_MIN = 3

STATUS_UNCONFIRMED = "unconfirmed"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_CONFIRMED = "confirmed_by_reviewer"
STATUS_REJECTED = "rejected_by_reviewer"
_REVIEW_STATUSES = {"confirm": STATUS_CONFIRMED, "reject": STATUS_REJECTED}

# evidence type -> (basis, strength). Strength is a weight, not a probability.
_EVIDENCE_WEIGHTS = {
    "observed_spawn_tree": ("observed", 0.30),
    "spawn_burst": ("inferred", 0.10),
    "shared_endpoint": ("inferred", 0.15),
    "identical_tool_sequence": ("inferred", 0.15),
    "overlapping_targets": ("inferred", 0.20),
    "canonical_principal_delegation": ("observed", 0.60),
}
_CIRCUMSTANTIAL = {
    "spawn_burst", "shared_endpoint", "identical_tool_sequence", "overlapping_targets",
}


@dataclass
class AgentObservation:
    agent_ref: str
    first_seen_at: Optional[str] = None
    spawned_at: Optional[str] = None
    tool_sequence: list[str] = field(default_factory=list)
    endpoint_hosts: set[str] = field(default_factory=set)
    target_refs: set[str] = field(default_factory=set)
    event_refs: list[str] = field(default_factory=list)


def _host(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url.strip():
        return None
    host = urlparse(url if "//" in url else f"//{url}").hostname
    return host.lower() if host else None


def observations_from_rows(
    rows: Iterable[dict[str, Any]], tenant_id: str, agent_refs: Iterable[str]
) -> dict[str, AgentObservation]:
    """Fold Silver agent execution rows into per-agent observations."""
    wanted = set(agent_refs)
    out = {ref: AgentObservation(agent_ref=ref) for ref in wanted}
    for row in sorted(rows, key=lambda r: str(r.get("occurred_at") or "")):
        if row.get("tenant_id") != tenant_id:
            continue
        name = str(row.get("source_event_type") or row.get("event_name") or "")
        occurred = str(row.get("occurred_at") or "") or None
        if name == "agent_subagent_spawned":
            child = row.get("child_agent_ref")
            if child in out and (out[child].spawned_at is None or (occurred and occurred < out[child].spawned_at)):
                out[child].spawned_at = occurred
        ref = row.get("agent_id")
        if ref not in out:
            continue
        obs = out[ref]
        obs.first_seen_at = obs.first_seen_at or occurred
        if row.get("tool_name"):
            obs.tool_sequence.append(str(row["tool_name"]))
        host = _host(row.get("server_url"))
        if host:
            obs.endpoint_hosts.add(host)
        if row.get("object_id") and str(row.get("object_type") or "") in {"wallet", "account", "address"}:
            obs.target_refs.add(f"{row['object_type']}:{row['object_id']}")
        if row.get("source_event_id") and len(obs.event_refs) < 25:
            obs.event_refs.append(str(row["source_event_id"]))
    return out


def _seconds(a: str, b: str) -> Optional[float]:
    from shared.temporal.instant import try_parse_instant

    da, _ = try_parse_instant(a)
    db, _ = try_parse_instant(b)
    return abs((db - da).total_seconds()) if da and db else None


def _burst(spawn_times: list[str]) -> Optional[int]:
    ordered = sorted(t for t in spawn_times if t)
    best = 0
    for i, start in enumerate(ordered):
        count = 1
        for later in ordered[i + 1:]:
            gap = _seconds(start, later)
            if gap is not None and gap <= SPAWN_BURST_WINDOW_SECONDS:
                count += 1
        best = max(best, count)
    return best if best >= SPAWN_BURST_MIN else None


def _combine(strengths: list[float]) -> float:
    remaining = 1.0
    for s in strengths:
        remaining *= 1.0 - s
    return round(1.0 - remaining, 2)


def hypothesis_id(tenant_id: str, root_agent_ref: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}\x00{root_agent_ref}".encode()).hexdigest()[:24]
    return f"{tenant_id}:fleet_hyp:{digest}"


def build_fleet_hypothesis(
    *,
    tenant_id: str,
    root_agent_ref: str,
    member_refs: list[str],
    observations: dict[str, AgentObservation],
    principal_entity_ids: Optional[list[str]] = None,
    risk_flagged_refs: Optional[set[str]] = None,
    source_event_refs: Optional[list[str]] = None,
) -> Optional[dict[str, Any]]:
    """Return an unconfirmed hypothesis, or None when the fleet is too small."""
    members = [m for m in dict.fromkeys(member_refs) if m != root_agent_ref]
    if len(members) + 1 < MIN_FLEET_SIZE:
        return None
    principals = sorted(set(principal_entity_ids or []))
    flagged = sorted((risk_flagged_refs or set()) & ({root_agent_ref} | set(members)))
    evidence: list[dict[str, Any]] = []

    def add(kind: str, detail: dict[str, Any], refs: Optional[list[str]] = None) -> None:
        basis, strength = _EVIDENCE_WEIGHTS[kind]
        evidence.append({
            "type": kind, "basis": basis, "strength": strength,
            "detail": detail, "source_event_refs": (refs or [])[:25],
        })

    add("observed_spawn_tree", {"root": root_agent_ref, "member_count": len(members)},
        source_event_refs)

    spawn_times = [observations[m].spawned_at for m in members if m in observations and observations[m].spawned_at]
    burst = _burst([t for t in spawn_times if t])
    if burst:
        add("spawn_burst", {"agents_in_window": burst, "window_seconds": SPAWN_BURST_WINDOW_SECONDS})

    host_members: dict[str, set[str]] = defaultdict(set)
    for m in members:
        for host in observations.get(m, AgentObservation(m)).endpoint_hosts:
            host_members[host].add(m)
    shared_hosts = {h: sorted(ms) for h, ms in host_members.items() if len(ms) >= max(2, len(members) // 2)}
    if shared_hosts:
        add("shared_endpoint", {"hosts": dict(sorted(shared_hosts.items()))})

    sequences = Counter(
        tuple(observations[m].tool_sequence) for m in members
        if m in observations and observations[m].tool_sequence
    )
    if sequences:
        seq, count = sequences.most_common(1)[0]
        if count >= max(2, len(members) // 2):
            add("identical_tool_sequence", {"sequence": list(seq)[:20], "agents": count})

    target_members: dict[str, set[str]] = defaultdict(set)
    for m in members:
        for target in observations.get(m, AgentObservation(m)).target_refs:
            target_members[target].add(m)
    shared_targets = {t: sorted(ms) for t, ms in target_members.items() if len(ms) >= 2}
    if shared_targets:
        add("overlapping_targets", {
            "target_count": len(shared_targets),
            "targets": dict(sorted(shared_targets.items())[:20]),
        })

    if principals:
        add("canonical_principal_delegation", {"principal_entity_ids": principals})

    strengths = [e["strength"] for e in evidence]
    circumstantial = [e["strength"] for e in evidence if e["type"] in _CIRCUMSTANTIAL or e["type"] == "observed_spawn_tree"]
    if principals:
        confidence = min(_combine(strengths), DELEGATION_CAP)
    else:
        confidence = min(_combine(circumstantial), CIRCUMSTANTIAL_CAP)

    kinds = {e["type"] for e in evidence}
    competing: list[dict[str, str]] = []
    if "shared_endpoint" in kinds:
        competing.append({
            "id": "shared_third_party_infrastructure",
            "note": "Agents may share a hosting provider, sandbox or public tool endpoint without a common operator.",
        })
    if "identical_tool_sequence" in kinds:
        competing.append({
            "id": "same_vendor_template",
            "note": "Independent deployments of one vendor template produce identical tool sequences.",
        })
    if "spawn_burst" in kinds:
        competing.append({
            "id": "legitimate_parallel_workflow",
            "note": "An orchestrator fanning out parallel workers is normal and not itself abusive.",
        })
    if principals:
        competing.append({
            "id": "principal_is_not_the_actor",
            "note": "Delegation shows authority was granted, not intent. The principal may be a victim of a hijacked or over-scoped orchestrator.",
        })
    else:
        competing.append({
            "id": "no_human_principal_observed",
            "note": "No canonical delegation ties this fleet to a person; any person link would be speculation.",
        })

    return {
        "hypothesis_id": hypothesis_id(tenant_id, root_agent_ref),
        "tenant_id": tenant_id,
        "kind": "common_operator",
        "root_agent_ref": root_agent_ref,
        "member_refs": sorted(members),
        "member_count": len(members) + 1,
        "evidence": evidence,
        "confidence": confidence,
        "confidence_cap": DELEGATION_CAP if principals else CIRCUMSTANTIAL_CAP,
        "status": STATUS_NEEDS_REVIEW if confidence >= NEEDS_REVIEW_THRESHOLD else STATUS_UNCONFIRMED,
        "person_link": (
            {
                "principal_entity_ids": principals,
                "basis": "canonical_delegation_principal",
                "evidence_status": "observed",
                "claim": "authority_granted",
            }
            if principals else None
        ),
        "competing_explanations": competing,
        "risk_context": {"flagged_agent_refs": flagged, "risk_flagged": bool(flagged)},
        "priority": "high" if flagged and confidence >= NEEDS_REVIEW_THRESHOLD else "normal",
        "review_history": [],
        "created_at": utc_now().isoformat(),
    }


class ReviewError(ValueError):
    pass


def apply_review(
    hypothesis: dict[str, Any], *, reviewer_id: str, decision: str, reason: str
) -> dict[str, Any]:
    """Record a human decision. The only path to a confirmed/rejected status."""
    if decision not in _REVIEW_STATUSES:
        raise ReviewError("decision must be 'confirm' or 'reject'")
    if not reviewer_id.strip():
        raise ReviewError("reviewer is required")
    if len(reason.strip()) < 10:
        raise ReviewError("a reason of at least 10 characters is required")
    if decision == "confirm" and not hypothesis.get("person_link"):
        raise ReviewError("cannot confirm: no observed principal to link the fleet to")
    updated = dict(hypothesis)
    updated["status"] = _REVIEW_STATUSES[decision]
    updated["review_history"] = [
        *hypothesis.get("review_history", []),
        {
            "reviewer_id": reviewer_id.strip(), "decision": decision,
            "reason": reason.strip()[:1000], "previous_status": hypothesis.get("status"),
            "reviewed_at": utc_now().isoformat(),
        },
    ]
    return updated


class FleetHypothesisRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("fleet_hypotheses")

    async def save(self, hypothesis: dict[str, Any]) -> dict[str, Any]:
        """Upsert by (tenant, root). A reviewed hypothesis keeps its status and history."""
        existing = await self.find_by_id(hypothesis["hypothesis_id"])
        record = dict(hypothesis)
        if existing and existing.get("tenant_id") == hypothesis["tenant_id"]:
            if existing.get("status") in (STATUS_CONFIRMED, STATUS_REJECTED):
                record["status"] = existing["status"]
            record["review_history"] = existing.get("review_history", [])
            record["created_at"] = existing.get("created_at", record["created_at"])
        return await self.insert_tenant_scoped(
            record["hypothesis_id"], record, record["tenant_id"]
        )

    async def get(self, tenant_id: str, hypothesis_id_: str) -> Optional[dict[str, Any]]:
        row = await self.find_by_id(hypothesis_id_)
        return row if row and row.get("tenant_id") == tenant_id else None

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)
