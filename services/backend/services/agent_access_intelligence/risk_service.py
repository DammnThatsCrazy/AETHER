"""Capability risk findings + blast radius (PR 2, Phase C, monoprompt §9.5).

Two read-only derivations over stores that already exist (``capability_catalog``,
``capability_installations``, ``delegations``). Nothing here writes a row, registers an
event type, or creates a table.

**Findings** merge two independent sources into one ordered list:

``scan``
    ``scanning.scan_capabilities`` over the tenant's catalog rows — credentials in a
    server URL, insecure transport, private-network origins, injection-shaped tool names.

``identity``
    Declared-vs-observed artifact drift. For every catalog row the observed digest
    (``identity.artifact_digest_for``) is compared with the tenant's declared digest
    (``declarations.capability_declaration_service.digest_map``) through
    ``identity.identity_state_for``.

    Only ``DRIFTED`` becomes a finding. ``OBSERVED_ONLY`` deliberately does **not**:
    this platform's entire premise is inventorying capabilities nobody declared, so
    "undeclared" is the normal state of a healthy tenant, not a defect. Emitting a
    finding per undeclared capability would bury the real ones on day one and train
    operators to ignore the surface. It is reported as a *count* instead.

**Blast radius** answers "what does this agent reach?" / "who reaches this capability?"
from observed installations, the catalog, and capability authorizations.

The invariant this module exists to protect: **unknown is never reported as zero.**
Every count that could not be computed is ``None`` (serialized as ``null``),
``exposure_known`` is ``False``, ``missing_inputs`` names each absent input, and the
``summary`` states that exposure is unknown. A caller must never be able to read
"0 capabilities exposed" when the truth is "we have no data for this agent" — zero is a
claim about reality, and we are not entitled to make it. The rule is applied strictly:
if *any* required input is missing, *every* count in the response is ``None``, because a
partial total is still a number a reader will treat as complete.

Even a fully-computed answer is bounded by observation: it is "what we have seen this
agent reach", never "everything this agent can reach". The summary says so.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Optional

from shared.common.common import BadRequestError, NotFoundError

from services.agent_access_intelligence.authority import (
    authorization_state,
    capability_authority_service,
    server_ref_for,
)
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.declarations import capability_declaration_service
from services.agent_access_intelligence.identity import (
    IdentityState,
    artifact_digest_for,
    identity_state_for,
)
from services.agent_access_intelligence.scanning import scan_capabilities
from services.agentic_observability.models import RiskLevel

__all__ = [
    "IDENTITY_DRIFT_CODE",
    "CapabilityRiskService",
    "capability_risk_service",
]

# Code for the drift finding this module raises itself. Kept distinct from
# ``scanning.FindingCode`` because it is derived from a *declaration comparison*, not from
# inspecting a capability record, and the two sources must stay separable in ``by_code``.
IDENTITY_DRIFT_CODE = "identity_drift"

# Bounded read windows. Every one of them, when hit, is disclosed to the caller
# (``sampled`` / a ``missing_inputs`` entry) rather than silently truncating an answer.
_CATALOG_SCAN_LIMIT = 1000
_INSTALLATION_SCAN_LIMIT = 1000
_DECLARATION_LIMIT = 1000
# Capability authorizations are read ONCE per request in a single bounded query, then
# matched in memory. Reading them per-capability through the delegation engine was both
# wrong (it inherited `active_for`'s 200-row newest-first window, so an agent's older live
# grants fell out and the split reported 0 authorized) and expensive (~400 sequential
# uncached round-trips on one read-gated GET). Hitting this window reports the split as
# unknown rather than answering from a partial view.
_AUTHORIZATION_SCAN_LIMIT = 2000

_RISK_ORDER = {
    RiskLevel.CRITICAL.value: 0,
    RiskLevel.HIGH.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.LOW.value: 3,
}


def _plain(value: Any) -> Any:
    """Enum → its value; everything else unchanged."""
    return getattr(value, "value", value)


def _server_key(record: dict[str, Any]) -> Optional[str]:
    """The observed server identity of a catalog/installation row, matching
    ``catalog_service._server_key`` so both sides of a join agree."""
    return record.get("server_name") or record.get("server_url")


def _risk_rank(level: Any) -> int:
    return _RISK_ORDER.get(str(_plain(level) or "").strip().lower(), 99)


def _finding_dict(finding: Any) -> dict[str, Any]:
    """Serialize a ``scanning.CapabilityFinding`` for the API.

    ``code`` and ``risk_level`` are carried through **verbatim**: they are the scanning
    module's vocabulary, and re-casing or renaming a peer module's identifiers here would
    make two surfaces disagree about the name of the same finding. Case-insensitivity
    lives in the filter instead.
    """
    data = dict(finding.model_dump(mode="json"))
    data["code"] = _plain(data.get("code"))
    data["risk_level"] = _plain(data.get("risk_level"))
    data.setdefault("source", "scan")
    return data


class CapabilityRiskService:
    """Read-only risk derivations over the capability inventory."""

    # ------------------------------------------------------------------
    # Findings
    # ------------------------------------------------------------------

    async def findings(
        self,
        tenant_id: str,
        *,
        code: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows = await capability_catalog_service.list_capabilities(
            tenant_id, limit=_CATALOG_SCAN_LIMIT
        )
        catalog_truncated = len(rows) >= _CATALOG_SCAN_LIMIT

        # Module-global lookups (not bound at import) so the scanning lane's function is
        # resolved at call time.
        scanned = [_finding_dict(f) for f in (scan_capabilities(rows) or [])]
        drift, identity = await self._identity_findings(tenant_id, rows)

        items = scanned + drift
        if code:
            wanted = code.strip().lower()
            items = [i for i in items if str(i.get("code") or "").lower() == wanted]
        items.sort(
            key=lambda i: (
                _risk_rank(i.get("risk_level")),
                str(i.get("code") or ""),
                str(i.get("capability_id") or ""),
                str(i.get("summary") or ""),
            )
        )

        by_risk = Counter(str(i.get("risk_level") or "unknown") for i in items)
        by_code = Counter(str(i.get("code") or "unknown") for i in items)
        page = items[offset : offset + limit]

        return {
            "items": page,
            "count": len(page),
            "limit": limit,
            "offset": offset,
            "filter": {"code": code},
            # Counts cover every matching finding in the scanned window, not just the
            # returned page: a page-scoped total would understate risk for any tenant with
            # more findings than one page, which is exactly the tenant that needs the
            # number. `counts.scope` states whether that window was the whole inventory.
            "counts": {
                "total": len(items),
                # The scope of `total` depends on whether either bounded read was hit.
                # Claiming "all matching findings" while the catalog window truncated
                # under-reports risk for exactly the tenant with the most of it, and the
                # oldest capabilities can never surface no matter how far the caller pages.
                "scope": (
                    "all_matching_findings"
                    if not (catalog_truncated or identity.get("declarations_truncated"))
                    else "scanned_window_only"
                ),
                "by_risk_level": dict(by_risk),
                "by_code": dict(by_code),
            },
            "identity": identity,
            "coverage": {
                "capabilities_examined": len(rows),
                "scan_limit": _CATALOG_SCAN_LIMIT,
                # A full window may have truncated the catalog; say so rather than
                # presenting a partial scan as a complete one.
                "sampled": catalog_truncated,
                "catalog_truncated": catalog_truncated,
                "declarations_truncated": bool(identity.get("declarations_truncated")),
                "complete": not (
                    catalog_truncated or identity.get("declarations_truncated")
                ),
            },
        }

    async def _identity_findings(
        self, tenant_id: str, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        declared, declarations_truncated = await capability_declaration_service.digest_map(
            tenant_id, limit=_DECLARATION_LIMIT
        )

        states: Counter = Counter()
        items: list[dict[str, Any]] = []
        for row in rows:
            capability_id = row.get("capability_id")
            entry = declared.get(capability_id)
            declared_digest = entry["digest"] if entry else None
            # Digest the observed row over the SAME field subset the declaration asserted.
            # Comparing the full tuple against a partial declaration reported permanent
            # drift for capabilities that never changed — you cannot diverge from an
            # assertion nobody made.
            observed = artifact_digest_for(row, entry["fields"] if entry else None)
            state = identity_state_for(observed, declared_digest)
            states[state.value] += 1
            if state is not IdentityState.DRIFTED:
                # OBSERVED_ONLY is a normal state, not a finding — see module docstring.
                continue
            items.append({
                "code": IDENTITY_DRIFT_CODE,
                # A declaration is the one place the tenant stated an expectation; the
                # observed artifact no longer matching it is a stronger signal than any
                # inference we could draw from an unattributed observation.
                "risk_level": RiskLevel.HIGH.value,
                "summary": (
                    f"Declared identity for capability {capability_id} no longer matches "
                    "what was observed."
                ),
                "evidence": (
                    f"declared_digest={declared_digest or 'none'} observed_digest={observed}"
                ),
                "capability_id": capability_id,
                "source": "identity",
            })

        return items, {
            "capabilities_examined": len(rows),
            "declarations_read": len(declared),
            # `declarations_read` is what we looked at, not what exists. When the window
            # truncated, a declaration outside it makes its capability look
            # `observed_only` — which is deliberately not a finding — so real drift would
            # vanish into a clean-looking report. Say so instead.
            "declarations_truncated": declarations_truncated,
            "declaration_read_limit": _DECLARATION_LIMIT,
            "declared": states.get(IdentityState.DECLARED.value, 0),
            "drifted": states.get(IdentityState.DRIFTED.value, 0),
            # Reported as a count, never as a finding.
            "observed_only": states.get(IdentityState.OBSERVED_ONLY.value, 0),
            "drift_detection_complete": not declarations_truncated,
        }

    # ------------------------------------------------------------------
    # Blast radius
    # ------------------------------------------------------------------

    async def blast_radius(
        self,
        tenant_id: str,
        *,
        agent_id: Optional[str] = None,
        capability_id: Optional[str] = None,
    ) -> dict[str, Any]:
        agent_id = (agent_id or "").strip() or None
        capability_id = (capability_id or "").strip() or None
        if bool(agent_id) == bool(capability_id):
            raise BadRequestError(
                "provide exactly one of agent_id (what this agent reaches) or "
                "capability_id (who reaches this capability)"
            )
        if agent_id:
            return await self._agent_blast_radius(tenant_id, agent_id)
        assert capability_id is not None  # guarded by the exactly-one check above
        return await self._capability_blast_radius(tenant_id, capability_id)

    async def _agent_blast_radius(self, tenant_id: str, agent_id: str) -> dict[str, Any]:
        missing: list[str] = []
        installations = await capability_catalog_service.list_installations(
            tenant_id, agent_id=agent_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if not installations:
            # THE case this surface exists for. An agent we have never observed has an
            # unknown reach, not an empty one.
            return self._unknown(
                subject={"kind": "agent", "id": agent_id},
                count_keys=_AGENT_COUNT_KEYS,
                missing=[f"capability_installations:agent_id={agent_id}"],
                servers=[],
                capabilities=[],
            )
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            missing.append("capability_installations:scan_truncated")

        server_keys: set[str] = set()
        for installation in installations:
            key = _server_key(installation)
            if key:
                server_keys.add(key)
            else:
                missing.append(
                    "capability_server_binding:installation_id="
                    f"{installation.get('installation_id')}"
                )

        catalog = await capability_catalog_service.list_capabilities(
            tenant_id, limit=_CATALOG_SCAN_LIMIT
        )
        if len(catalog) >= _CATALOG_SCAN_LIMIT:
            missing.append("capability_catalog:scan_truncated")
        by_id = {r.get("capability_id"): r for r in catalog}

        exposed: set[str] = {
            r["capability_id"] for r in catalog if _server_key(r) in server_keys
        }
        # Provenance per capability: `invoked` means this agent was actually observed
        # using it; `server_reachable` means it merely sits on a server the agent
        # connects to. Both belong in a blast radius, but conflating them in the response
        # let a summary claim an agent was "observed reaching" 50 tools when it had been
        # observed invoking one.
        invoked: set[str] = set()
        for installation in installations:
            for cid in installation.get("capability_ids") or []:
                exposed.add(cid)
                invoked.add(cid)
                if cid not in by_id:
                    # Recorded as reachable but absent from the catalog window: we cannot
                    # describe it, so the totals it belongs to are not ours to state.
                    missing.append(f"capability_catalog:capability_id={cid}")

        authorized = await self._authorization_split(
            tenant_id,
            agent_id=agent_id,
            capability_ids=sorted(exposed),
            by_id=by_id,
            missing=missing,
        )

        capabilities = [
            {
                "capability_id": cid,
                "server_key": _server_key(by_id.get(cid) or {}),
                "provider": (by_id.get(cid) or {}).get("provider"),
                "tool_name": (by_id.get(cid) or {}).get("tool_name"),
                "latest_risk_level": (by_id.get(cid) or {}).get("latest_risk_level"),
                "basis": "invoked" if cid in invoked else "server_reachable",
                "authorized": None if authorized is None else (cid in authorized),
            }
            for cid in sorted(exposed)
        ]

        if missing:
            return self._unknown(
                subject={"kind": "agent", "id": agent_id},
                count_keys=_AGENT_COUNT_KEYS,
                missing=missing,
                servers=sorted(server_keys),
                capabilities=capabilities,
            )

        assert authorized is not None  # no missing inputs ⇒ the split was computed
        counts = {
            "servers_reachable": len(server_keys),
            "capabilities_exposed": len(exposed),
            "capabilities_invoked": len(invoked),
            "capabilities_authorized": len(authorized),
            "capabilities_unauthorized": len(exposed) - len(authorized),
        }
        return {
            "subject": {"kind": "agent", "id": agent_id},
            "exposure_known": True,
            "missing_inputs": [],
            "basis": "observed_only",
            "counts": counts,
            "servers": sorted(server_keys),
            "capabilities": capabilities,
            "summary": (
                f"Agent {agent_id} has been observed connected to "
                f"{counts['servers_reachable']} server(s), putting "
                f"{counts['capabilities_exposed']} capability(ies) within reach; "
                f"{counts['capabilities_authorized']} authorized, "
                f"{counts['capabilities_unauthorized']} not. Reach is derived from the "
                "servers this agent was observed connected to, so it includes capabilities "
                "on those servers the agent was never observed invoking — that is the point "
                "of a blast radius. It is not a proof of total reach."
            ),
        }

    async def _capability_blast_radius(
        self, tenant_id: str, capability_id: str
    ) -> dict[str, Any]:
        subject = {"kind": "capability", "id": capability_id}
        missing: list[str] = []
        try:
            capability = await capability_catalog_service.get_capability(
                tenant_id, capability_id
            )
        except NotFoundError:
            # Not observed (or another tenant's) — identical answer either way, so the id
            # is not an existence oracle, and the answer is "unknown", not "nothing".
            return self._unknown(
                subject=subject,
                count_keys=_CAPABILITY_COUNT_KEYS,
                missing=[f"capability_catalog:capability_id={capability_id}"],
                servers=[],
                agents=[],
            )

        server_key = _server_key(capability)
        if not server_key:
            missing.append(f"capability_server_binding:capability_id={capability_id}")

        installations = await capability_catalog_service.list_installations(
            tenant_id, limit=_INSTALLATION_SCAN_LIMIT
        )
        if len(installations) >= _INSTALLATION_SCAN_LIMIT:
            missing.append("capability_installations:scan_truncated")

        reaching = [
            i
            for i in installations
            if (server_key and _server_key(i) == server_key)
            or capability_id in (i.get("capability_ids") or [])
        ]
        agent_ids = sorted({i["agent_id"] for i in reaching if i.get("agent_id")})
        if not agent_ids and not missing:
            # An empty result is only unknown when something stopped us from looking. With
            # a complete, untruncated installation scan and a server binding to match on,
            # "nobody reaches this" is a computed answer, and returning `unknown` for it
            # made the surface useless for its most valuable question — "did quarantining
            # this capability work?" was permanently unanswerable.
            #
            # Note the guard is `not missing`, not just the truncation flag: a capability
            # with no server binding (every `provider_action` — `_upsert_installation`
            # only writes a row when both an agent and a server key exist) has already
            # added a missing input above, so it correctly stays unknown rather than
            # claiming a zero it cannot support.
            pass

        authorized = await self._authorization_split_by_agent(
            tenant_id,
            capability_id=capability_id,
            capability=capability,
            agent_ids=agent_ids,
            missing=missing,
        )
        agents = [
            {
                "agent_id": aid,
                "authorized": None if authorized is None else (aid in authorized),
            }
            for aid in agent_ids
        ]

        if missing:
            return self._unknown(
                subject=subject,
                count_keys=_CAPABILITY_COUNT_KEYS,
                missing=missing,
                servers=[server_key] if server_key else [],
                agents=agents,
            )

        assert authorized is not None
        counts = {
            "agents_reaching": len(agent_ids),
            "agents_authorized": len(authorized),
            "agents_unauthorized": len(agent_ids) - len(authorized),
        }
        return {
            "subject": subject,
            "exposure_known": True,
            "missing_inputs": [],
            "basis": "observed_only",
            "counts": counts,
            "servers": [server_key] if server_key else [],
            "agents": agents,
            "summary": (
                f"Capability {capability_id} has been observed reachable by "
                f"{counts['agents_reaching']} agent(s); {counts['agents_authorized']} "
                f"authorized, {counts['agents_unauthorized']} not. This is observed reach, "
                "not a proof of total reach."
            ),
        }

    # ------------------------------------------------------------------
    # Authorization split (returns None when it could not be computed)
    # ------------------------------------------------------------------

    async def _active_authorizations(
        self, tenant_id: str, *, agent_id: Optional[str], missing: list[str]
    ) -> Optional[list[dict[str, Any]]]:
        """Active capability authorizations, read once, or ``None`` if unknowable.

        Replaces a per-capability ``resolve()`` loop, which was wrong twice over:

        * **Correctness.** ``resolve`` → ``DelegationEngine`` → ``active_for`` reads
          ``find_many(limit=200, ORDER BY created_at DESC)`` and *then* filters to active
          rows in Python. Revoked authorizations are never deleted, so grant/revoke churn
          fills that window with dead rows. An agent with 210 lifetime rows whose 3 live
          authorizations were granted earliest fell entirely outside it, and the endpoint
          answered ``capabilities_authorized: 0`` with ``exposure_known: true`` and an
          empty ``missing_inputs`` — "0 authorized, 3 not" about a fully authorized agent.
          That is the never-report-unknown-as-zero rule broken one layer below the
          aggregation, and it points the operator at a revocation that should not happen.
        * **Cost.** Up to 200 capabilities × 2 candidate resources ≈ 400 sequential
          uncached round-trips on a single ``read``-gated GET.

        This reads the capability authorization rows directly, in one bounded query, and
        reports truncation instead of silently answering from a partial window.
        """
        rows = await capability_authority_service._repo.list_authorizations(
            tenant_id, agent_id=agent_id, limit=_AUTHORIZATION_SCAN_LIMIT, offset=0
        )
        if len(rows) >= _AUTHORIZATION_SCAN_LIMIT:
            missing.append("capability_authorizations:scan_truncated")
            return None
        return [r for r in rows if authorization_state(r) == "active"]

    @staticmethod
    def _authorizes(row: dict[str, Any], capability_id: str, server_ref: Optional[str]) -> bool:
        """Whether one authorization row covers one capability.

        Mirrors ``CapabilityAuthorityService.resolve``'s two scope shapes: a row naming the
        capability directly, or a row naming the server the capability lives on.
        """
        if row.get("capability_id") and str(row["capability_id"]) == capability_id:
            return True
        return bool(server_ref) and str(row.get("server_ref") or "") == server_ref

    async def _authorization_split(
        self,
        tenant_id: str,
        *,
        agent_id: str,
        capability_ids: list[str],
        by_id: dict[str, dict[str, Any]],
        missing: list[str],
    ) -> Optional[set[str]]:
        active = await self._active_authorizations(
            tenant_id, agent_id=agent_id, missing=missing
        )
        if active is None:
            return None
        authorized: set[str] = set()
        for cid in capability_ids:
            row = by_id.get(cid) or {}
            key = _server_key(row)
            server_ref = server_ref_for(tenant_id, key) if key else None
            if any(self._authorizes(a, cid, server_ref) for a in active):
                authorized.add(cid)
        return authorized

    async def _authorization_split_by_agent(
        self,
        tenant_id: str,
        *,
        capability_id: str,
        capability: dict[str, Any],
        agent_ids: list[str],
        missing: list[str],
    ) -> Optional[set[str]]:
        active = await self._active_authorizations(
            tenant_id, agent_id=None, missing=missing
        )
        if active is None:
            return None
        key = _server_key(capability)
        server_ref = server_ref_for(tenant_id, key) if key else None
        authorized: set[str] = set()
        for aid in agent_ids:
            rows = [a for a in active if str(a.get("agent_id") or "") == aid]
            if any(self._authorizes(a, capability_id, server_ref) for a in rows):
                authorized.add(aid)
        return authorized

    # ------------------------------------------------------------------
    # The unknown response
    # ------------------------------------------------------------------

    @staticmethod
    def _unknown(
        *,
        subject: dict[str, Any],
        count_keys: tuple[str, ...],
        missing: list[str],
        servers: list[str],
        capabilities: Optional[list[dict[str, Any]]] = None,
        agents: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Every count ``None``; the evidence we do hold kept as a labelled list.

        The lists are evidence, not totals — they are what we happened to observe, and
        the response says nowhere that they are complete. Emitting ``0`` for any of the
        counts here would be an assertion about the world that no input supports.
        """
        deduped: list[str] = []
        for entry in missing:
            if entry not in deduped:
                deduped.append(entry)
        response: dict[str, Any] = {
            "subject": subject,
            "exposure_known": False,
            "missing_inputs": deduped,
            "basis": "observed_only",
            "counts": {key: None for key in count_keys},
            "servers": servers,
            "summary": (
                f"Exposure for {subject['kind']} {subject['id']} is UNKNOWN, not zero. "
                f"Required input(s) absent: {', '.join(deduped)}. Every count is null "
                "because it could not be computed — do not read this as no exposure."
            ),
        }
        if capabilities is not None:
            response["capabilities"] = capabilities
        if agents is not None:
            response["agents"] = agents
        return response


_AGENT_COUNT_KEYS = (
    "servers_reachable",
    "capabilities_exposed",
    "capabilities_invoked",
    "capabilities_authorized",
    "capabilities_unauthorized",
)

_CAPABILITY_COUNT_KEYS = (
    "agents_reaching",
    "agents_authorized",
    "agents_unauthorized",
)


capability_risk_service = CapabilityRiskService()
