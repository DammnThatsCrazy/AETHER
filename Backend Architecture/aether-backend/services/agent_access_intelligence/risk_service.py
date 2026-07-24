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

from services.agent_access_intelligence.authority import capability_authority_service
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
# Each authorization check is a delegation-engine evaluation; past this many pairs we
# report the authorization split as unknown instead of spending unbounded work or
# guessing.
_AUTHORIZATION_CHECK_LIMIT = 200

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
            # Counts cover EVERY matching finding, not just the returned page: a
            # page-scoped total would understate risk for any tenant with more findings
            # than one page, which is exactly the tenant that needs the number.
            "counts": {
                "total": len(items),
                "scope": "all_matching_findings",
                "by_risk_level": dict(by_risk),
                "by_code": dict(by_code),
            },
            "identity": identity,
            "coverage": {
                "capabilities_examined": len(rows),
                "scan_limit": _CATALOG_SCAN_LIMIT,
                # A full window may have truncated the catalog; say so rather than
                # presenting a partial scan as a complete one.
                "sampled": len(rows) >= _CATALOG_SCAN_LIMIT,
            },
        }

    async def _identity_findings(
        self, tenant_id: str, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        declared = await capability_declaration_service.digest_map(
            tenant_id, limit=_DECLARATION_LIMIT
        ) or {}

        states: Counter = Counter()
        items: list[dict[str, Any]] = []
        for row in rows:
            capability_id = row.get("capability_id")
            observed = artifact_digest_for(row)
            declared_digest = declared.get(capability_id)
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
            "declarations_on_file": len(declared),
            "declared": states.get(IdentityState.DECLARED.value, 0),
            "drifted": states.get(IdentityState.DRIFTED.value, 0),
            # Reported as a count, never as a finding.
            "observed_only": states.get(IdentityState.OBSERVED_ONLY.value, 0),
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
        for installation in installations:
            for cid in installation.get("capability_ids") or []:
                exposed.add(cid)
                if cid not in by_id:
                    # Recorded as reachable but absent from the catalog window: we cannot
                    # describe it, so the totals it belongs to are not ours to state.
                    missing.append(f"capability_catalog:capability_id={cid}")

        authorized = await self._authorization_split(
            tenant_id, agent_id=agent_id, capability_ids=sorted(exposed), missing=missing
        )

        capabilities = [
            {
                "capability_id": cid,
                "server_key": _server_key(by_id.get(cid) or {}),
                "provider": (by_id.get(cid) or {}).get("provider"),
                "tool_name": (by_id.get(cid) or {}).get("tool_name"),
                "latest_risk_level": (by_id.get(cid) or {}).get("latest_risk_level"),
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
                f"Agent {agent_id} has been observed reaching {counts['servers_reachable']} "
                f"server(s) and {counts['capabilities_exposed']} capability(ies); "
                f"{counts['capabilities_authorized']} authorized, "
                f"{counts['capabilities_unauthorized']} not. This is observed reach, not a "
                "proof of total reach."
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
        if not agent_ids:
            missing.append(f"capability_installations:capability_id={capability_id}")

        authorized = await self._authorization_split_by_agent(
            tenant_id, capability_id=capability_id, agent_ids=agent_ids, missing=missing
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

    async def _authorization_split(
        self,
        tenant_id: str,
        *,
        agent_id: str,
        capability_ids: list[str],
        missing: list[str],
    ) -> Optional[set[str]]:
        if len(capability_ids) > _AUTHORIZATION_CHECK_LIMIT:
            missing.append("capability_authorizations:check_truncated")
            return None
        authorized: set[str] = set()
        for cid in capability_ids:
            facts = await capability_authority_service.resolve(
                tenant_id=tenant_id, agent_id=agent_id, capability_id=cid
            )
            if facts.get("authorized"):
                authorized.add(cid)
        return authorized

    async def _authorization_split_by_agent(
        self,
        tenant_id: str,
        *,
        capability_id: str,
        agent_ids: list[str],
        missing: list[str],
    ) -> Optional[set[str]]:
        if len(agent_ids) > _AUTHORIZATION_CHECK_LIMIT:
            missing.append("capability_authorizations:check_truncated")
            return None
        authorized: set[str] = set()
        for aid in agent_ids:
            facts = await capability_authority_service.resolve(
                tenant_id=tenant_id, agent_id=aid, capability_id=capability_id
            )
            if facts.get("authorized"):
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
    "capabilities_authorized",
    "capabilities_unauthorized",
)

_CAPABILITY_COUNT_KEYS = (
    "agents_reaching",
    "agents_authorized",
    "agents_unauthorized",
)


capability_risk_service = CapabilityRiskService()
