"""Per-agent access profiles + access journeys (PR 4, ``AAI-4-PROFILES-JOURNEYS``).

Three read-only derivations over stores that already exist (``capability_catalog``,
``capability_installations``, ``delegations``) plus the access graph. Nothing here writes
a row, registers an event type, or creates a table.

``profile(tenant_id, agent_id)``
    Who this agent is *as we have observed it*: the servers it was seen connected to, the
    capabilities that puts within reach, its authorization posture, the observation
    provenance behind all of it (``first_seen_at`` / ``last_seen_at`` /
    ``observation_count``), and a risk posture rolled up from the catalog rows it touches.

``journey(tenant_id, agent_id)``
    The agent's access journey: an ordered, bounded sequence of first-observation
    milestones.

``list_profiles(tenant_id)``
    A light index of the agents this tenant has observed at least one installation for.

Four things this module refuses to do, each because the alternative is a lie an operator
would act on:

**1. A journey is an OBSERVATION ORDER, not a causal history.**
Every milestone timestamp is a ``first_seen_at`` — the first moment *we recorded*
something, not the first moment it happened. An agent that connected to a server for six
months before this platform was installed has a milestone dated the day we turned on, and
nothing in the data distinguishes that from a genuinely new connection. The response says
so in ``basis``, ``is_causal_history`` and ``summary``, and the ordering is labelled
``first_observation_ascending`` rather than anything resembling "history" or "audit
trail". ``observation_count`` is a bounded-window count (see ``models.py``:
``_MAX_DEDUP_EVENT_IDS``), not an exactly-once counter, and is labelled as such.

The sharpest edge here, and the one most likely to mislead: **capability milestones are
tenant-scoped, not agent-scoped.** A ``capability_catalog`` row is keyed by
``(tenant, provider, server, tool)`` — there is no agent in that identity — so its
``first_seen_at`` is the first time *this tenant* observed the capability, which may
predate this agent's existence entirely. Only ``capability_installations`` rows are keyed
by agent, so only server milestones carry an agent-scoped timestamp. Every milestone
therefore carries an explicit ``observed_scope`` of ``agent`` or ``tenant``, and the
response repeats the caveat at the top level. Presenting a tenant-scoped timestamp as
"when this agent first reached this tool" would be a fabricated fact about a specific
principal, which is the worst kind this package can emit.

**2. Unknown is never zero.** An agent with no observed installations has an UNKNOWN
reach, not an empty one. Every count is ``None`` (serialized ``null``),
``profile_known`` / ``journey_known`` is ``False``, ``missing_inputs`` names each absent
input, and the summary states that the answer is unknown rather than nothing. The rule is
applied strictly, exactly as in ``risk_service``: if *any* required input is missing,
*every* count in that section is ``None``, because a partial total is still a number a
reader will treat as complete.

**3. Every bounded read discloses truncation.** Each scan window that was hit appears in
the response — as a ``missing_inputs`` entry for the sections whose counts it invalidates,
and as ``truncated`` on the journey.

**4. There is no score.** No "risk score", no "trust score", no composite number. The
observed ``latest_risk_level`` values are rolled up as *counts by level* and nothing else.
A composite would need a weighting nobody can derive from these inputs, and a number an
operator cannot trace is worse than the counts it hides.

Two independent honesty scopes, deliberately kept separate:

``missing_inputs`` / ``counts``
    Derived from the catalog, installation and authorization stores directly.

``graph.missing_inputs`` / ``graph.counts``
    Derived from ``access_graph.capability_access_graph_service``.

An unavailable graph must not erase counts we computed from the stores ourselves, and a
graph that answered must not paper over an absent installation row. Collapsing the two
would make one outage silently degrade the other's answer.

Naming note: the ``journey`` vocabulary already exists in this product for the
*customer/user* journey (``frontend/aether/src/features/journey/``: steps, transitions,
touchpoints). This is a different subject — an **agent access journey** — so it is
composed of ``milestones``, not steps, and never claims a transition between them.
"""

from __future__ import annotations

import inspect
from collections import Counter
from typing import Any, Optional

from shared.common.common import BadRequestError
from shared.temporal.instant import to_iso_utc, try_parse_instant

from services.agent_access_intelligence.authority import (
    authorization_state,
    capability_authority_service,
    server_ref_for,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service

# The access graph is built by a peer lane. Imported normally, but guarded: this lane must
# stay independently verifiable, and a profile computed entirely from the catalog and
# installation stores is still a true profile without it. When the module is absent the
# graph section reports itself unavailable via `graph.missing_inputs` rather than either
# crashing the import or silently omitting the section — see the two-honesty-scopes note in
# the module docstring for why that absence does NOT null the store-derived counts.
#
# `neighborhood`'s response is read through `_graph_section` / `_graph_truncated`, which
# tolerate two shapes: the flat `{"truncated": bool, nodes[].id}` this lane was specified
# against, and the `{"truncation": {...}, "complete": bool, "neighborhood_known": bool,
# nodes[].node_id}` the module actually ships. Binding to one would have made a capped
# neighborhood read as complete and the node sample come back empty.
try:  # pragma: no cover - exercised by whichever side of the branch is live
    from services.agent_access_intelligence.access_graph import (  # type: ignore[import-not-found]
        capability_access_graph_service,
    )
except ImportError:  # pragma: no cover - the lane has not landed yet
    capability_access_graph_service = None  # type: ignore[assignment]

__all__ = [
    "AgentAccessProfileService",
    "capability_profile_service",
]

# Bounded read windows. Every one of them, when hit, is disclosed to the caller rather
# than silently truncating an answer.
_INSTALLATION_SCAN_LIMIT = 1000
_CATALOG_SCAN_LIMIT = 1000
# Capability authorizations are read ONCE per request in a single bounded query and then
# matched in memory, for the reason `risk_service._active_authorizations` documents at
# length: routing this through `DelegationEngine.active_for` inherits a 200-row
# newest-first window that revoked rows fill up, so an agent's older live grants fall out
# and the split reports "0 authorized" about a fully authorized agent.
_AUTHORIZATION_SCAN_LIMIT = 2000
# Window scanned to build the agent index. Distinct agents are derived from installation
# rows, so this bounds agents indirectly; truncation is disclosed.
_PROFILE_INDEX_SCAN_LIMIT = 2000

# Bounded neighborhood requested from the access graph.
_GRAPH_DEPTH = 1
_GRAPH_LIMIT = 500
# Bounded sample of graph node ids echoed back as evidence.
_GRAPH_NODE_SAMPLE = 200

_JOURNEY_MAX_LIMIT = 500

_PROFILE_COUNT_KEYS = (
    "servers_observed",
    "capabilities_reachable",
    "capabilities_invoked",
    "capabilities_authorized",
    "capabilities_unauthorized",
    "authorizations_active",
    "observations_recorded",
)

_JOURNEY_COUNT_KEYS = (
    "milestones_total",
    "milestones_returned",
    "server_milestones",
    "capability_milestones",
    "milestones_undated",
)

_GRAPH_COUNT_KEYS = ("nodes", "edges")

# Stated on every response that rolls up risk, so the absence of a composite number is a
# documented decision rather than something a later reader "fixes".
_NO_SCORE_NOTE = (
    "Counts of the latest observed risk level on each capability this agent reaches. "
    "There is deliberately no composite risk or trust score: no formula over these "
    "inputs is derivable or explainable, and a number an operator cannot trace is worse "
    "than the counts it would hide."
)

_OBSERVATION_COUNT_NOTE = (
    "observations_recorded sums observation_count across this agent's installation rows. "
    "observation_count is deduplicated over a BOUNDED recent window of source events, so "
    "it is a bounded-window observation count, not an exactly-once total."
)

_JOURNEY_SCOPE_NOTE = (
    "Server milestones are agent-scoped (a capability_installations row is keyed by "
    "tenant+agent+server). Capability milestones are TENANT-scoped: a capability_catalog "
    "row is keyed by tenant+provider+server+tool with no agent in its identity, so its "
    "first_seen_at is the first time this tenant observed the capability and may predate "
    "this agent entirely. Read each milestone's observed_scope before attributing it."
)


def _server_key(record: dict[str, Any]) -> Optional[str]:
    """The observed server identity of a catalog/installation row, matching
    ``catalog_service._server_key`` so both sides of a join agree."""
    return record.get("server_name") or record.get("server_url")


def _risk_bucket(level: Any) -> str:
    """The rollup bucket for a catalog row's ``latest_risk_level``.

    A row with no observed level is counted under ``unknown`` — a real count of
    capabilities whose risk we do not know — never folded into ``low``."""
    text = str(getattr(level, "value", level) or "").strip().lower()
    return text or "unknown"


class AgentAccessProfileService:
    """Read-only per-agent profiles and access journeys over the agent-access graph."""

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    async def profile(self, tenant_id: str, agent_id: str) -> dict[str, Any]:
        """What we have observed about one agent's access, or an explicit unknown.

        Tenant scoping is fail-closed and identical to absence: another tenant's agent and
        an agent that does not exist produce the same unknown shape, so ``agent_id`` is
        never an existence oracle.
        """
        agent_id = (agent_id or "").strip()
        if not agent_id:
            raise BadRequestError("agent_id is required")

        installations = await capability_catalog_service.list_installations(
            tenant_id, agent_id=agent_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if not installations:
            # THE case this surface exists for. An agent we have never observed has an
            # unknown profile, not an empty one. The graph is deliberately NOT queried:
            # there is no observed subject to build a neighborhood around, and querying it
            # anyway would invite a zero-node answer to be read as "reaches nothing".
            return self._unknown_profile(
                agent_id,
                missing=[f"capability_installations:agent_id={agent_id}"],
                graph_missing=["capability_access_graph:not_queried_subject_unobserved"],
            )

        missing: list[str] = []
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            missing.append("capability_installations:scan_truncated")

        server_keys: set[str] = set()
        providers: set[str] = set()
        first_seen: Optional[str] = None
        last_seen: Optional[str] = None
        observations = 0
        for installation in installations:
            key = _server_key(installation)
            if key:
                server_keys.add(key)
            else:
                missing.append(
                    "capability_server_binding:installation_id="
                    f"{installation.get('installation_id')}"
                )
            if installation.get("provider"):
                providers.add(str(installation["provider"]))

            seen_first = installation.get("first_seen_at")
            seen_last = installation.get("last_seen_at")
            if not seen_first:
                missing.append(
                    "capability_installations:first_seen_at:installation_id="
                    f"{installation.get('installation_id')}"
                )
            else:
                first_seen = seen_first if first_seen is None else min(first_seen, seen_first)
            if not seen_last:
                missing.append(
                    "capability_installations:last_seen_at:installation_id="
                    f"{installation.get('installation_id')}"
                )
            else:
                last_seen = seen_last if last_seen is None else max(last_seen, seen_last)

            count = installation.get("observation_count")
            if count is None:
                missing.append(
                    "capability_installations:observation_count:installation_id="
                    f"{installation.get('installation_id')}"
                )
            else:
                observations += int(count)

        catalog = await capability_catalog_service.list_capabilities(
            tenant_id, limit=_CATALOG_SCAN_LIMIT
        )
        if len(catalog) >= _CATALOG_SCAN_LIMIT:
            missing.append("capability_catalog:scan_truncated")
        by_id = {r.get("capability_id"): r for r in catalog}

        reachable, invoked = self._reach(installations, catalog, server_keys, missing, by_id)

        authorized, active_authorizations = await self._authorization_split(
            tenant_id, agent_id=agent_id, capability_ids=sorted(reachable),
            by_id=by_id, missing=missing,
        )

        graph = await self._graph_section(
            tenant_id, agent_id=agent_id, subject_observed=True
        )

        capabilities = [
            {
                "capability_id": cid,
                "server_key": _server_key(by_id.get(cid) or {}),
                "provider": (by_id.get(cid) or {}).get("provider"),
                "tool_name": (by_id.get(cid) or {}).get("tool_name"),
                "capability_kind": (by_id.get(cid) or {}).get("capability_kind"),
                "latest_risk_level": (by_id.get(cid) or {}).get("latest_risk_level"),
                # `invoked` = this agent was observed using it; `server_reachable` = it
                # merely sits on a server the agent connects to. Conflating them lets a
                # summary claim an agent was "observed reaching" 50 tools when it was
                # observed invoking one.
                "basis": "invoked" if cid in invoked else "server_reachable",
                "authorized": None if authorized is None else (cid in authorized),
            }
            for cid in sorted(reachable)
        ]

        by_level = Counter(
            _risk_bucket((by_id.get(cid) or {}).get("latest_risk_level")) for cid in reachable
        )

        identity = {
            "agent_id": agent_id,
            "providers_observed": sorted(providers),
            "servers_observed": sorted(server_keys),
            "installation_ids": sorted(
                str(i["installation_id"]) for i in installations if i.get("installation_id")
            ),
        }

        if missing:
            return self._unknown_profile(
                agent_id,
                missing=missing,
                graph_missing=None,
                identity=identity,
                capabilities=capabilities,
                graph=graph,
                observation={
                    "first_seen_at": first_seen,
                    "last_seen_at": last_seen,
                    # A partial sum over a truncated or incomplete read is still a number
                    # a reader treats as complete. It is not ours to state.
                    "observations_recorded": None,
                    "basis": _OBSERVATION_COUNT_NOTE,
                },
            )

        assert authorized is not None  # no missing inputs ⇒ the split was computed
        counts = {
            "servers_observed": len(server_keys),
            "capabilities_reachable": len(reachable),
            "capabilities_invoked": len(invoked),
            "capabilities_authorized": len(authorized),
            "capabilities_unauthorized": len(reachable) - len(authorized),
            "authorizations_active": len(active_authorizations or []),
            "observations_recorded": observations,
        }
        return {
            "subject": {"kind": "agent", "id": agent_id},
            "profile_known": True,
            "missing_inputs": [],
            "basis": "observed_only",
            "identity": identity,
            "observation": {
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "observations_recorded": observations,
                "basis": _OBSERVATION_COUNT_NOTE,
            },
            "counts": counts,
            "reach": {
                "servers": sorted(server_keys),
                "capabilities": capabilities,
            },
            "authorization": {
                "known": True,
                "authorizations_active": counts["authorizations_active"],
                "capabilities_authorized": counts["capabilities_authorized"],
                "capabilities_unauthorized": counts["capabilities_unauthorized"],
                "scan_limit": _AUTHORIZATION_SCAN_LIMIT,
            },
            "risk": {
                "known": True,
                "by_latest_risk_level": dict(by_level),
                "note": _NO_SCORE_NOTE,
            },
            "graph": graph,
            "summary": (
                f"Agent {agent_id} has been observed connected to "
                f"{counts['servers_observed']} server(s), putting "
                f"{counts['capabilities_reachable']} capability(ies) within reach "
                f"({counts['capabilities_invoked']} of them observed invoked); "
                f"{counts['capabilities_authorized']} authorized, "
                f"{counts['capabilities_unauthorized']} not. This is observed reach over "
                "the servers this agent was seen connected to, not a proof of total reach, "
                "and risk is reported as counts by observed level with no composite score."
            ),
        }

    @staticmethod
    def _reach(
        installations: list[dict[str, Any]],
        catalog: list[dict[str, Any]],
        server_keys: set[str],
        missing: list[str],
        by_id: dict[Any, dict[str, Any]],
    ) -> tuple[set[str], set[str]]:
        """(reachable, invoked) capability ids for one agent.

        Reachable = every catalog row on a server this agent was observed connected to,
        plus every capability recorded directly on its installations. Invoked = only the
        latter."""
        reachable: set[str] = {
            r["capability_id"] for r in catalog if _server_key(r) in server_keys
        }
        invoked: set[str] = set()
        for installation in installations:
            for cid in installation.get("capability_ids") or []:
                reachable.add(cid)
                invoked.add(cid)
                if cid not in by_id:
                    # Recorded as reachable but absent from the catalog window: we cannot
                    # describe it, so the totals it belongs to are not ours to state.
                    missing.append(f"capability_catalog:capability_id={cid}")
        return reachable, invoked

    # ------------------------------------------------------------------
    # Journey
    # ------------------------------------------------------------------

    async def journey(
        self, tenant_id: str, agent_id: str, *, limit: int = 200
    ) -> dict[str, Any]:
        """This agent's access journey: bounded, ordered first-observation milestones.

        **This is an observation order, not a causal history.** Each milestone is dated by
        a ``first_seen_at`` — the first time this platform *recorded* something, not the
        first time it happened — so an access that predates ingestion is dated the day
        ingestion started, and nothing in the data distinguishes the two. It is not an
        audit trail and must not be presented as one.

        Server milestones are agent-scoped; capability milestones are **tenant-scoped**
        (a ``capability_catalog`` row has no agent in its identity), so a capability's
        first observation may predate this agent. Each milestone carries an
        ``observed_scope`` saying which it is.

        Ordering parses each timestamp through the platform's canonical instant authority
        rather than comparing ISO strings: mixed offsets sort correctly by meaning instead
        of by punctuation, and an unparseable or timezone-naive value is moved to
        ``undated`` and named in ``missing_inputs`` instead of being silently misplaced in
        a sequence whose whole value is its order.
        """
        agent_id = (agent_id or "").strip()
        if not agent_id:
            raise BadRequestError("agent_id is required")
        limit = max(1, min(int(limit or 1), _JOURNEY_MAX_LIMIT))

        installations = await capability_catalog_service.list_installations(
            tenant_id, agent_id=agent_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if not installations:
            return self._unknown_journey(
                agent_id,
                limit=limit,
                missing=[f"capability_installations:agent_id={agent_id}"],
            )

        missing: list[str] = []
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            missing.append("capability_installations:scan_truncated")

        dated: list[tuple[Any, str, str, dict[str, Any]]] = []
        undated: list[dict[str, Any]] = []

        def _add(milestone: dict[str, Any], raw: Optional[str]) -> None:
            parsed, reason = try_parse_instant(raw) if raw else (None, "timestamp_missing")
            if parsed is None:
                undated.append({**milestone, "at": None, "at_observed": raw, "undated_reason": reason})
                missing.append(
                    f"first_seen_at:{milestone['kind']}:{milestone['ref']}:{reason}"
                )
                return
            entry = {**milestone, "at": to_iso_utc(parsed), "at_observed": raw}
            dated.append((parsed, milestone["kind"], milestone["ref"], entry))

        server_keys: set[str] = set()
        for installation in installations:
            key = _server_key(installation)
            if key:
                server_keys.add(key)
            ref = str(installation.get("installation_id") or key or "")
            _add(
                {
                    "kind": "server_first_observed",
                    "ref": ref,
                    # Agent-scoped: this row's identity is (tenant, agent, server).
                    "observed_scope": "agent",
                    "server_key": key,
                    "provider": installation.get("provider"),
                    "installation_id": installation.get("installation_id"),
                    "last_seen_at": installation.get("last_seen_at"),
                    "observation_count": installation.get("observation_count"),
                    "label": f"First observed connected to server {key or 'unknown'}",
                },
                installation.get("first_seen_at"),
            )

        catalog = await capability_catalog_service.list_capabilities(
            tenant_id, limit=_CATALOG_SCAN_LIMIT
        )
        if len(catalog) >= _CATALOG_SCAN_LIMIT:
            missing.append("capability_catalog:scan_truncated")
        by_id = {r.get("capability_id"): r for r in catalog}
        reachable, invoked = self._reach(installations, catalog, server_keys, missing, by_id)

        for cid in sorted(reachable):
            row = by_id.get(cid)
            if row is None:
                # Named by an installation but outside the catalog window — already in
                # `missing_inputs` via `_reach`; we cannot date what we cannot read.
                continue
            _add(
                {
                    "kind": "capability_first_observed",
                    "ref": cid,
                    # TENANT-scoped: the catalog row's identity carries no agent, so this
                    # timestamp is not evidence about when THIS agent reached it.
                    "observed_scope": "tenant",
                    "capability_id": cid,
                    "server_key": _server_key(row),
                    "provider": row.get("provider"),
                    "tool_name": row.get("tool_name"),
                    "capability_kind": row.get("capability_kind"),
                    "latest_risk_level": row.get("latest_risk_level"),
                    "basis": "invoked" if cid in invoked else "server_reachable",
                    "last_seen_at": row.get("last_seen_at"),
                    "observation_count": row.get("observation_count"),
                    "label": (
                        f"Capability {row.get('tool_name') or cid} first observed in this "
                        "tenant's inventory"
                    ),
                },
                row.get("first_seen_at"),
            )

        dated.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        ordered = [entry[3] for entry in dated]
        for index, milestone in enumerate(ordered):
            # 1-based: `sequence: 0` would be a zero in a response whose whole contract is
            # that a zero means something.
            milestone["sequence"] = index + 1

        page = ordered[:limit]
        truncated = len(ordered) > limit
        if truncated:
            missing_note = f"journey:limit_reached:{limit}"
            if missing_note not in missing:
                missing.append(missing_note)

        counts = {
            "milestones_total": len(ordered) + len(undated),
            "milestones_returned": len(page),
            "server_milestones": sum(
                1 for m in ordered + undated if m["kind"] == "server_first_observed"
            ),
            "capability_milestones": sum(
                1 for m in ordered + undated if m["kind"] == "capability_first_observed"
            ),
            "milestones_undated": len(undated),
        }

        return {
            "subject": {"kind": "agent", "id": agent_id},
            "journey_known": True,
            # Truncation and undated milestones are disclosed, but they do not make the
            # returned order wrong — unlike the profile's counts, an ordered page is still
            # true about what it contains. So `missing_inputs` here is a disclosure list,
            # and `ordering_complete` says whether every milestone made it into the order.
            "missing_inputs": missing,
            "basis": "observation_order",
            "ordering": "first_observation_ascending",
            "ordering_complete": not undated,
            "is_causal_history": False,
            "limit": limit,
            "truncated": truncated,
            "counts": counts,
            "milestones": page,
            "undated": undated,
            "scope_note": _JOURNEY_SCOPE_NOTE,
            "summary": (
                f"Access journey for agent {agent_id}: {counts['milestones_returned']} of "
                f"{counts['milestones_total']} first-observation milestone(s), ordered by "
                "when we FIRST OBSERVED each one. This is an OBSERVATION ORDER, not a "
                "causal history and not an audit trail — it records when this platform "
                "first saw something, never when it first happened, and anything that "
                "predates ingestion is dated the day ingestion began. "
                + _JOURNEY_SCOPE_NOTE
                + (
                    f" The {limit}-milestone page limit was reached; "
                    "later milestones are not shown."
                    if truncated
                    else ""
                )
            ),
        }

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------

    async def list_profiles(
        self, tenant_id: str, *, limit: int = 100, offset: int = 0
    ) -> dict[str, Any]:
        """A light index of agents this tenant has observed at least one installation for.

        Deliberately *not* a page of full profiles: computing reach, authorization and risk
        per agent would fan a single read-gated GET out into hundreds of store round-trips.
        Callers fetch the profile for the agents they care about.

        Absence from this list is not evidence of no access. It means we have observed no
        installation for that agent, which includes every agent that exists and has never
        been seen. ``note`` says so on every response.
        """
        limit = max(1, int(limit or 1))
        offset = max(0, int(offset or 0))

        installations = await capability_catalog_service.list_installations(
            tenant_id, limit=_PROFILE_INDEX_SCAN_LIMIT
        )
        truncated = len(installations) >= _PROFILE_INDEX_SCAN_LIMIT

        agents: dict[str, dict[str, Any]] = {}
        for installation in installations:
            agent_id = installation.get("agent_id")
            if not agent_id:
                continue
            entry = agents.setdefault(
                str(agent_id),
                {
                    "agent_id": str(agent_id),
                    "servers_observed": set(),
                    "providers_observed": set(),
                    "capability_ids_on_installations": set(),
                    "first_seen_at": None,
                    "last_seen_at": None,
                    "observations_recorded": 0,
                    "observations_complete": True,
                },
            )
            key = _server_key(installation)
            if key:
                entry["servers_observed"].add(key)
            if installation.get("provider"):
                entry["providers_observed"].add(str(installation["provider"]))
            entry["capability_ids_on_installations"].update(
                installation.get("capability_ids") or []
            )
            seen_first = installation.get("first_seen_at")
            if seen_first:
                entry["first_seen_at"] = (
                    seen_first
                    if entry["first_seen_at"] is None
                    else min(entry["first_seen_at"], seen_first)
                )
            seen_last = installation.get("last_seen_at")
            if seen_last:
                entry["last_seen_at"] = (
                    seen_last
                    if entry["last_seen_at"] is None
                    else max(entry["last_seen_at"], seen_last)
                )
            count = installation.get("observation_count")
            if count is None:
                entry["observations_complete"] = False
            else:
                entry["observations_recorded"] += int(count)

        items = [
            {
                "agent_id": entry["agent_id"],
                "servers_observed": len(entry["servers_observed"]),
                "servers": sorted(entry["servers_observed"]),
                "providers_observed": sorted(entry["providers_observed"]),
                "capabilities_on_installations": len(entry["capability_ids_on_installations"]),
                "first_seen_at": entry["first_seen_at"],
                "last_seen_at": entry["last_seen_at"],
                # A sum missing one row's contribution is not the sum. Null, not partial.
                "observations_recorded": (
                    entry["observations_recorded"] if entry["observations_complete"] else None
                ),
            }
            for entry in (agents[key] for key in sorted(agents))
        ]
        page = items[offset : offset + limit]

        return {
            "items": page,
            "count": len(page),
            "limit": limit,
            "offset": offset,
            "basis": "observed_only",
            "counts": {
                "agents_observed": len(items),
                # Whether `agents_observed` covers the tenant or only the scanned window.
                "scope": "all_observed_agents" if not truncated else "scanned_window_only",
            },
            "scan_limit": _PROFILE_INDEX_SCAN_LIMIT,
            "truncated": truncated,
            "complete": not truncated,
            "note": (
                "Agents with at least one OBSERVED installation. An agent absent from this "
                "list is not known to have no access — it is an agent we have not observed. "
                "Reach, authorization and risk are not computed here; read the per-agent "
                "profile for those."
            ),
        }

    # ------------------------------------------------------------------
    # Authorization split (returns (None, None) when it could not be computed)
    # ------------------------------------------------------------------

    async def _authorization_split(
        self,
        tenant_id: str,
        *,
        agent_id: str,
        capability_ids: list[str],
        by_id: dict[Any, dict[str, Any]],
        missing: list[str],
    ) -> tuple[Optional[set[str]], Optional[list[dict[str, Any]]]]:
        rows = await capability_authority_service._repo.list_authorizations(
            tenant_id, agent_id=agent_id, limit=_AUTHORIZATION_SCAN_LIMIT, offset=0
        )
        if len(rows) >= _AUTHORIZATION_SCAN_LIMIT:
            missing.append("capability_authorizations:scan_truncated")
            return None, None
        active = [r for r in rows if authorization_state(r) == "active"]

        authorized: set[str] = set()
        for cid in capability_ids:
            row = by_id.get(cid) or {}
            key = _server_key(row)
            server_ref = server_ref_for(tenant_id, key) if key else None
            if any(self._authorizes(a, cid, server_ref) for a in active):
                authorized.add(cid)
        return authorized, active

    @staticmethod
    def _authorizes(
        row: dict[str, Any], capability_id: str, server_ref: Optional[str]
    ) -> bool:
        """Whether one authorization row covers one capability.

        Mirrors the two scope shapes ``CapabilityAuthorityService.resolve`` writes: a row
        naming the capability directly, or a row naming the server it lives on."""
        if row.get("capability_id") and str(row["capability_id"]) == capability_id:
            return True
        return bool(server_ref) and str(row.get("server_ref") or "") == server_ref

    # ------------------------------------------------------------------
    # Access graph
    # ------------------------------------------------------------------

    @staticmethod
    def _graph() -> Any:
        """The access-graph lane's service, or ``None``.

        Re-resolved when the module global is unset so a lane that lands after this module
        was first imported is picked up. Tests monkeypatch the module global directly."""
        global capability_access_graph_service
        if capability_access_graph_service is None:  # pragma: no cover - lane-dependent
            try:
                from services.agent_access_intelligence.access_graph import (  # type: ignore[import-not-found]
                    capability_access_graph_service as service,
                )
            except ImportError:
                return None
            capability_access_graph_service = service
        return capability_access_graph_service

    async def _graph_section(
        self, tenant_id: str, *, agent_id: str, subject_observed: bool
    ) -> dict[str, Any]:
        """Bounded neighborhood around this agent, or an explicit unknown.

        Kept in its own honesty scope: an unavailable or truncated graph nulls
        ``graph.counts`` and nothing else, because the profile's own counts are computed
        from the catalog and installation stores without it.
        """
        if not subject_observed:
            return self._unknown_graph(
                ["capability_access_graph:not_queried_subject_unobserved"]
            )
        service = self._graph()
        if service is None:
            return self._unknown_graph(["capability_access_graph:service_unavailable"])

        try:
            result = service.neighborhood(
                tenant_id,
                agent_id=agent_id,
                depth=_GRAPH_DEPTH,
                limit=_GRAPH_LIMIT,
            )
            # The contract does not state whether `neighborhood` is a coroutine and every
            # peer service in this package is async, so both are accepted rather than
            # guessing and being silently wrong for one of them.
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # pragma: no cover - defensive across a lane boundary
            return self._unknown_graph([f"capability_access_graph:error:{type(exc).__name__}"])
        if not isinstance(result, dict):
            return self._unknown_graph(["capability_access_graph:unexpected_response"])

        graph_missing = [str(m) for m in (result.get("missing_inputs") or [])]
        if self._graph_truncated(result):
            graph_missing.append("capability_access_graph:truncated")
        if result.get("neighborhood_known") is False:
            # The graph states its own knownness. Trust it over any inference of ours: it
            # can withhold counts for reasons that never reach `missing_inputs`.
            graph_missing.append("capability_access_graph:neighborhood_unknown")

        raw_counts = result.get("counts")
        raw_counts = raw_counts if isinstance(raw_counts, dict) else {}
        nodes = result.get("nodes") or []
        edges = result.get("edges") or []
        node_ids = sorted(
            str(n.get("node_id") or n.get("id"))
            for n in nodes
            if isinstance(n, dict) and (n.get("node_id") or n.get("id"))
        )

        if graph_missing:
            return self._unknown_graph(graph_missing, node_ids=node_ids[:_GRAPH_NODE_SAMPLE])

        # Counts come from the graph's own `counts` when it supplied them. The length of
        # the returned page is NOT a substitute: the contract says a count it could not
        # compute is null, and replacing it with a page length would turn "unknown" into a
        # confident number that happens to equal the page size.
        counts: dict[str, Any] = {
            "nodes": raw_counts.get("nodes") if "nodes" in raw_counts else len(nodes),
            "edges": raw_counts.get("edges") if "edges" in raw_counts else len(edges),
        }
        if any(value is None for value in counts.values()):
            return self._unknown_graph(
                ["capability_access_graph:counts_unavailable"],
                node_ids=node_ids[:_GRAPH_NODE_SAMPLE],
            )

        return {
            "neighborhood_known": True,
            "missing_inputs": [],
            "depth": _GRAPH_DEPTH,
            "limit": _GRAPH_LIMIT,
            "truncated": False,
            "counts": counts,
            "node_ids": node_ids[:_GRAPH_NODE_SAMPLE],
            "node_ids_sampled": len(node_ids) > _GRAPH_NODE_SAMPLE,
        }

    @staticmethod
    def _graph_truncated(result: dict[str, Any]) -> bool:
        """Whether the graph's answer was shaped by a cap, across both response shapes.

        The lane contract this module was written against specified a flat
        ``truncated: bool``. The module that shipped reports a ``truncation`` mapping
        (``node_limit_reached`` / ``edge_limit_reached`` / ``depth_capped`` /
        ``*_truncated``) alongside a ``complete`` flag instead. Reading only the flat key
        would have silently reported every capped neighborhood as complete — the exact
        failure this package's truncation-disclosure rule exists to prevent — so both are
        honored, and a shape we do not recognize is treated as truncated rather than
        assumed whole.
        """
        if bool(result.get("truncated")):
            return True
        truncation = result.get("truncation")
        if isinstance(truncation, dict) and any(bool(v) for v in truncation.values()):
            return True
        return result.get("complete") is False

    # ------------------------------------------------------------------
    # The unknown responses
    # ------------------------------------------------------------------

    @staticmethod
    def _dedupe(entries: list[str]) -> list[str]:
        out: list[str] = []
        for entry in entries:
            if entry not in out:
                out.append(entry)
        return out

    @classmethod
    def _unknown_graph(
        cls, missing: list[str], *, node_ids: Optional[list[str]] = None
    ) -> dict[str, Any]:
        return {
            "neighborhood_known": False,
            "missing_inputs": cls._dedupe(missing),
            "depth": _GRAPH_DEPTH,
            "limit": _GRAPH_LIMIT,
            "truncated": None,
            "counts": {key: None for key in _GRAPH_COUNT_KEYS},
            "node_ids": node_ids or [],
            "node_ids_sampled": None,
        }

    @classmethod
    def _unknown_profile(
        cls,
        agent_id: str,
        *,
        missing: list[str],
        graph_missing: Optional[list[str]] = None,
        identity: Optional[dict[str, Any]] = None,
        capabilities: Optional[list[dict[str, Any]]] = None,
        graph: Optional[dict[str, Any]] = None,
        observation: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Every count ``None``; the evidence we do hold kept as a labelled list.

        The lists are evidence, not totals — nothing in the response claims they are
        complete. Emitting ``0`` for any count here would be an assertion about the world
        that no input supports, and "this agent reaches 0 capabilities" is precisely the
        sentence an operator would act on.
        """
        deduped = cls._dedupe(missing)
        return {
            "subject": {"kind": "agent", "id": agent_id},
            "profile_known": False,
            "missing_inputs": deduped,
            "basis": "observed_only",
            "identity": identity or {
                "agent_id": agent_id,
                "providers_observed": [],
                "servers_observed": [],
                "installation_ids": [],
            },
            "observation": observation or {
                "first_seen_at": None,
                "last_seen_at": None,
                "observations_recorded": None,
                "basis": _OBSERVATION_COUNT_NOTE,
            },
            "counts": {key: None for key in _PROFILE_COUNT_KEYS},
            "reach": {
                "servers": list((identity or {}).get("servers_observed") or []),
                "capabilities": capabilities or [],
            },
            "authorization": {
                "known": False,
                "authorizations_active": None,
                "capabilities_authorized": None,
                "capabilities_unauthorized": None,
                "scan_limit": _AUTHORIZATION_SCAN_LIMIT,
            },
            "risk": {
                "known": False,
                # Not `{"unknown": 0}` — an empty rollup, because we rolled up nothing.
                "by_latest_risk_level": {},
                "note": _NO_SCORE_NOTE,
            },
            "graph": graph or cls._unknown_graph(
                graph_missing or ["capability_access_graph:not_queried_subject_unobserved"]
            ),
            "summary": (
                f"The access profile for agent {agent_id} is UNKNOWN, not empty. Required "
                f"input(s) absent: {', '.join(deduped)}. Every count is null because it "
                "could not be computed — do not read this as an agent with no access. An "
                "agent id we have never observed is indistinguishable from another "
                "tenant's, by design."
            ),
        }

    @classmethod
    def _unknown_journey(
        cls, agent_id: str, *, limit: int, missing: list[str]
    ) -> dict[str, Any]:
        deduped = cls._dedupe(missing)
        return {
            "subject": {"kind": "agent", "id": agent_id},
            "journey_known": False,
            "missing_inputs": deduped,
            "basis": "observation_order",
            "ordering": "first_observation_ascending",
            "ordering_complete": False,
            "is_causal_history": False,
            "limit": limit,
            "truncated": False,
            "counts": {key: None for key in _JOURNEY_COUNT_KEYS},
            "milestones": [],
            "undated": [],
            "scope_note": _JOURNEY_SCOPE_NOTE,
            "summary": (
                f"The access journey for agent {agent_id} is UNKNOWN, not empty. Required "
                f"input(s) absent: {', '.join(deduped)}. Every count is null because it "
                "could not be computed — do not read this as an agent that has done "
                "nothing. Even when it can be computed, a journey is an OBSERVATION "
                "ORDER, not a causal history: it records when this platform first saw "
                "something, never when it first happened."
            ),
        }


capability_profile_service = AgentAccessProfileService()
