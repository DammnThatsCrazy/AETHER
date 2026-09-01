"""The only sanctioned path from Kyber into one tenant's own graph.

Everything else in this package answers questions about the *platform* —
services, releases, fleet projections, cohorts. This module is the one place a
Kyber operator reaches a single tenant's entities, and it exists so that reach
is a narrow, auditable, ordered gate rather than a query-time filter.

The order is fixed and every step fails closed:

===  ===============================================================  ======================
 #   Check                                                            Denial
===  ===============================================================  ======================
 1   A Kyber context was attached by the route dependency             ``no_kyber_context``
 2   The tenant-graph capability is held                              ``capability_missing``
 3   An active, unexpired tenant access scope exists                  ``scope_missing`` /
                                                                      ``scope_expired``
 4   The requested tenant IS the scope's tenant                       ``scope_tenant_mismatch``
 5   Granted disclosure reaches the masked-tenant floor               ``disclosure_exceeded``
 6   A tenant graph backend and a Kyber graph store both resolve      ``graph_unavailable``
 7   Tenant-scoped read, hard result/traversal budget                 —
 8   Redaction per granted disclosure                                 —
 9   Evidence references attached (gated on the evidence capability)   —
===  ===============================================================  ======================

Step 4 is a *denial*, never a silent rescope. A request whose path or query
names tenant B while the live scope names tenant A is an attempt — deliberate or
a client bug — and answering it with tenant A's data would make the audit trail
lie about what was asked for.

Step 7 reads through ``GraphClient.get_vertices_for_tenant``, which pushes the
tenant predicate into the query, and never through ``get_all_vertices``. That is
not a stylistic preference: a global page filtered by tenant afterwards silently
truncates, and a tenant whose vertices sort past the cap reads to the operator
as "this tenant has no data". ``scripts/validate_graph_scoped_reads.py`` freezes
that. For the same reason the neighborhood walk drops foreign neighbours
*before* charging the node budget, so a noisy neighbour can never shrink the
answer a caller gets about their own tenant.

The response is deliberately two-keyed — ``tenantVisible`` and
``operatorDiagnostics`` — so a later Tenant Mirror parity check can compare only
the first key against what the tenant's own API returns, without diffing
operator-only metadata that the tenant never sees.
"""
from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from shared.common.common import ForbiddenError, utc_now
from shared.graph.graph import tenant_of
from shared.temporal.instant import try_parse_instant
from shared.logger.logger import get_logger, metrics
from shared.rights_authority.contracts import ActorRef, DestinationRef
from shared.rights_authority.pep import evaluate_rights

from ..access.disclosure import DisclosureLevel
from .contracts import now_iso

logger = get_logger("aether.kyber.graph.gateway")

#: Capability that gates a scoped tenant graph read.
TENANT_GRAPH_CAPABILITY = "kyber.graph.tenant.read"

#: Any one of these authorizes a scoped tenant read through this gateway.
#:
#: The Tenant Mirror reads a tenant's data through this same gateway — by
#: design, because it is the only sanctioned path — but its routes are gated on
#: the mirror capability, not the graph one. Requiring only
#: ``TENANT_GRAPH_CAPABILITY`` here meant a principal granted exactly
#: ``kyber.tenant.mirror.read`` passed the route dependency and was then denied
#: *inside* the gateway: one request, allowed and then refused, with a reason
#: naming a capability the operator was never told they needed. No shipped role
#: hits it — ``access/roles.py`` grants the two together — but a direct
#: capability grant does, and an authorization that depends on a bundle
#: happening to include a second capability is not an authorization rule, it is
#: a coincidence.
#:
#: These are alternatives, not a widening: each already authorizes reading one
#: tenant's data at D2 or above, every one of them still passes through the
#: identical scope, tenant-match, disclosure and budget checks below, and none
#: of them can be reached without an active purpose-bound scope.
TENANT_READ_CAPABILITIES: frozenset[str] = frozenset({
    TENANT_GRAPH_CAPABILITY,
    "kyber.tenant.mirror.read",
    "kyber.tenant.mirror.read_masked",
})

#: Capability that gates lineage / evidence *references* on that read.
EVIDENCE_CAPABILITY = "kyber.graph.evidence.read"

#: A tenant graph read reveals one tenant, so it needs at least the masked
#: tenant level. Below that the caller may see topology and nothing else.
MINIMUM_DISCLOSURE = DisclosureLevel.D2_TENANT_MASKED

#: Hard ceilings. A request may ask for less; it may never ask for more.
MAX_RESULT_BUDGET = 500
MAX_TRAVERSAL_DEPTH = 3
MAX_NEIGHBORHOOD_NODES = 200

#: Node key template for the Tenant node in the Kyber graph.
TENANT_NODE_KEY = "tenant:{tenant_id}"

#: Property names that identify a tenant, a person, or a device and are
#: therefore masked at or below D2. Compared case-insensitively.
_TENANT_IDENTIFYING_KEYS: frozenset[str] = frozenset({
    "account_id", "account_name", "address", "company", "company_name",
    "customer_id", "device_id", "display_name", "domain", "email",
    "external_id", "first_name", "full_name", "ip", "ip_address", "last_name",
    "name", "org_id", "organization", "organization_id", "phone", "referrer",
    "session_id", "tenant", "tenant_id", "tenantid", "url", "user_id",
    "username", "wallet",
})


# ── Denials ──────────────────────────────────────────────────────────────────


def _deny(reason: str, detail: str) -> ForbiddenError:
    """Build the denial for one failed step, counting and logging it.

    Denials are returned rather than raised so the call site reads as a single
    ``raise _deny(...)`` and the ordered gate stays visible in one function.
    """
    metrics.increment("kyber_graph_gateway_denied_total", labels={"reason": reason})
    logger.warning(f"kyber: scoped graph gateway denied reason={reason} detail={detail}")
    return ForbiddenError(detail, details={"denial_reason": reason})


# ── Provider indirection ─────────────────────────────────────────────────────
#
# The Kyber graph store and the tenant graph backend are both resolved through
# providers rather than imported at module scope. Two reasons: this package is
# built alongside the repository that backs it, and — more importantly — an
# unresolvable provider must DENY. A gateway that answers when its store is
# missing would report "this tenant has no data" for an infrastructure fault,
# which is the exact failure mode this plane was created to remove.

_STORE_MODULE = "services.kyber.graph.repository"
_STORE_SINGLETON = "kyber_graph_store"
_STORE_CLASS = "KyberGraphStore"

_store: Any = None
_store_probed = False

_tenant_graph: Any = None


def set_store(store: Any) -> None:
    """Install the Kyber graph store. The seam tests use to supply a fake."""
    global _store, _store_probed
    _store = store
    _store_probed = True


def reset_store() -> None:
    """Forget the cached store so the next call re-resolves it."""
    global _store, _store_probed
    _store = None
    _store_probed = False


def get_store() -> Optional[Any]:
    """The Kyber graph store, or ``None`` when it cannot be resolved.

    ``None`` means *deny* at every call site in this package. Resolution goes
    through :func:`importlib.import_module` rather than a ``from ... import``
    so this module stays importable while the repository is being built, and so
    import order between the two is never load-bearing.
    """
    global _store, _store_probed
    if _store is not None:
        return _store
    if _store_probed:
        return None
    _store_probed = True
    try:
        module = importlib.import_module(_STORE_MODULE)
    except Exception as exc:  # pragma: no cover - repository not yet deployed
        logger.warning(f"kyber: graph store unavailable ({_STORE_MODULE}): {exc}")
        return None
    resolved = getattr(module, _STORE_SINGLETON, None)
    if resolved is None:
        factory = getattr(module, _STORE_CLASS, None)
        if factory is not None:
            try:
                resolved = factory()
            except Exception as exc:  # pragma: no cover - constructor mismatch
                logger.error(f"kyber: graph store {_STORE_CLASS}() failed: {exc}")
                resolved = None
    if resolved is None:
        logger.error(
            f"kyber: {_STORE_MODULE} imports but exports neither "
            f"{_STORE_SINGLETON!r} nor {_STORE_CLASS!r}; graph reads will deny"
        )
    _store = resolved
    return _store


def set_tenant_graph(client: Any) -> None:
    """Install the tenant graph backend. The seam tests use to supply a fake."""
    global _tenant_graph
    _tenant_graph = client


def reset_tenant_graph() -> None:
    """Forget the injected tenant graph backend."""
    global _tenant_graph
    _tenant_graph = None


def get_tenant_graph() -> Optional[Any]:
    """The tenant graph backend, or ``None`` when it cannot be resolved."""
    if _tenant_graph is not None:
        return _tenant_graph
    try:
        from shared.graph.graph import get_graph_client

        return get_graph_client()
    except Exception as exc:  # pragma: no cover - graph package unavailable
        logger.error(f"kyber: tenant graph backend unavailable: {exc}")
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse an exact instant, or return ``None`` — never a guess.

    Delegates to :func:`shared.temporal.instant.try_parse_instant`, which
    refuses a timezone-naive value rather than assuming UTC. An earlier version
    did assume it, and that assumption is not harmless here: this parser's
    primary caller is the scope-expiry gate, so silently reading a naive
    timestamp as UTC could *extend* an operator's access to a tenant by up to a
    day depending on where the value came from. Guessing a timezone is a policy
    decision, and the one place it must never be made implicitly is the check
    deciding whether authority has lapsed.

    ``None`` is the safe answer everywhere it is used: the gateway treats an
    unparseable expiry as expired (fail closed), and the fleet reader counts an
    unparseable ``computed_at`` as undated, which forces ``totals_known: false``
    rather than passing the row off as fresh.

    Shared with :mod:`services.kyber.graph.fleet` so one timestamp cannot be
    "expired" to the gateway and "fresh" to the fleet reader.
    """
    if not value:
        return None
    parsed, _reason = try_parse_instant(str(value))
    return parsed


def _mask(value: Any) -> str:
    """A stable, non-reversible token for one identifying value.

    Stable so an operator can still correlate two masked appearances of the
    same entity within one response; non-reversible so the identifier itself is
    not disclosed below D3.
    """
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"masked:{digest[:12]}"


def _redact_properties(properties: dict[str, Any], *, masked: bool) -> dict[str, Any]:
    """Mask tenant-identifying properties when disclosure requires it."""
    if not masked:
        return dict(properties)
    return {
        key: (_mask(value) if key.lower() in _TENANT_IDENTIFYING_KEYS else value)
        for key, value in properties.items()
    }


def _serialize_vertex(vertex: Any, *, masked: bool) -> dict[str, Any]:
    """Render one tenant vertex at the granted disclosure level."""
    vertex_id = getattr(vertex, "vertex_id", None)
    properties = dict(getattr(vertex, "properties", None) or {})
    return {
        "vertex_id": _mask(vertex_id) if masked and vertex_id else vertex_id,
        "vertex_type": getattr(vertex, "vertex_type", None),
        "properties": _redact_properties(properties, masked=masked),
    }


@dataclass(frozen=True)
class _Authorized:
    """What the ordered gate resolved. Built only after every step passed."""

    context: Any
    tenant_id: str
    disclosure: DisclosureLevel
    masked: bool
    store: Any
    graph: Any
    evidence_allowed: bool
    rights_decision_id: Optional[str] = None

    @property
    def scope_id(self) -> Optional[str]:
        scope = getattr(self.context, "scope", None)
        return getattr(scope, "scope_id", None) if scope is not None else None

    @property
    def purpose(self) -> Optional[str]:
        scope = getattr(self.context, "scope", None)
        return getattr(scope, "purpose", None) if scope is not None else None


class ScopedTenantGraphGateway:
    """A tenant-graph read that cannot leave the scope it was granted.

    Instances are stateless apart from their budgets, so the module singleton
    is safe to share. Budgets are constructor arguments purely so tests can
    drive the truncation path with small numbers instead of seeding 500 rows.
    """

    def __init__(
        self,
        *,
        max_results: int = MAX_RESULT_BUDGET,
        max_depth: int = MAX_TRAVERSAL_DEPTH,
        max_nodes: int = MAX_NEIGHBORHOOD_NODES,
    ) -> None:
        self.max_results = max(1, int(max_results))
        self.max_depth = max(1, int(max_depth))
        self.max_nodes = max(1, int(max_nodes))

    # ── The ordered gate ─────────────────────────────────────────────────────

    async def _authorize(self, request: Any, tenant_id: str) -> _Authorized:
        """Run steps 1-6. Raises ``ForbiddenError`` at the first failure."""
        # 1 ── The route dependency must have authorized this request. A handler
        # reaching the gateway without a context is a wiring mistake, and the
        # only safe reading of a missing authorization is "not authorized".
        context = _current_context(request)
        if context is None:
            raise _deny(
                "no_kyber_context",
                "This tenant graph read was not authorized by the Kyber access dependency",
            )

        # 2 ── Capability.
        capabilities = getattr(context, "capabilities", frozenset()) or frozenset()
        if not (TENANT_READ_CAPABILITIES & set(capabilities)):
            raise _deny(
                "capability_missing",
                "Capability not held for scoped tenant graph reads; one of "
                f"{sorted(TENANT_READ_CAPABILITIES)} is required",
            )

        # 3 ── An active, unexpired scope. `resolve_for_tenant` already checked
        # this upstream; it is re-checked here because this module is reachable
        # from background work and from nested handler calls, and because a
        # scope can expire between authorization and the read.
        scope = getattr(context, "scope", None)
        if scope is None:
            raise _deny("scope_missing", "No active tenant access scope for this session")
        if getattr(scope, "status", None) != "active":
            raise _deny(
                "scope_expired",
                f"Tenant access scope is {getattr(scope, 'status', 'unusable')!r}",
            )
        expires_at = parse_iso(getattr(scope, "expires_at", None))
        if expires_at is None or expires_at <= utc_now():
            raise _deny("scope_expired", "Tenant access scope has expired")

        # 4 ── The requested tenant must BE the scope's tenant. Both the
        # explicit argument and whatever the request itself named are compared;
        # either disagreeing is a denial, never a rescope.
        requested = str(tenant_id or "").strip()
        if not requested:
            raise _deny("scope_missing", "A tenant id is required for a scoped graph read")
        scope_tenant = str(getattr(scope, "tenant_id", "") or "")
        if requested != scope_tenant:
            raise _deny(
                "scope_tenant_mismatch",
                "The requested tenant is not the tenant this scope was granted for",
            )
        named = getattr(context, "tenant_id", None)
        if named and str(named) != scope_tenant:
            raise _deny(
                "scope_tenant_mismatch",
                "The tenant named by the request disagrees with the active scope",
            )

        # IRRL is the second, independent authority: the workforce scope says
        # which tenant an operator may approach, while rights says whether the
        # underlying tenant data may be read on Kyber. The envelope reference
        # is carried on the scope and is never accepted from the request path.
        rights_result = await evaluate_rights(
            action="operate_kyber",
            tenant_id=scope_tenant,
            actor=ActorRef(
                kind="operator",
                id=str(getattr(context, "operator_id", "kyber")),
            ),
            purpose=str(getattr(scope, "purpose", "diagnostics")),
            envelope_refs=(
                [scope.rights_envelope_ref] if getattr(scope, "rights_envelope_ref", None)
                else getattr(scope, "metadata", {}).get("rights_envelope_refs", [])
            ),
            policy_set_ref=getattr(scope, "metadata", {}).get("rights_policy_set_ref"),
            destination=DestinationRef(kind="aether_internal", id="kyber"),
            artifacts=[{"kind": "tenant_graph", "id": scope_tenant, "tenant_id": scope_tenant}],
            metadata={
                "scope_id": getattr(scope, "scope_id", None),
                "ticket_reference": getattr(scope, "ticket_reference", None),
            },
        )
        if not rights_result.proceed:
            reason = ",".join(rights_result.reason_codes) or "rights_denied"
            raise _deny(
                "rights_authority",
                f"Kyber tenant read blocked by rights authority: {reason}",
            )

        # 5 ── Disclosure ceiling.
        disclosure = getattr(context, "granted_disclosure", DisclosureLevel.D0_PLATFORM_TOPOLOGY)
        disclosure = DisclosureLevel(int(disclosure))
        if disclosure < MINIMUM_DISCLOSURE:
            raise _deny(
                "disclosure_exceeded",
                "Granted disclosure is below the masked-tenant floor for graph reads",
            )
        masks = getattr(context, "masks_identifiers", None)
        masked = bool(masks()) if callable(masks) else disclosure <= MINIMUM_DISCLOSURE

        # 6 ── Backends. Absence denies; it never reads as an empty tenant.
        store = get_store()
        if store is None:
            raise _deny("graph_unavailable", "The Kyber graph store is unavailable")
        graph = get_tenant_graph()
        if graph is None:
            raise _deny("graph_unavailable", "The tenant graph backend is unavailable")

        return _Authorized(
            context=context,
            tenant_id=scope_tenant,
            disclosure=disclosure,
            masked=masked,
            store=store,
            graph=graph,
            evidence_allowed=EVIDENCE_CAPABILITY in capabilities,
            rights_decision_id=(
                rights_result.decision.decision_id
                if rights_result.decision else None
            ),
        )

    # ── Reads ────────────────────────────────────────────────────────────────

    async def query(
        self,
        request: Any,
        *,
        tenant_id: str,
        vertex_type: Optional[str] = None,
        limit: int = MAX_RESULT_BUDGET,
    ) -> dict[str, Any]:
        """One page of a tenant's own vertices, at the granted disclosure level.

        Args:
            request: The authorized request; carries the Kyber context.
            tenant_id: The tenant being asked about. Must equal the scope's.
            vertex_type: Optional vertex label filter, pushed into the query.
            limit: Requested page size, clamped to the gateway's budget.

        Returns:
            ``{"tenantVisible": {...}, "operatorDiagnostics": {...}}``. The
            first key is comparable against the tenant's own API; the second is
            operator-only metadata.

        Raises:
            ForbiddenError: At the first failed step of the ordered gate.
        """
        resolved = await self._authorize(request, tenant_id)
        budget = min(max(1, int(limit)), self.max_results)

        # Ask for one more than the budget so truncation is *detected* rather
        # than inferred. A silent cap is how the previous defect read as
        # "no data" instead of "there is more".
        vertices = list(
            await resolved.graph.get_vertices_for_tenant(
                resolved.tenant_id, budget + 1, vertex_type=vertex_type
            )
        )
        truncated = len(vertices) > budget
        if truncated:
            vertices = vertices[:budget]

        evidence, evidence_missing = await self._evidence(resolved)
        metrics.increment(
            "kyber_graph_gateway_reads_total",
            labels={"surface": "query", "truncated": str(truncated).lower()},
        )
        return {
            "tenantVisible": {
                "tenant_id": _mask(resolved.tenant_id) if resolved.masked else resolved.tenant_id,
                "vertex_type": vertex_type,
                "vertices": [_serialize_vertex(v, masked=resolved.masked) for v in vertices],
                "vertex_count": len(vertices),
                "truncated": truncated,
            },
            "operatorDiagnostics": self._diagnostics(
                resolved,
                surface="query",
                budget=budget,
                requested_limit=int(limit),
                truncated=truncated,
                result_count=len(vertices),
                evidence_references=evidence,
                missing_inputs=evidence_missing
                + (["tenant_vertices:scan_truncated"] if truncated else []),
            ),
        }

    async def neighborhood(
        self,
        request: Any,
        *,
        tenant_id: str,
        vertex_id: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """A bounded neighbourhood around one of the tenant's own vertices.

        Foreign neighbours are dropped before they can charge the node budget,
        so another tenant's density can never truncate this tenant's answer. An
        anchor that does not exist and an anchor belonging to another tenant
        return the same ``found: false`` shape on purpose — distinguishing them
        would turn this route into a cross-tenant existence oracle.
        """
        resolved = await self._authorize(request, tenant_id)
        walk_depth = min(max(1, int(depth)), self.max_depth)

        anchor = await resolved.graph.get_vertex(vertex_id)
        if anchor is None or tenant_of(getattr(anchor, "properties", None)) != resolved.tenant_id:
            metrics.increment(
                "kyber_graph_gateway_reads_total",
                labels={"surface": "neighborhood", "truncated": "false"},
            )
            return {
                "tenantVisible": {
                    "tenant_id": (
                        _mask(resolved.tenant_id) if resolved.masked else resolved.tenant_id
                    ),
                    "found": False,
                    "anchor": None,
                    "neighbors": [],
                    "vertex_count": 0,
                    "depth": walk_depth,
                    "truncated": False,
                },
                "operatorDiagnostics": self._diagnostics(
                    resolved,
                    surface="neighborhood",
                    budget=self.max_nodes,
                    requested_limit=int(depth),
                    truncated=False,
                    result_count=0,
                    evidence_references=[],
                    missing_inputs=["tenant_vertex:not_resolved_in_scope"],
                ),
            }

        neighbors, truncated, depth_reached = await self._walk(
            resolved, anchor=anchor, depth=walk_depth
        )
        evidence, evidence_missing = await self._evidence(resolved)
        metrics.increment(
            "kyber_graph_gateway_reads_total",
            labels={"surface": "neighborhood", "truncated": str(truncated).lower()},
        )
        return {
            "tenantVisible": {
                "tenant_id": _mask(resolved.tenant_id) if resolved.masked else resolved.tenant_id,
                "found": True,
                "anchor": _serialize_vertex(anchor, masked=resolved.masked),
                "neighbors": [_serialize_vertex(v, masked=resolved.masked) for v in neighbors],
                "vertex_count": len(neighbors),
                "depth": depth_reached,
                "truncated": truncated,
            },
            "operatorDiagnostics": self._diagnostics(
                resolved,
                surface="neighborhood",
                budget=self.max_nodes,
                requested_limit=int(depth),
                truncated=truncated,
                result_count=len(neighbors),
                evidence_references=evidence,
                missing_inputs=evidence_missing
                + (["tenant_neighborhood:node_budget_reached"] if truncated else []),
            ),
        }

    # ── Internals ────────────────────────────────────────────────────────────

    async def _walk(
        self, resolved: _Authorized, *, anchor: Any, depth: int
    ) -> tuple[list[Any], bool, int]:
        """Breadth-first over the tenant's own vertices, cycle- and budget-safe."""
        anchor_id = getattr(anchor, "vertex_id", None)
        visited: set[str] = {str(anchor_id)}
        frontier: list[Any] = [anchor]
        collected: list[Any] = []
        truncated = False
        reached = 0

        for hop in range(depth):
            next_frontier: list[Any] = []
            for vertex in frontier:
                vid = getattr(vertex, "vertex_id", None)
                if not vid:
                    continue
                for neighbor in await resolved.graph.get_neighbors(vid, direction="both"):
                    nid = str(getattr(neighbor, "vertex_id", "") or "")
                    if not nid or nid in visited:
                        continue
                    # Drop foreign vertices BEFORE charging the budget.
                    if tenant_of(getattr(neighbor, "properties", None)) != resolved.tenant_id:
                        continue
                    if len(collected) >= self.max_nodes:
                        truncated = True
                        break
                    visited.add(nid)
                    collected.append(neighbor)
                    next_frontier.append(neighbor)
                if truncated:
                    break
            reached = hop + 1
            if truncated or not next_frontier:
                break
            frontier = next_frontier
        return collected, truncated, reached

    async def _evidence(self, resolved: _Authorized) -> tuple[list[str], list[str]]:
        """Evidence references for the tenant, gated on the evidence capability.

        The Tenant node in the Kyber graph carries a pointer into the evidence
        store; the pointer is disclosed only to a caller holding
        ``kyber.graph.evidence.read``. Everyone else gets the count, which says
        that evidence exists without saying where.
        """
        try:
            node = await resolved.store.get_node(
                TENANT_NODE_KEY.format(tenant_id=resolved.tenant_id),
                environment=getattr(resolved.context, "environment", None),
            )
        except Exception as exc:
            logger.warning(f"kyber: tenant node lookup failed: {exc}")
            return [], ["kyber_graph_tenant_node:lookup_failed"]
        if node is None:
            return [], [f"kyber_graph_tenant_node:tenant_id={resolved.tenant_id}"]
        reference = getattr(node, "evidence_reference", None)
        if not reference:
            return [], []
        return ([str(reference)] if resolved.evidence_allowed else []), []

    def _diagnostics(
        self,
        resolved: _Authorized,
        *,
        surface: str,
        budget: int,
        requested_limit: int,
        truncated: bool,
        result_count: int,
        evidence_references: list[str],
        missing_inputs: list[str],
    ) -> dict[str, Any]:
        """Operator-only metadata. Never compared by the Tenant Mirror parity check."""
        context = resolved.context
        held = getattr(context, "capabilities", frozenset()) or frozenset()
        # The capability this read was ACTUALLY authorized by, not the graph one
        # by default. Since TENANT_READ_CAPABILITIES accepts the mirror
        # capabilities too, naming the graph capability unconditionally would put
        # a capability the operator may not hold into the evidence record — and
        # this record is what an auditor reads to reconstruct who was allowed to
        # do what. Sorted so the value is stable across runs.
        authorized_by = sorted(TENANT_READ_CAPABILITIES & set(held))
        return {
            "surface": surface,
            "capability": authorized_by[0] if authorized_by else None,
            "authorized_by": authorized_by,
            "operator_id": getattr(context, "operator_id", None),
            "session_id": getattr(context, "session_id", None),
            "device_id": getattr(context, "device_id", None),
            "environment": getattr(context, "environment", None),
            "scope_id": resolved.scope_id,
            "purpose": resolved.purpose,
            "granted_disclosure": resolved.disclosure.name_token,
            "identifiers_masked": resolved.masked,
            "requested_limit": requested_limit,
            "budget": budget,
            "result_count": result_count,
            "truncated": truncated,
            "evidence_disclosure_gated": not resolved.evidence_allowed,
            "evidence_reference_count": len(evidence_references),
            "evidence_references": evidence_references,
            "missing_inputs": missing_inputs,
            "exposure_known": not truncated and not missing_inputs,
            "computed_at": now_iso(),
            "rights_decision_id": resolved.rights_decision_id,
        }


def _current_context(request: Any) -> Any:
    """The Kyber context the route dependency stashed, or ``None``.

    Imported lazily and declared in ``services/kyber/seams.py`` so a rename in
    the access plane fails the seam gate instead of silently degrading every
    tenant graph read into a denial.
    """
    try:
        from services.kyber.access.dependencies import current_kyber_context
    except ImportError as exc:  # pragma: no cover - access plane unavailable
        logger.error(f"kyber: access dependency unavailable, graph reads deny: {exc}")
        return None
    return current_kyber_context(request)


#: Process-wide gateway. Stateless apart from its budgets.
scoped_tenant_graph_gateway = ScopedTenantGraphGateway()


__all__ = [
    "EVIDENCE_CAPABILITY",
    "MAX_NEIGHBORHOOD_NODES",
    "MAX_RESULT_BUDGET",
    "MAX_TRAVERSAL_DEPTH",
    "MINIMUM_DISCLOSURE",
    "TENANT_GRAPH_CAPABILITY",
    "TENANT_READ_CAPABILITIES",
    "ScopedTenantGraphGateway",
    "get_store",
    "get_tenant_graph",
    "parse_iso",
    "reset_store",
    "reset_tenant_graph",
    "scoped_tenant_graph_gateway",
    "set_store",
    "set_tenant_graph",
]
