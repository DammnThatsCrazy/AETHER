"""Stores for the derived lineage read model (in-memory and Postgres).

Both implement the same contract and are exercised by the same test suite. Every
read is tenant-bound and every list uses keyset cursors, so a page costs the same
at agent 90,000 as at agent 10. Nothing here is authoritative: the tables can be
dropped and rebuilt from Silver facts, authority records and bindings.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Protocol

from repositories.repos import BaseRepository

from ._common import PATH_SEP, LineageQueryError
from .engine import ResolveResult

ROW_FILTERS = frozenset({
    "relationship", "attribution_class", "active_state", "lineage_status", "risk",
    "cluster_id", "deployment_id", "operator_entity_id", "authority_status", "min_depth", "max_depth",
    "parent_agent_id", "root_agent_id",
})


class PrincipalBindingRepository(BaseRepository):
    """Tenant principal declarations (table ``agent_lineage_principal_bindings``)."""

    def __init__(self) -> None:
        super().__init__("agent_lineage_principal_bindings")


class AdjudicationRepository(BaseRepository):
    """A person's verdict per agent (table ``agent_lineage_adjudications``)."""

    def __init__(self) -> None:
        super().__init__("agent_lineage_adjudications")


def validate_filters(filters: Optional[dict[str, Any]]) -> dict[str, Any]:
    clean = {key: value for key, value in (filters or {}).items() if value is not None}
    unknown = set(clean) - ROW_FILTERS
    if unknown:
        raise LineageQueryError(f"unknown lineage filter: {sorted(unknown)[0]}")
    if clean.get("relationship") not in (None, "direct", "indirect"):
        raise LineageQueryError("relationship must be direct or indirect")
    if clean.get("risk") not in (None, "flagged", "unflagged", "unknown"):
        raise LineageQueryError("risk must be flagged, unflagged or unknown")
    return clean


def _row_matches(row: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, value in filters.items():
        if key == "relationship":
            if row["direct_or_indirect"] != value:
                return False
        elif key == "risk":
            count = row.get("risk_signal_count")
            state = "unknown" if count is None else ("flagged" if count else "unflagged")
            if state != value:
                return False
        elif key == "cluster_id":
            if value not in (row.get("cluster_ids") or ()):
                return False
        elif key == "deployment_id":
            if row.get("agent_deployment_id") != value:
                return False
        elif key == "authority_status":
            if row.get("authority_resolution_status") != value:
                return False
        elif key == "min_depth":
            if row["depth"] < int(value):
                return False
        elif key == "max_depth":
            if row["depth"] > int(value):
                return False
        elif row.get(key) != value:
            return False
    return True


class StaleLineageGeneration(RuntimeError):
    """An erasure ran after this reconcile read its evidence, so its delta may name the subject."""


class LineageRepository(Protocol):
    async def apply(self, result: ResolveResult, *, expected_generation: Optional[int] = None) -> None: ...
    async def erasure_generation(self, tenant_id: str) -> int: ...
    async def summary(self, tenant_id: str, principal: str) -> Optional[dict[str, Any]]: ...
    async def list_rows(
        self, tenant_id: str, principal: str, filters: dict[str, Any], after: Optional[str], limit: int,
    ) -> list[dict[str, Any]]: ...
    async def list_clusters(
        self, tenant_id: str, principal: str, after: Optional[tuple[int, str]], limit: int,
    ) -> list[dict[str, Any]]: ...
    async def node(self, tenant_id: str, agent: str) -> Optional[dict[str, Any]]: ...
    async def nodes(self, tenant_id: str, agents: Iterable[str]) -> dict[str, dict[str, Any]]: ...
    async def children(self, tenant_id: str, agent: str, after: Optional[str], limit: int) -> list[dict[str, Any]]: ...
    async def descendants(self, tenant_id: str, node: dict[str, Any], after: Optional[str], limit: int) -> list[dict[str, Any]]: ...
    async def rows_for_agent(self, tenant_id: str, agent: str) -> list[dict[str, Any]]: ...
    async def restatements(self, tenant_id: str, principal: str, after: Optional[str], limit: int) -> list[dict[str, Any]]: ...
    async def erase_subject(self, tenant_id: str, refs: Iterable[str]) -> dict[str, int]: ...


class InMemoryLineageRepository:
    """Same contract as the SQL store, for local runs, tests and the scale proof."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
        self._sorted: dict[tuple[str, str], list[str]] = {}
        self._summaries: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._clusters: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(dict)
        self._nodes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._sorted_nodes: dict[str, list[str]] = {}
        self._restatements: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._reconciled_at: dict[tuple[str, str], str] = {}
        self._generations: dict[str, int] = defaultdict(int)

    async def erasure_generation(self, tenant_id: str) -> int:
        return self._generations[tenant_id]

    async def apply(self, result: ResolveResult, *, expected_generation: Optional[int] = None) -> None:
        tenant = result.tenant_id
        if expected_generation is not None and self._generations[tenant] != expected_generation:
            raise StaleLineageGeneration(tenant)
        now = datetime.now(timezone.utc).isoformat()
        principals = set()
        for row in result.rows_upserted:
            self._rows[tenant][row["principal_entity_id"]][row["agent_entity_id"]] = dict(row)
            principals.add(row["principal_entity_id"])
        for principal, agent in result.rows_removed:
            self._rows[tenant][principal].pop(agent, None)
            principals.add(principal)
        for principal in principals:
            self._sorted.pop((tenant, principal), None)
        for node in result.nodes_upserted:
            self._nodes[tenant][node["agent_entity_id"]] = dict(node)
        for agent in result.nodes_removed:
            self._nodes[tenant].pop(agent, None)
        if result.nodes_upserted or result.nodes_removed:
            self._sorted_nodes.pop(tenant, None)
        for summary in result.summaries:
            principal = summary["principal_entity_id"]
            self._summaries[tenant][principal] = dict(summary)
            self._reconciled_at[(tenant, principal)] = now
        for principal in result.summaries_removed:
            self._summaries[tenant].pop(principal, None)
            self._clusters[tenant].pop(principal, None)
        for principal, clusters in result.clusters.items():
            self._clusters[tenant][principal] = [dict(c) for c in clusters]
        for index, entry in enumerate(result.restatements):
            stored = len(self._restatements[tenant])
            self._restatements[tenant].append({**entry, "id": f"{stored:012d}", "as_of": result.as_of})
        if result.restatements_dropped:
            stored = len(self._restatements[tenant])
            self._restatements[tenant].append({
                "tenant_id": tenant, "principal_entity_id": "*", "agent_entity_id": "*",
                "change_kind": "row_log_capped", "before": None,
                "after": {"rows_not_logged": result.restatements_dropped},
                "id": f"{stored:012d}", "as_of": result.as_of,
            })

    async def summary(self, tenant_id: str, principal: str) -> Optional[dict[str, Any]]:
        found = self._summaries[tenant_id].get(principal)
        if found is None:
            return None
        return {**found, "reconciled_at": self._reconciled_at.get((tenant_id, principal))}

    async def list_rows(self, tenant_id, principal, filters, after, limit):
        keys = self._sorted.get((tenant_id, principal))
        store = self._rows[tenant_id][principal]
        if keys is None:
            keys = self._sorted[(tenant_id, principal)] = sorted(store)
        from bisect import bisect_right

        start = bisect_right(keys, after) if after is not None else 0
        out: list[dict[str, Any]] = []
        for index in range(start, len(keys)):
            row = store[keys[index]]
            if _row_matches(row, filters):
                out.append(row)
                if len(out) >= limit:
                    break
        return out

    async def list_clusters(self, tenant_id, principal, after, limit):
        clusters = sorted(
            self._clusters[tenant_id].get(principal, []),
            key=lambda c: (-c["member_count"], c["cluster_id"]),
        )
        if after is not None:
            clusters = [c for c in clusters if (-c["member_count"], c["cluster_id"]) > (-after[0], after[1])]
        return clusters[:limit]

    async def node(self, tenant_id, agent):
        return self._nodes[tenant_id].get(agent)

    async def nodes(self, tenant_id, agents):
        store = self._nodes[tenant_id]
        return {agent: store[agent] for agent in agents if agent in store}

    def _node_keys(self, tenant_id: str) -> list[str]:
        keys = self._sorted_nodes.get(tenant_id)
        if keys is None:
            keys = self._sorted_nodes[tenant_id] = sorted(self._nodes[tenant_id])
        return keys

    async def children(self, tenant_id, agent, after, limit):
        rows = sorted(
            (n for n in self._nodes[tenant_id].values()
             if n.get("parent_agent_id") == agent and (after is None or n["agent_entity_id"] > after)),
            key=lambda n: n["agent_entity_id"],
        )
        return rows[:limit]

    async def descendants(self, tenant_id, node, after, limit):
        prefix = node["path"] + PATH_SEP
        rows = sorted(
            (n for n in self._nodes[tenant_id].values()
             if n["path"].startswith(prefix) and (after is None or n["path"] > after)),
            key=lambda n: n["path"],
        )
        return rows[:limit]

    async def rows_for_agent(self, tenant_id, agent):
        out = []
        for principal in sorted(self._rows[tenant_id]):
            row = self._rows[tenant_id][principal].get(agent)
            if row is not None:
                out.append(row)
        return out

    async def restatements(self, tenant_id, principal, after, limit):
        out = []
        for entry in self._restatements[tenant_id]:
            if entry["principal_entity_id"] not in (principal, "*"):
                continue
            if after is not None and entry["id"] <= after:
                continue
            out.append(entry)
            if len(out) >= limit:
                break
        return out

    async def prior_rows(self, tenant_id: str) -> dict[tuple[str, str], dict[str, Any]]:
        return {
            (principal, agent): row
            for principal, rows in self._rows[tenant_id].items()
            for agent, row in rows.items()
        }

    async def erase_subject(self, tenant_id, refs):
        wanted = {str(value) for value in refs if value}
        self._generations[tenant_id] += 1
        rows = nodes = summaries = clusters = restatements = 0
        for principal in list(self._rows[tenant_id]):
            store = self._rows[tenant_id][principal]
            if principal in wanted:
                rows += len(store)
                del self._rows[tenant_id][principal]
                self._sorted.pop((tenant_id, principal), None)
                if self._summaries[tenant_id].pop(principal, None) is not None:
                    summaries += 1
                clusters += len(self._clusters[tenant_id].pop(principal, []))
                continue
            # A surviving row naming the subject as parent or root would carry that id into
            # the rebuild's restatement log, so it goes too. The rebuild restores what remains.
            doomed = wanted & set(store) | {
                agent for agent, row in store.items()
                if row.get("parent_agent_id") in wanted or row.get("root_agent_id") in wanted
            }
            for agent in doomed:
                del store[agent]
                rows += 1
                self._sorted.pop((tenant_id, principal), None)
        for agent in [
            agent for agent, node in self._nodes[tenant_id].items()
            if agent in wanted or node.get("parent_agent_id") in wanted or node.get("root_agent_id") in wanted
        ]:
            del self._nodes[tenant_id][agent]
            nodes += 1
        # Records about other subjects keep no trace of the erased one.
        for node in self._nodes[tenant_id].values():
            if wanted & set(node.get("principal_entity_ids") or ()):
                node["principal_entity_ids"] = [p for p in node["principal_entity_ids"] if p not in wanted]
        for store in self._rows[tenant_id].values():
            for row in store.values():
                if wanted & set(row.get("competing_principal_ids") or ()):
                    row["competing_principal_ids"] = [p for p in row["competing_principal_ids"] if p not in wanted]
        self._sorted_nodes.pop(tenant_id, None)
        kept = []
        for entry in self._restatements[tenant_id]:
            states = [entry.get("before") or {}, entry.get("after") or {}]
            if (
                entry["principal_entity_id"] in wanted or entry["agent_entity_id"] in wanted
                or any(state.get(field) in wanted for state in states for field in ("parent_agent_id", "root_agent_id"))
            ):
                restatements += 1
            else:
                kept.append(entry)
        self._restatements[tenant_id] = kept
        return {"rows": rows, "nodes": nodes, "summaries": summaries, "clusters": clusters,
                "restatements": restatements}


_UPSERT_BATCH = 2000


class PostgresLineageRepository:
    """Keyset-paged store over the ``principal_agent_lineage`` tables."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def erasure_generation(self, tenant_id: str) -> int:
        value = await self._pool.fetchval(
            "SELECT erasure_generation FROM agent_lineage_tenant_state WHERE tenant_id = $1", tenant_id,
        )
        return int(value or 0)

    async def apply(self, result: ResolveResult, *, expected_generation: Optional[int] = None) -> None:
        tenant = result.tenant_id
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                if expected_generation is not None:
                    # The row lock orders this write against a concurrent erasure.
                    await conn.execute(
                        "INSERT INTO agent_lineage_tenant_state (tenant_id) VALUES ($1) "
                        "ON CONFLICT (tenant_id) DO NOTHING",
                        tenant,
                    )
                    current = await conn.fetchval(
                        "SELECT erasure_generation FROM agent_lineage_tenant_state "
                        "WHERE tenant_id = $1 FOR UPDATE",
                        tenant,
                    )
                    if int(current) != expected_generation:
                        raise StaleLineageGeneration(tenant)
                await self._apply_rows(conn, tenant, result)
                await self._apply_nodes(conn, tenant, result)
                await self._apply_summaries(conn, tenant, result)
                await self._apply_restatements(conn, tenant, result)

    async def _apply_rows(self, conn: Any, tenant: str, result: ResolveResult) -> None:
        if result.rows_removed:
            await conn.executemany(
                "DELETE FROM principal_agent_lineage WHERE tenant_id = $1 AND principal_entity_id = $2 "
                "AND agent_entity_id = $3",
                [(tenant, principal, agent) for principal, agent in result.rows_removed],
            )
        for start in range(0, len(result.rows_upserted), _UPSERT_BATCH):
            batch = result.rows_upserted[start:start + _UPSERT_BATCH]
            await conn.executemany(
                """
                INSERT INTO principal_agent_lineage (
                    tenant_id, principal_entity_id, agent_entity_id, direct_or_indirect, attribution_class,
                    active_state, lineage_status, authority_status, depth, parent_agent_id, root_agent_id,
                    deployment_id, operator_entity_id, risk_signal_count, cluster_ids, data, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16::jsonb,NOW())
                ON CONFLICT (tenant_id, principal_entity_id, agent_entity_id) DO UPDATE SET
                    direct_or_indirect = EXCLUDED.direct_or_indirect,
                    attribution_class = EXCLUDED.attribution_class,
                    active_state = EXCLUDED.active_state,
                    lineage_status = EXCLUDED.lineage_status,
                    authority_status = EXCLUDED.authority_status,
                    depth = EXCLUDED.depth,
                    parent_agent_id = EXCLUDED.parent_agent_id,
                    root_agent_id = EXCLUDED.root_agent_id,
                    deployment_id = EXCLUDED.deployment_id,
                    operator_entity_id = EXCLUDED.operator_entity_id,
                    risk_signal_count = EXCLUDED.risk_signal_count,
                    cluster_ids = EXCLUDED.cluster_ids,
                    data = EXCLUDED.data,
                    updated_at = NOW()
                """,
                [(
                    tenant, row["principal_entity_id"], row["agent_entity_id"], row["direct_or_indirect"],
                    row["attribution_class"], row["active_state"], row["lineage_status"],
                    row.get("authority_resolution_status"), row["depth"], row.get("parent_agent_id"),
                    row.get("root_agent_id"), row.get("agent_deployment_id"), row.get("operator_entity_id"),
                    row.get("risk_signal_count"), row.get("cluster_ids") or [], json.dumps(row, default=str),
                ) for row in batch],
            )

    async def _apply_nodes(self, conn: Any, tenant: str, result: ResolveResult) -> None:
        if result.nodes_removed:
            await conn.execute(
                "DELETE FROM agent_lineage_nodes WHERE tenant_id = $1 AND agent_entity_id = ANY($2::text[])",
                tenant, result.nodes_removed,
            )
        for start in range(0, len(result.nodes_upserted), _UPSERT_BATCH):
            batch = result.nodes_upserted[start:start + _UPSERT_BATCH]
            await conn.executemany(
                """
                INSERT INTO agent_lineage_nodes (
                    tenant_id, agent_entity_id, parent_agent_id, root_agent_id, depth, path, data, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,NOW())
                ON CONFLICT (tenant_id, agent_entity_id) DO UPDATE SET
                    parent_agent_id = EXCLUDED.parent_agent_id,
                    root_agent_id = EXCLUDED.root_agent_id,
                    depth = EXCLUDED.depth,
                    path = EXCLUDED.path,
                    data = EXCLUDED.data,
                    updated_at = NOW()
                """,
                [(
                    tenant, node["agent_entity_id"], node.get("parent_agent_id"), node["root_agent_id"],
                    node["depth"], node["path"], json.dumps(node, default=str),
                ) for node in batch],
            )

    async def _apply_summaries(self, conn: Any, tenant: str, result: ResolveResult) -> None:
        if result.summaries_removed:
            await conn.execute(
                "DELETE FROM principal_agent_lineage_summary WHERE tenant_id = $1 "
                "AND principal_entity_id = ANY($2::text[])",
                tenant, result.summaries_removed,
            )
            await conn.execute(
                "DELETE FROM principal_agent_lineage_clusters WHERE tenant_id = $1 "
                "AND principal_entity_id = ANY($2::text[])",
                tenant, result.summaries_removed,
            )
        for summary in result.summaries:
            await conn.execute(
                """
                INSERT INTO principal_agent_lineage_summary (tenant_id, principal_entity_id, data, updated_at)
                VALUES ($1,$2,$3::jsonb,NOW())
                ON CONFLICT (tenant_id, principal_entity_id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                """,
                tenant, summary["principal_entity_id"], json.dumps(summary, default=str),
            )
        for principal, clusters in result.clusters.items():
            await conn.execute(
                "DELETE FROM principal_agent_lineage_clusters WHERE tenant_id = $1 AND principal_entity_id = $2",
                tenant, principal,
            )
            if clusters:
                await conn.executemany(
                    "INSERT INTO principal_agent_lineage_clusters "
                    "(tenant_id, principal_entity_id, cluster_id, member_count, data) "
                    "VALUES ($1,$2,$3,$4,$5::jsonb)",
                    [(tenant, principal, c["cluster_id"], c["member_count"], json.dumps(c, default=str))
                     for c in clusters],
                )

    async def _apply_restatements(self, conn: Any, tenant: str, result: ResolveResult) -> None:
        entries = [
            (tenant, e["principal_entity_id"], e["agent_entity_id"], e["change_kind"],
             json.dumps(e.get("before")), json.dumps(e.get("after")), result.as_of)
            for e in result.restatements
        ]
        if result.restatements_dropped:
            entries.append((
                tenant, "*", "*", "row_log_capped", json.dumps(None),
                json.dumps({"rows_not_logged": result.restatements_dropped}), result.as_of,
            ))
        if entries:
            await conn.executemany(
                "INSERT INTO agent_lineage_restatements "
                "(tenant_id, principal_entity_id, agent_entity_id, change_kind, before_state, after_state, as_of) "
                "VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7)",
                entries,
            )

    async def summary(self, tenant_id, principal):
        row = await self._pool.fetchrow(
            "SELECT data, updated_at FROM principal_agent_lineage_summary "
            "WHERE tenant_id = $1 AND principal_entity_id = $2",
            tenant_id, principal,
        )
        if row is None:
            return None
        return {**_json(row["data"]), "reconciled_at": row["updated_at"].isoformat()}

    async def list_rows(self, tenant_id, principal, filters, after, limit):
        clauses = ["tenant_id = $1", "principal_entity_id = $2"]
        args: list[Any] = [tenant_id, principal]

        def bind(sql: str, value: Any) -> None:
            args.append(value)
            clauses.append(sql.format(n=len(args)))

        columns = {
            "relationship": "direct_or_indirect", "attribution_class": "attribution_class",
            "active_state": "active_state", "lineage_status": "lineage_status",
            "deployment_id": "deployment_id", "operator_entity_id": "operator_entity_id",
            "authority_status": "authority_status", "parent_agent_id": "parent_agent_id",
            "root_agent_id": "root_agent_id",
        }
        for key, value in filters.items():
            if key in columns:
                bind(f"{columns[key]} = ${{n}}", value)
            elif key == "risk":
                clauses.append({
                    "flagged": "risk_signal_count > 0", "unflagged": "risk_signal_count = 0",
                    "unknown": "risk_signal_count IS NULL",
                }[value])
            elif key == "cluster_id":
                bind("cluster_ids @> ARRAY[${n}]::text[]", value)
            elif key == "min_depth":
                bind("depth >= ${n}", int(value))
            elif key == "max_depth":
                bind("depth <= ${n}", int(value))
        if after is not None:
            bind("agent_entity_id > ${n}", after)
        args.append(limit)
        rows = await self._pool.fetch(
            f"SELECT data FROM principal_agent_lineage WHERE {' AND '.join(clauses)} "
            f"ORDER BY agent_entity_id LIMIT ${len(args)}",
            *args,
        )
        return [_json(row["data"]) for row in rows]

    async def list_clusters(self, tenant_id, principal, after, limit):
        if after is None:
            rows = await self._pool.fetch(
                "SELECT data FROM principal_agent_lineage_clusters WHERE tenant_id = $1 AND principal_entity_id = $2 "
                "ORDER BY member_count DESC, cluster_id LIMIT $3",
                tenant_id, principal, limit,
            )
        else:
            rows = await self._pool.fetch(
                "SELECT data FROM principal_agent_lineage_clusters WHERE tenant_id = $1 AND principal_entity_id = $2 "
                "AND (member_count < $4 OR (member_count = $4 AND cluster_id > $3)) "
                "ORDER BY member_count DESC, cluster_id LIMIT $5",
                tenant_id, principal, after[1], after[0], limit,
            )
        return [_json(row["data"]) for row in rows]

    async def node(self, tenant_id, agent):
        row = await self._pool.fetchrow(
            "SELECT data FROM agent_lineage_nodes WHERE tenant_id = $1 AND agent_entity_id = $2",
            tenant_id, agent,
        )
        return _json(row["data"]) if row else None

    async def nodes(self, tenant_id, agents):
        rows = await self._pool.fetch(
            "SELECT data FROM agent_lineage_nodes WHERE tenant_id = $1 AND agent_entity_id = ANY($2::text[])",
            tenant_id, list(agents),
        )
        found = [_json(row["data"]) for row in rows]
        return {node["agent_entity_id"]: node for node in found}

    async def children(self, tenant_id, agent, after, limit):
        rows = await self._pool.fetch(
            "SELECT data FROM agent_lineage_nodes WHERE tenant_id = $1 AND parent_agent_id = $2 "
            "AND ($3::text IS NULL OR agent_entity_id > $3) ORDER BY agent_entity_id LIMIT $4",
            tenant_id, agent, after, limit,
        )
        return [_json(row["data"]) for row in rows]

    async def descendants(self, tenant_id, node, after, limit):
        # Range scan on the materialized path; the bounds are binary, so no
        # LIKE escaping can widen it.
        lower = node["path"] + PATH_SEP
        upper = node["path"] + chr(ord(PATH_SEP) + 1)
        rows = await self._pool.fetch(
            "SELECT data FROM agent_lineage_nodes WHERE tenant_id = $1 AND path COLLATE \"C\" > $2 "
            "AND path COLLATE \"C\" < $3 ORDER BY path COLLATE \"C\" LIMIT $4",
            tenant_id, after if after is not None and after > lower else lower, upper, limit,
        )
        return [_json(row["data"]) for row in rows]

    async def rows_for_agent(self, tenant_id, agent):
        rows = await self._pool.fetch(
            "SELECT data FROM principal_agent_lineage WHERE tenant_id = $1 AND agent_entity_id = $2 "
            "ORDER BY principal_entity_id LIMIT 200",
            tenant_id, agent,
        )
        return [_json(row["data"]) for row in rows]

    async def restatements(self, tenant_id, principal, after, limit):
        rows = await self._pool.fetch(
            "SELECT id, tenant_id, principal_entity_id, agent_entity_id, change_kind, before_state, after_state, as_of "
            "FROM agent_lineage_restatements WHERE tenant_id = $1 AND principal_entity_id IN ($2, '*') "
            "AND ($3::bigint IS NULL OR id > $3) ORDER BY id LIMIT $4",
            tenant_id, principal, int(after) if after else None, limit,
        )
        return [{
            "id": str(row["id"]), "tenant_id": row["tenant_id"],
            "principal_entity_id": row["principal_entity_id"], "agent_entity_id": row["agent_entity_id"],
            "change_kind": row["change_kind"], "before": _json(row["before_state"]),
            "after": _json(row["after_state"]), "as_of": row["as_of"],
        } for row in rows]

    async def prior_rows(self, tenant_id: str) -> dict[tuple[str, str], dict[str, Any]]:
        out: dict[tuple[str, str], dict[str, Any]] = {}
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                async for row in conn.cursor(
                    "SELECT principal_entity_id, agent_entity_id, data FROM principal_agent_lineage WHERE tenant_id = $1",
                    tenant_id,
                ):
                    out[(row["principal_entity_id"], row["agent_entity_id"])] = _json(row["data"])
        return out

    async def erase_subject(self, tenant_id, refs):
        wanted = sorted({str(value) for value in refs if value})
        if not tenant_id:
            raise ValueError("erase_subject requires a tenant_id")
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Bumped even with nothing to delete: evidence may have just been erased.
                await conn.execute(
                    "INSERT INTO agent_lineage_tenant_state (tenant_id, erasure_generation) VALUES ($1, 1) "
                    "ON CONFLICT (tenant_id) DO UPDATE SET "
                    "erasure_generation = agent_lineage_tenant_state.erasure_generation + 1",
                    tenant_id,
                )
                rows = await conn.execute(
                    "DELETE FROM principal_agent_lineage WHERE tenant_id = $1 "
                    "AND (principal_entity_id = ANY($2::text[]) OR agent_entity_id = ANY($2::text[]) "
                    "OR parent_agent_id = ANY($2::text[]) OR root_agent_id = ANY($2::text[]))",
                    tenant_id, wanted,
                )
                nodes = await conn.execute(
                    "DELETE FROM agent_lineage_nodes WHERE tenant_id = $1 AND (agent_entity_id = ANY($2::text[]) "
                    "OR parent_agent_id = ANY($2::text[]) OR root_agent_id = ANY($2::text[]))",
                    tenant_id, wanted,
                )
                summaries = await conn.execute(
                    "DELETE FROM principal_agent_lineage_summary WHERE tenant_id = $1 "
                    "AND principal_entity_id = ANY($2::text[])",
                    tenant_id, wanted,
                )
                clusters = await conn.execute(
                    "DELETE FROM principal_agent_lineage_clusters WHERE tenant_id = $1 "
                    "AND principal_entity_id = ANY($2::text[])",
                    tenant_id, wanted,
                )
                restatements = await conn.execute(
                    "DELETE FROM agent_lineage_restatements WHERE tenant_id = $1 "
                    "AND (principal_entity_id = ANY($2::text[]) OR agent_entity_id = ANY($2::text[]) "
                    "OR before_state->>'parent_agent_id' = ANY($2::text[]) "
                    "OR before_state->>'root_agent_id' = ANY($2::text[]) "
                    "OR after_state->>'parent_agent_id' = ANY($2::text[]) "
                    "OR after_state->>'root_agent_id' = ANY($2::text[]))",
                    tenant_id, wanted,
                )
                # Records about other subjects keep no trace of the erased one.
                await conn.execute(
                    """
                    UPDATE agent_lineage_nodes SET data = jsonb_set(data, '{principal_entity_ids}', (
                        SELECT COALESCE(jsonb_agg(item), '[]'::jsonb)
                        FROM jsonb_array_elements_text(data->'principal_entity_ids') AS item
                        WHERE item <> ALL($2::text[])
                    ))
                    WHERE tenant_id = $1 AND data->'principal_entity_ids' ?| $2::text[]
                    """,
                    tenant_id, wanted,
                )
                await conn.execute(
                    """
                    UPDATE principal_agent_lineage SET data = jsonb_set(data, '{competing_principal_ids}', (
                        SELECT COALESCE(jsonb_agg(item), '[]'::jsonb)
                        FROM jsonb_array_elements_text(data->'competing_principal_ids') AS item
                        WHERE item <> ALL($2::text[])
                    ))
                    WHERE tenant_id = $1 AND data->'competing_principal_ids' ?| $2::text[]
                    """,
                    tenant_id, wanted,
                )
        return {
            "rows": _affected(rows), "nodes": _affected(nodes), "summaries": _affected(summaries),
            "clusters": _affected(clusters), "restatements": _affected(restatements),
        }


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _affected(status: str) -> int:
    try:
        return int(str(status).rsplit(" ", 1)[-1])
    except ValueError:
        return 0
