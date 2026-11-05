"""Reconciliation and read API over the principal <-> agent lineage projection.

``reconcile`` folds tenant evidence into a :class:`LineageEngine` and persists the
delta. Reads never touch the engine: every endpoint answers from the materialized
tables, so request cost is bounded by page size rather than by population.

Three query modes (work order §28): interactive pages stay inside the graph-window
budgets, the analytical summary/cluster/risk reads are pre-aggregated, and full
extraction goes through the platform export job. A budget limits what one request
returns, never what is known, and every response says what it left out.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from shared.agent_lineage import vocabulary as vocab
from shared.agent_lineage.models import Disclosure, LineageSummary, TreeNode
from shared.logger.logger import get_logger, metrics

from ._common import (
    PATH_SEP,
    UNATTRIBUTED,
    LineageQueryError,
    clamp_page_size,
    decode_cursor,
    encode_cursor,
    epoch,
    ref,
)
from .config import DEFAULT_CONFIG, PROJECTION_VERSION, LineageConfig
from .engine import LineageEngine, ResolveResult, compare_rows
from .evidence import AuthorityRecord, PrincipalBinding
from .repository import InMemoryLineageRepository, LineageRepository, PostgresLineageRepository, validate_filters

logger = get_logger("aether.agent_lineage.service")

SILVER_TABLE = "silver_agent_execution_facts"
SILVER_PAGE = 1000
DELEGATION_PAGE = 500
MAX_CACHED_ENGINES = 4
#: A projection this old is reported ``stale`` instead of ``complete``.
STALE_AFTER_SECONDS = 6 * 3600.0
#: Facts read per reconcile. Hitting it is disclosed on every affected summary.
MAX_FACTS_PER_RECONCILE = 20_000_000
#: Rows per export part, sized so a part of ``EXPORT_COLUMNS`` stays inside the artifact cap.
EXPORT_PART_ROWS = 50_000
EXPORT_COLUMNS = (
    "principal_entity_id", "agent_entity_id", "parent_agent_id", "root_agent_id", "depth",
    "relationship_type", "relationship_status", "direct_or_indirect", "attribution_class", "evidence_class",
    "authority_ref", "authority_resolution_status", "lineage_status", "active_state", "first_seen", "last_seen",
    "evidence_count", "evidence_digest", "agent_definition_id", "agent_deployment_id",
)
ALIAS_FIELDS = ("agent_id", "parent_agent_ref", "child_agent_ref", "delegated_to_ref", "root_agent_ref")

SilverPageReader = Callable[[str, Optional[str]], Awaitable[tuple[list[dict[str, Any]], Optional[str]]]]
Loader = Callable[[str], Awaitable[list[Any]]]
AliasLoader = Callable[[str], Awaitable[dict[str, str]]]


async def _silver_pages(tenant_id: str, cursor: Optional[str]) -> tuple[list[dict[str, Any]], Optional[str]]:
    from dependencies.providers import get_cache
    from repositories.repos import AnalyticsRepository

    rows, next_cursor, _ = await AnalyticsRepository(get_cache()).query_silver_page(
        SILVER_TABLE, {"tenant_id": tenant_id}, limit=SILVER_PAGE, cursor=cursor,
    )
    return rows, next_cursor


async def _delegation_authority(tenant_id: str) -> list[AuthorityRecord]:
    """Issued delegations are verified authority; revocation bumps the version."""
    from repositories.repos import DelegationRepository

    repo = DelegationRepository()
    out: list[AuthorityRecord] = []
    offset = 0
    while True:
        page = await repo.find_many(filters={"tenant_id": tenant_id}, limit=DELEGATION_PAGE, offset=offset)
        for row in page:
            record = authority_from_delegation(tenant_id, row)
            if record is not None:
                out.append(record)
        if len(page) < DELEGATION_PAGE:
            return out
        offset += DELEGATION_PAGE


def authority_from_delegation(tenant_id: str, row: dict[str, Any]) -> Optional[AuthorityRecord]:
    if row.get("tenant_id") != tenant_id:
        return None
    delegation_id = ref(row.get("delegation_id")) or ref(row.get("id"))
    grantor = ref(row.get("grantor_entity_id"))
    grantee = ref(row.get("grantee_entity_id"))
    if not (delegation_id and grantor and grantee):
        return None
    scope = row.get("scope") if isinstance(row.get("scope"), dict) else {}
    max_depth = scope.get("maximum_delegation_depth")
    allowed = scope.get("delegation_allowed")
    return AuthorityRecord(
        tenant_id=tenant_id,
        authority_ref=delegation_id,
        grantor_entity_id=grantor,
        grantee_entity_id=grantee,
        authority_type="delegation",
        delegation_allowed=allowed if isinstance(allowed, bool) else None,
        maximum_delegation_depth=max_depth if isinstance(max_depth, int) and max_depth >= 0 else None,
        valid_from=epoch(row.get("starts_at")),
        valid_until=epoch(row.get("ends_at")),
        revoked_at=epoch(row.get("revoked_at")),
        verified=True,
        version=2 if row.get("revoked_at") else 1,
        evidence_refs=(f"delegation:{delegation_id}",),
    )


async def _stored_bindings(tenant_id: str) -> list[PrincipalBinding]:
    from .repository import PrincipalBindingRepository

    repo = PrincipalBindingRepository()
    out: list[PrincipalBinding] = []
    offset = 0
    while True:
        page = await repo.find_many(filters={"tenant_id": tenant_id}, limit=DELEGATION_PAGE, offset=offset)
        for row in page:
            if row.get("tenant_id") == tenant_id:
                out.append(PrincipalBinding.from_mapping(row))
        if len(page) < DELEGATION_PAGE:
            break
        offset += DELEGATION_PAGE
    out.extend(await _registered_owner_bindings(tenant_id))
    return out


async def _registered_owner_bindings(tenant_id: str) -> list[PrincipalBinding]:
    """An agent registered under an owner is a deterministic binding to that owner."""
    from repositories.repos import AgentConfigRepository

    repo = AgentConfigRepository()
    out: list[PrincipalBinding] = []
    offset = 0
    while True:
        page = await repo.find_many(filters={"tenant_id": tenant_id}, limit=DELEGATION_PAGE, offset=offset)
        for row in page:
            agent = ref(row.get("agent_id"))
            owner = ref(row.get("owner_entity_id"))
            if row.get("tenant_id") == tenant_id and agent and owner:
                out.append(PrincipalBinding(
                    tenant_id=tenant_id, kind="agent", principal_entity_id=owner, agent_entity_id=agent,
                    evidence_class="DETERMINISTIC_BINDING", evidence_refs=(f"agent_config:{agent}",),
                ))
        if len(page) < DELEGATION_PAGE:
            return out
        offset += DELEGATION_PAGE


async def _agent_aliases(tenant_id: str) -> dict[str, str]:
    """Source ref -> canonical agent, only where a tenant binding is unambiguous."""
    from actions.agent_marketplace.identity_binding import AgentDeploymentIdentityBindingRepository

    repo = AgentDeploymentIdentityBindingRepository()
    targets: dict[str, set[str]] = {}
    offset = 0
    while True:
        page = await repo.find_many(filters={"tenant_id": tenant_id}, limit=DELEGATION_PAGE, offset=offset)
        for row in page:
            source = ref(row.get("source_agent_ref"))
            canonical = ref(row.get("canonical_agent_entity_id"))
            if row.get("tenant_id") == tenant_id and row.get("status") == "active" and source and canonical:
                targets.setdefault(source, set()).add(canonical)
        if len(page) < DELEGATION_PAGE:
            break
        offset += DELEGATION_PAGE
    # One ref bound differently in two namespaces stays a source ref: picking one
    # would merge agents the evidence does not say are the same.
    return {source: next(iter(ids)) for source, ids in targets.items() if len(ids) == 1}


def _unavailable_disclosure(reason: str, completeness: str = "unavailable") -> dict[str, Any]:
    return Disclosure(
        projection_version=PROJECTION_VERSION, completeness=completeness, truncated=False,
        truncation_reasons=[reason],
    ).model_dump(mode="json")


def _page(
    items: list[dict[str, Any]], page_size: int, disclosure: dict[str, Any],
    next_cursor: Optional[str], total_estimate: Optional[int] = None,
) -> dict[str, Any]:
    # More rows than this page returned is pagination, not loss: ``next_cursor``
    # names it, and ``total_estimate`` stays None where it is not known.
    return {
        "items": items, "next_cursor": next_cursor, "page_size": page_size,
        "total_estimate": total_estimate, "disclosure": disclosure,
    }


class AgentLineageService:
    def __init__(
        self,
        repo: LineageRepository,
        *,
        silver_reader: SilverPageReader = _silver_pages,
        authority_loader: Loader = _delegation_authority,
        binding_loader: Loader = _stored_bindings,
        alias_loader: AliasLoader = _agent_aliases,
        config: LineageConfig = DEFAULT_CONFIG,
        stale_after_seconds: float = STALE_AFTER_SECONDS,
    ) -> None:
        self.repo = repo
        self._silver_reader = silver_reader
        self._authority_loader = authority_loader
        self._binding_loader = binding_loader
        self._alias_loader = alias_loader
        self._config = config
        self._stale_after = stale_after_seconds
        self._engines: OrderedDict[str, tuple[LineageEngine, str]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}

    # ── reconciliation ────────────────────────────────────────────────────

    async def reconcile(self, tenant_id: str, *, full: bool = False) -> dict[str, Any]:
        """Fold new evidence and persist the delta. ``full`` rebuilds from scratch.

        Incremental passes stop at the first page holding nothing new, so a fact
        arriving with an old timestamp is picked up by the next full rebuild; run
        one periodically. Rebuilds diff against the stored projection and log what
        was restated.
        """
        if not ref(tenant_id):
            raise LineageQueryError("reconcile requires a tenant")
        lock = self._locks.setdefault(tenant_id, asyncio.Lock())
        async with lock:
            return await self._reconcile_locked(tenant_id, full)

    async def _reconcile_locked(self, tenant_id: str, full: bool) -> dict[str, Any]:
        aliases = await self._alias_loader(tenant_id)
        alias_key = hashlib.sha256(json.dumps(sorted(aliases.items())).encode()).hexdigest()
        cached = self._engines.get(tenant_id)
        rebuild = full or cached is None or cached[1] != alias_key
        engine = LineageEngine(tenant_id, self._config) if rebuild else cached[0]

        for record in await self._authority_loader(tenant_id):
            engine.upsert_authority(record)
        for binding in await self._binding_loader(tenant_id):
            engine.upsert_binding(binding)
        facts_read = applied = 0
        cursor: Optional[str] = None
        while True:
            rows, cursor = await self._silver_reader(tenant_id, cursor)
            facts_read += len(rows)
            if aliases:
                rows = [_apply_aliases(row, aliases) for row in rows]
            page_applied = engine.ingest(rows)
            applied += page_applied
            if not cursor or (not rebuild and page_applied == 0):
                break
            if facts_read >= MAX_FACTS_PER_RECONCILE:
                engine.disclose_source_truncation(f"fact_budget:{MAX_FACTS_PER_RECONCILE}")
                break
        result = engine.resolve()
        if rebuild:
            await self._diff_rebuild(tenant_id, engine, result)
        await self.repo.apply(result)
        self._engines[tenant_id] = (engine, alias_key)
        self._engines.move_to_end(tenant_id)
        while len(self._engines) > MAX_CACHED_ENGINES:
            self._engines.popitem(last=False)
        metrics.increment("agent_lineage_reconciled", labels={"mode": "full" if rebuild else "incremental"})
        return {
            "tenant_id": tenant_id,
            "mode": "full" if rebuild else "incremental",
            "facts_read": facts_read,
            "facts_applied": applied,
            "as_of": result.as_of,
            "restatements": len(result.restatements) + result.restatements_dropped,
            **result.stats,
        }

    async def _diff_rebuild(self, tenant_id: str, engine: LineageEngine, result: ResolveResult) -> None:
        prior = await self.repo.prior_rows(tenant_id)
        if not prior:
            return
        removed, restatements, dropped = compare_rows(
            prior, engine.rows(), cap=self._config.restatement_row_log_cap,
        )
        result.rows_removed = sorted(set(result.rows_removed) | set(removed))
        result.restatements = restatements
        result.restatements_dropped = dropped
        current = {key[1] for key in engine.rows()}
        result.nodes_removed = sorted({key[1] for key in removed if key[1] not in current})
        live = {key[0] for key in engine.rows()}
        result.summaries_removed = sorted({key[0] for key in prior if key[0] not in live})

    def forget(self, tenant_id: str) -> None:
        """Drop cached state so the next reconcile rebuilds (used after erasure)."""
        self._engines.pop(tenant_id, None)

    # ── analytical reads ──────────────────────────────────────────────────

    def _overlay(self, summary: dict[str, Any]) -> dict[str, Any]:
        """Add wall-clock freshness to the evidence-derived disclosure."""
        reconciled_at = summary.pop("reconciled_at", None)
        disclosure = dict(summary["disclosure"])
        if reconciled_at:
            disclosure["computed_at"] = reconciled_at
            age = datetime.now(timezone.utc).timestamp() - (epoch(reconciled_at) or 0.0)
            if age > self._stale_after and disclosure["completeness"] == "complete":
                disclosure["completeness"] = "stale"
                disclosure["truncation_reasons"] = [
                    *disclosure["truncation_reasons"], f"not_reconciled_for_seconds:{int(age)}",
                ]
        summary["disclosure"] = disclosure
        return summary

    async def summary(self, tenant_id: str, principal: str) -> dict[str, Any]:
        found = await self.repo.summary(tenant_id, principal)
        if found is None:
            # Not materialized is unknown, never "this principal has no agents".
            return LineageSummary(
                tenant_id=tenant_id, principal_entity_id=principal,
                disclosure=Disclosure(**_unavailable_disclosure("lineage_summary_not_materialized", "unknown")),
            ).model_dump(mode="json")
        return self._overlay(found)

    async def summary_model(self, tenant_id: str, principal: str) -> Optional[LineageSummary]:
        """``LineageSummaryReader`` for Profile360: ``None`` when not materialized."""
        found = await self.repo.summary(tenant_id, principal)
        return LineageSummary(**self._overlay(found)) if found is not None else None

    async def _disclosure(self, tenant_id: str, principal: str) -> dict[str, Any]:
        return (await self.summary(tenant_id, principal))["disclosure"]

    async def agents(
        self, tenant_id: str, principal: str, *, filters: Optional[dict[str, Any]] = None,
        cursor: Optional[str] = None, page_size: Optional[int] = None,
    ) -> dict[str, Any]:
        clean = validate_filters(filters)
        size = clamp_page_size(page_size)
        scope = f"agents|{tenant_id}|{principal}|{json.dumps(clean, sort_keys=True, default=str)}"
        key = decode_cursor(cursor, scope)
        rows = await self.repo.list_rows(tenant_id, principal, clean, key[0] if key else None, size + 1)
        next_cursor = encode_cursor(scope, [rows[size - 1]["agent_entity_id"]]) if len(rows) > size else None
        return _page(rows[:size], size, await self._disclosure(tenant_id, principal), next_cursor)

    async def clusters(
        self, tenant_id: str, principal: str, *, cursor: Optional[str] = None, page_size: Optional[int] = None,
    ) -> dict[str, Any]:
        size = clamp_page_size(page_size)
        scope = f"clusters|{tenant_id}|{principal}"
        key = decode_cursor(cursor, scope)
        rows = await self.repo.list_clusters(tenant_id, principal, tuple(key) if key else None, size + 1)
        next_cursor = None
        if len(rows) > size:
            last = rows[size - 1]
            next_cursor = encode_cursor(scope, [last["member_count"], last["cluster_id"]])
        items = [
            {k: v for k, v in cluster.items() if k not in ("tenant_id", "principal_entity_id")}
            for cluster in rows[:size]
        ]
        for item in items:
            item["next_cursor"] = encode_cursor(
                f"agents|{tenant_id}|{principal}|" + json.dumps({"cluster_id": item["cluster_id"]}, sort_keys=True),
                [""],
            )
        return _page(items, size, await self._disclosure(tenant_id, principal), next_cursor)

    async def tree(
        self, tenant_id: str, principal: str, *, parent: Optional[str] = None, cursor: Optional[str] = None,
        page_size: Optional[int] = None,
    ) -> dict[str, Any]:
        """One level of the delegation tree; each branch collapses to its descendant count."""
        size = min(clamp_page_size(page_size), vocab.INTERACTIVE_MAX_NODES)
        filters: dict[str, Any] = {"parent_agent_id": parent} if parent else {"relationship": "direct"}
        scope = f"tree|{tenant_id}|{principal}|{parent or ''}"
        key = decode_cursor(cursor, scope)
        rows = await self.repo.list_rows(tenant_id, principal, filters, key[0] if key else None, size + 1)
        page_rows = rows[:size]
        nodes = await self.repo.nodes(tenant_id, [row["agent_entity_id"] for row in page_rows])
        items = []
        for row in page_rows:
            node = nodes.get(row["agent_entity_id"]) or {}
            descendants = node.get("recursive_descendant_count")
            items.append(TreeNode(
                agent_entity_id=row["agent_entity_id"],
                depth=row["depth"],
                descendant_count=descendants,
                collapsed=bool(descendants),
                lineage_status=row["lineage_status"],
                relationship_type=row["relationship_type"],
                attribution_class=row["attribution_class"],
            ).model_dump(mode="json"))
        next_cursor = encode_cursor(scope, [page_rows[-1]["agent_entity_id"]]) if len(rows) > size else None
        return _page(items, size, await self._disclosure(tenant_id, principal), next_cursor)

    async def risk(self, tenant_id: str, principal: str) -> dict[str, Any]:
        from intelligence.risk360.fanout import assess_principal

        summary = await self.summary(tenant_id, principal)
        clusters = await self.repo.list_clusters(tenant_id, principal, None, vocab.MAX_PAGE_SIZE)
        return assess_principal(summary, clusters=clusters)

    async def investigation(self, tenant_id: str, principal: str) -> dict[str, Any]:
        """Everything the operator's first screen needs, in bounded reads."""
        summary = await self.summary(tenant_id, principal)
        clusters = await self.clusters(tenant_id, principal, page_size=25)
        risk = await self.risk(tenant_id, principal)
        crossed = await self.agents(tenant_id, principal, filters={"authority_status": "out_of_scope"}, page_size=25)
        revoked = await self.agents(tenant_id, principal, filters={"authority_status": "revoked"}, page_size=25)
        active = await self.agents(tenant_id, principal, filters={"active_state": "active"}, page_size=25)
        unresolved = await self.agents(tenant_id, principal, filters={"attribution_class": "unresolved"}, page_size=25)
        activity = summary.get("activity") or {}
        return {
            "principal_entity_id": principal,
            "suspected_root_principal": principal != UNATTRIBUTED,
            "summary": {k: v for k, v in summary.items() if k != "activity"},
            "linkage": {
                "verified_links": summary.get("verified_links"),
                "inferred_links": summary.get("inferred_links"),
                "probabilistic_links": summary.get("probabilistic_agents"),
                "unresolved_links": summary.get("unresolved_agents"),
            },
            "clusters": clusters,
            "spawn_acceleration": risk["temporal"],
            "common_tools": activity.get("tool_sample"),
            "common_providers": activity.get("provider_sample"),
            "wallets": activity.get("wallet_sample"),
            "authority_boundary_crossings": crossed,
            "revoked_agents": revoked,
            "active_agents": active,
            "unresolved_agents": unresolved,
            "verified_external_effects": activity.get("verified_effect_count"),
            "reported_external_effects": activity.get("reported_effect_count"),
            "risk": risk,
        }

    # ── agent-centred reads ───────────────────────────────────────────────

    async def agent_counts(self, tenant_id: str, agent: str) -> dict[str, Any]:
        node = await self.repo.node(tenant_id, agent)
        if node is None:
            return {
                "direct_child_count": None, "recursive_descendant_count": None, "active_descendant_count": None,
                "risk_descendant_count": None, "max_descendant_depth": None,
                "disclosure": _unavailable_disclosure("agent_not_in_lineage_projection", "unknown"),
            }
        return {
            "direct_child_count": node["direct_child_count"],
            "recursive_descendant_count": node["recursive_descendant_count"],
            "active_descendant_count": node["active_descendant_count"],
            "risk_descendant_count": node["risk_descendant_count"],
            "max_descendant_depth": node["max_descendant_depth"],
            "disclosure": _node_disclosure(node),
        }

    async def agent_detail(self, tenant_id: str, agent: str) -> dict[str, Any]:
        """Agent360's lineage block: execution hierarchy, parent, chain, principals."""
        node = await self.repo.node(tenant_id, agent)
        counts = await self.agent_counts(tenant_id, agent)
        if node is None:
            return {"agent_entity_id": agent, "node": None, "principals": [], "ancestors": [], "counts": counts,
                    "disclosure": counts["disclosure"]}
        ancestors = await self.ancestors(tenant_id, agent)
        return {
            "agent_entity_id": agent,
            "node": {k: v for k, v in node.items() if k != "path"},
            "principals": await self.repo.rows_for_agent(tenant_id, agent),
            "ancestors": ancestors["items"],
            "counts": counts,
            "disclosure": _node_disclosure(node),
        }

    async def ancestors(self, tenant_id: str, agent: str) -> dict[str, Any]:
        node = await self.repo.node(tenant_id, agent)
        if node is None:
            return _page([], 0, _unavailable_disclosure("agent_not_in_lineage_projection", "unknown"), None)
        chain = node["path"].split(PATH_SEP)[:-1] if PATH_SEP in node["path"] else []
        chain = [member for member in chain if member != agent]
        found = await self.repo.nodes(tenant_id, chain)
        items = [_public_node(found[member]) for member in reversed(chain) if member in found]
        return _page(items, len(items), _node_disclosure(node), None)

    async def descendants(
        self, tenant_id: str, agent: str, *, cursor: Optional[str] = None, page_size: Optional[int] = None,
    ) -> dict[str, Any]:
        size = clamp_page_size(page_size)
        node = await self.repo.node(tenant_id, agent)
        if node is None:
            return _page([], size, _unavailable_disclosure("agent_not_in_lineage_projection", "unknown"), None)
        scope = f"descendants|{tenant_id}|{agent}"
        key = decode_cursor(cursor, scope)
        rows = await self.repo.descendants(tenant_id, node, key[0] if key else None, size + 1)
        next_cursor = encode_cursor(scope, [rows[size - 1]["path"]]) if len(rows) > size else None
        return _page(
            [_public_node(row) for row in rows[:size]], size, _node_disclosure(node), next_cursor,
            total_estimate=node.get("recursive_descendant_count"),
        )

    async def restatements(
        self, tenant_id: str, principal: str, *, cursor: Optional[str] = None, page_size: Optional[int] = None,
    ) -> dict[str, Any]:
        size = clamp_page_size(page_size)
        scope = f"restatements|{tenant_id}|{principal}"
        key = decode_cursor(cursor, scope)
        rows = await self.repo.restatements(tenant_id, principal, key[0] if key else None, size + 1)
        next_cursor = encode_cursor(scope, [rows[size - 1]["id"]]) if len(rows) > size else None
        return _page(rows[:size], size, await self._disclosure(tenant_id, principal), next_cursor)

    async def export_part(
        self, tenant_id: str, principal: str, *, filters: Optional[dict[str, Any]] = None,
        after: Optional[str] = None, part_rows: int = EXPORT_PART_ROWS,
    ) -> dict[str, Any]:
        """One part of a full extraction, for the asynchronous export job.

        An artifact has a size cap, so a large principal exports in parts: rows carry
        the evidence fields rather than the whole read-model record, and a part that
        stops early names where the next one starts. Not reachable from a read route.
        """
        clean = validate_filters(filters)
        rows: list[dict[str, Any]] = []
        cursor = after
        complete = False
        while len(rows) < part_rows:
            page = await self.repo.list_rows(
                tenant_id, principal, clean, cursor, min(vocab.MAX_PAGE_SIZE, part_rows - len(rows)),
            )
            rows.extend({column: row.get(column) for column in EXPORT_COLUMNS} for row in page)
            if len(page) < min(vocab.MAX_PAGE_SIZE, part_rows - len(rows) + len(page)):
                complete = True
                break
            cursor = page[-1]["agent_entity_id"]
        if not complete:
            # Exactly part_rows read: only one more row says whether another part exists.
            complete = not await self.repo.list_rows(tenant_id, principal, clean, cursor, 1)
        return {"rows": rows, "next_after": None if complete else cursor, "complete": complete}


def _apply_aliases(row: dict[str, Any], aliases: dict[str, str]) -> dict[str, Any]:
    mapped = None
    for column in ALIAS_FIELDS:
        value = row.get(column)
        if isinstance(value, str) and value in aliases:
            if mapped is None:
                mapped = dict(row)
            mapped[column] = aliases[value]
    return mapped if mapped is not None else row


def _public_node(node: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in node.items() if k != "path"}


def _node_disclosure(node: dict[str, Any]) -> dict[str, Any]:
    status = node.get("lineage_status")
    completeness = {
        "complete": "complete", "depth_limited": "truncated",
        "cyclic": "partial", "partial": "partial", "unresolved_parent": "partial",
    }.get(status, "unknown")
    return Disclosure(
        as_of=node.get("last_seen"), projection_version=node.get("projection_version") or PROJECTION_VERSION,
        completeness=completeness, truncated=status == "depth_limited",
        truncation_reasons=[] if status == "complete" else [f"lineage_status:{status}"],
    ).model_dump(mode="json")


_service: Optional[AgentLineageService] = None


async def get_service() -> AgentLineageService:
    """Process-wide service over Postgres, or in-memory where no database is configured."""
    global _service
    if _service is None:
        from repositories.repos import get_pool

        pool = await get_pool()
        repo: LineageRepository = PostgresLineageRepository(pool) if pool is not None else InMemoryLineageRepository()
        _service = AgentLineageService(repo)
    return _service


def set_service(service: Optional[AgentLineageService]) -> None:
    """Install a service (tests, alternate wiring)."""
    global _service
    _service = service


class ServiceSummaryReader:
    """Profile360 ``LineageSummaryReader`` backed by the process-wide service."""

    async def summary(self, tenant_id: str, principal_entity_id: str) -> Optional[LineageSummary]:
        return await (await get_service()).summary_model(tenant_id, principal_entity_id)
