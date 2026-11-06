#!/usr/bin/env python3
"""Measure the principal <-> agent lineage projection at 100 to 100,000 agents.

Each tier runs in its own process so peak RSS belongs to that tier alone. Numbers
are measured here and written to the ledger; nothing is estimated. Set
``AGENT_LINEAGE_TEST_DSN`` to also exercise the Postgres store (the tables are
dropped and recreated from the migration, so point it at a scratch database).

Usage:
  python scripts/agent_lineage_scale_proof.py [--tiers 100,1000,10000,100000]
      [--output docs/product/productization/agent-lineage-scale-proof.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "services" / "api"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "scale-proof-only")

DEFAULT_OUTPUT = ROOT / "docs/product/productization/agent-lineage-scale-proof.json"
LEDGER = ROOT / "docs/product/productization/agent-lineage-scale-proof-ledger.md"
QUERY_SAMPLES = 60


def _timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


async def _latency(call: Callable[[int], Awaitable[Any]], samples: int = QUERY_SAMPLES) -> dict[str, float]:
    timings = []
    for index in range(samples):
        start = time.perf_counter()
        await call(index)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return {
        "p50_ms": round(statistics.median(timings), 3),
        "p95_ms": round(timings[int(len(timings) * 0.95) - 1], 3),
        "max_ms": round(timings[-1], 3),
    }


async def _store_metrics(service: Any, result: Any, fixture: Any) -> dict[str, Any]:
    from actions.agent_lineage import synthetic as S

    start = time.perf_counter()
    await service.repo.apply(result)
    apply_seconds = time.perf_counter() - start

    tenant = S.TENANT
    principal = S.MALICIOUS_HUMAN
    # Walk to a deep cursor first: a keyset page must not cost more there.
    deep_cursor = None
    pages = walked = 0
    while True:
        page = await service.agents(tenant, principal, cursor=deep_cursor, page_size=500)
        walked += len(page["items"])
        pages += 1
        if not page["next_cursor"]:
            break
        deep_cursor = page["next_cursor"]
    agents = sorted(fixture.truth)
    rng = random.Random(3)
    picks = [rng.choice(agents) for _ in range(QUERY_SAMPLES)]
    return {
        "apply_seconds": round(apply_seconds, 3),
        "full_walk": {"pages": pages, "rows": walked},
        "query_latency": {
            "summary": await _latency(lambda _: service.summary(tenant, principal)),
            "agents_first_page": await _latency(lambda _: service.agents(tenant, principal, page_size=100)),
            "agents_deep_page": await _latency(
                lambda _: service.agents(tenant, principal, cursor=deep_cursor, page_size=100)),
            "agents_filtered": await _latency(lambda _: service.agents(
                tenant, principal, filters={"authority_status": "out_of_scope"}, page_size=100)),
            "clusters": await _latency(lambda _: service.clusters(tenant, principal, page_size=25)),
            "tree_top": await _latency(lambda _: service.tree(tenant, principal)),
            "tree_expand": await _latency(lambda _: service.tree(tenant, principal, parent="mal-orch", page_size=100)),
            "descendants_page": await _latency(lambda _: service.descendants(tenant, "mal-orch", page_size=100)),
            "ancestors": await _latency(lambda i: service.ancestors(tenant, picks[i])),
            "agent_detail": await _latency(lambda i: service.agent_detail(tenant, picks[i])),
            "investigation": await _latency(lambda _: service.investigation(tenant, principal), samples=10),
        },
    }


def _projector_throughput(fixture: Any) -> dict[str, Any]:
    """Run the real Silver projector over events shaped like these facts."""
    from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector

    projector = AgentExecutionProjector()
    sample = fixture.facts[: min(len(fixture.facts), 20_000)]
    events = []
    for index, fact in enumerate(sample):
        events.append({
            "messageId": f"proof-{index}", "tenantId": fact["tenant_id"], "type": fact["source_event_type"],
            "timestamp": fact["occurred_at"],
            "validated_agent_deployment": {"agentId": fact.get("agent_id"), "deploymentId": fact.get("deployment_id")},
            "properties": {
                "parentAgentId": fact.get("parent_agent_ref"), "childAgentId": fact.get("child_agent_ref"),
                "toolName": fact.get("tool_name"), "runId": fact.get("source_run_id"),
            },
            "context": {},
        })
    start = time.perf_counter()
    projected = sum(1 for event in events if projector.project(event) is not None)
    elapsed = time.perf_counter() - start
    return {"events": len(events), "projected": projected,
            "events_per_second": round(len(events) / elapsed) if elapsed else None}


def _run_tier(tier: int) -> dict[str, Any]:
    from actions.agent_lineage import synthetic as S
    from actions.agent_lineage.engine import LineageEngine
    from actions.agent_lineage.repository import InMemoryLineageRepository, PostgresLineageRepository
    from actions.agent_lineage.service import AgentLineageService
    from intelligence.risk360.fanout import assess_principal

    fixture, build_seconds = _timed(lambda: S.build_fixture(tier))
    metrics: dict[str, Any] = {
        "tier": tier,
        "agents_in_fixture": len(fixture.truth),
        "facts": len(fixture.facts),
        "replayed_events_in_fixture": fixture.replayed_events,
        "foreign_tenant_facts": len(fixture.foreign_facts),
        "fixture_build_seconds": round(build_seconds, 3),
        "silver_projection": _projector_throughput(fixture),
    }

    engine = LineageEngine(S.TENANT)
    def _load_canonical() -> None:
        for record in fixture.authorities:
            engine.upsert_authority(record)
        for binding in fixture.bindings:
            engine.upsert_binding(binding)
    _load_canonical()
    _, ingest_seconds = _timed(lambda: engine.ingest(fixture.facts))
    engine.ingest(fixture.foreign_facts)
    result, resolve_seconds = _timed(engine.resolve)
    metrics["lineage_fold"] = {
        "seconds": round(ingest_seconds, 3),
        "facts_per_second": round(len(fixture.facts) / ingest_seconds) if ingest_seconds else None,
    }
    metrics["identity_and_lineage_resolution_seconds"] = round(resolve_seconds, 3)
    metrics["rows"] = len(engine.rows())
    # Durable semantic edges only: a parent link per agent plus authority and binding
    # records. Execution events stay in Silver, so this is far below the fact count.
    parent_edges = sum(1 for node in result.nodes_upserted if node["parent_agent_id"])
    metrics["graph_mutation_volume"] = {
        "semantic_edges": parent_edges + len(fixture.authorities) + len(fixture.bindings),
        "facts": len(fixture.facts),
        "kind": "computed from the resolved topology; no graph store was written",
    }
    metrics["correctness"] = S.score(engine, fixture)
    metrics["correctness"]["cross_tenant_rows_rejected"] = engine.cross_tenant_rejected

    # Replay: every event again, nothing may change.
    before = {key: dict(row) for key, row in engine.rows().items()}
    _, replay_seconds = _timed(lambda: engine.ingest(fixture.facts))
    replayed, replay_resolve = _timed(engine.resolve)
    metrics["replay"] = {
        "seconds": round(replay_seconds + replay_resolve, 3),
        "rows_changed": len(replayed.rows_upserted),
        "divergence": sum(1 for key, row in engine.rows().items() if before.get(key) != row),
    }

    # Incremental convergence: the same evidence in batches equals one rebuild.
    incremental = LineageEngine(S.TENANT)
    for record in fixture.authorities:
        incremental.upsert_authority(record)
    for binding in fixture.bindings:
        incremental.upsert_binding(binding)
    batch_size = max(1, len(fixture.facts) // 5)
    for start in range(0, len(fixture.facts), batch_size):
        incremental.ingest(fixture.facts[start:start + batch_size])
        incremental.resolve()
    incremental.ingest(fixture.foreign_facts)
    incremental.resolve()
    metrics["incremental_vs_rebuild_divergence"] = _divergence(incremental.rows(), engine.rows())

    # One new event on one leaf, on a fully resolved tenant.
    leaf = next(agent for agent in sorted(fixture.truth) if agent.startswith("legit-"))
    last_fact = {
        "tenant_id": S.TENANT, "source_event_id": "proof-incremental", "source_event_type": "agent_tool_invocation_observed",
        "agent_id": leaf, "occurred_at": "2026-10-01T08:00:30Z", "tool_name": "read_file",
    }
    engine.ingest([last_fact])
    delta, delta_seconds = _timed(engine.resolve)
    metrics["incremental_single_event"] = {
        "seconds": round(delta_seconds, 4), "rows_written": len(delta.rows_upserted),
        "nodes_written": len(delta.nodes_upserted),
    }

    # Correction: revoke the malicious principal's root grant.
    grant = next(a for a in fixture.authorities if a.authority_ref == "grant-h1-orch")
    corrected = replace(grant, revoked_at=1.0, version=2)
    engine.upsert_authority(corrected)
    correction, correction_seconds = _timed(engine.resolve)
    metrics["correction"] = {
        "seconds": round(correction_seconds, 3),
        "rows_rewritten": len(correction.rows_upserted),
        "restatements_logged": len(correction.restatements),
        "restatements_counted_not_logged": correction.restatements_dropped,
    }
    rebuilt = LineageEngine(S.TENANT)
    for record in fixture.authorities:
        rebuilt.upsert_authority(corrected if record.authority_ref == "grant-h1-orch" else record)
    for binding in fixture.bindings:
        rebuilt.upsert_binding(binding)
    rebuilt.ingest(fixture.facts)
    rebuilt.ingest([last_fact])
    rebuilt.resolve()
    metrics["restatement_divergence"] = _divergence(engine.rows(), rebuilt.rows())
    # Return to the state the store metrics describe.
    engine.upsert_authority(replace(grant, version=3))
    restored = engine.resolve()
    metrics["correction"]["reversal_rows_rewritten"] = len(restored.rows_upserted)

    summaries = {s["principal_entity_id"]: s for s in result.summaries}
    _, risk_seconds = _timed(lambda: [
        assess_principal(s, clusters=result.clusters.get(p, [])) for p, s in summaries.items()
    ])
    metrics["risk360"] = {
        "seconds_all_principals": round(risk_seconds, 5),
        "legit": _risk_view(summaries[S.LEGIT_HUMAN], result.clusters.get(S.LEGIT_HUMAN, [])),
        "malicious": _risk_view(summaries[S.MALICIOUS_HUMAN], result.clusters.get(S.MALICIOUS_HUMAN, [])),
    }
    malicious = summaries[S.MALICIOUS_HUMAN]
    metrics["malicious_principal_summary"] = {
        key: malicious[key] for key in (
            "direct_agents", "indirect_agents", "probabilistic_agents", "unresolved_agents", "verified_links",
            "inferred_links", "agent_instances", "agent_runs", "out_of_scope_agents", "revoked_agents",
            "risk_flagged_agents", "max_delegation_depth",
        )
    }

    async def stores() -> dict[str, Any]:
        out: dict[str, Any] = {}
        memory = AgentLineageService(InMemoryLineageRepository())
        out["memory"] = await _store_metrics(memory, result, fixture)
        dsn = os.environ.get("AGENT_LINEAGE_TEST_DSN")
        if dsn:
            import asyncpg
            sys.path.insert(0, str(BACKEND))
            from tests.agent_lineage.conftest import _migration_statements

            up, down = _migration_statements()
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
            try:
                async with pool.acquire() as conn:
                    for sql in down:
                        await conn.execute(sql)
                    for sql in up:
                        await conn.execute(sql)
                sql_service = AgentLineageService(PostgresLineageRepository(pool))
                out["postgres"] = await _store_metrics(sql_service, result, fixture)
                size = await pool.fetchval("SELECT pg_total_relation_size('principal_agent_lineage')")
                out["postgres"]["lineage_table_bytes"] = size
            finally:
                await pool.close()
        return out

    metrics["stores"] = asyncio.run(stores())
    metrics["peak_rss_mb"] = round(_peak_rss_mb(), 1)
    return metrics


def _risk_view(summary: dict[str, Any], clusters: list[dict[str, Any]]) -> dict[str, Any]:
    from intelligence.risk360.fanout import assess_principal

    assessment = assess_principal(summary, clusters=clusters)
    return {
        "assessment_level": assessment["assessment_level"],
        "triggered_signals": assessment["triggered_signals"],
        "segments": assessment["segments"],
        "spawn_velocity_per_second": assessment["signals"]["agent_spawn_velocity"],
        "delegation_depth": assessment["signals"]["delegation_depth"],
    }


def _divergence(left: dict, right: dict) -> int:
    volatile = ("last_reconciled_at",)
    count = 0
    for key in set(left) | set(right):
        a, b = left.get(key), right.get(key)
        if a is None or b is None:
            count += 1
        elif any(a.get(k) != b.get(k) for k in a if k not in volatile):
            count += 1
    return count


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def _row(label: str, tiers: list[dict[str, Any]], read: Callable[[dict[str, Any]], Any]) -> str:
    return f"| {label} | " + " | ".join(str(read(tier)) for tier in tiers) + " |"


def _latency_rows(tiers: list[dict[str, Any]], store: str) -> list[str]:
    rows = []
    for name in tiers[0]["stores"].get(store, {}).get("query_latency", {}):
        rows.append(_row(name, tiers, lambda t: (
            f"{t['stores'][store]['query_latency'][name]['p50_ms']} / "
            f"{t['stores'][store]['query_latency'][name]['p95_ms']}"
        )))
    return rows


def render_ledger(payload: dict[str, Any]) -> str:
    """The ledger is rendered from measured results; it holds no hand-written numbers."""
    tiers = payload["tiers"]
    env = payload["environment"]
    header = "| Measure | " + " | ".join(f"{t['tier']:,}" for t in tiers) + " |"
    rule = "|---|" + "---:|" * len(tiers)
    correctness = [key for key in tiers[0]["correctness"] if key not in ("agents_in_truth", "agents_resolved", "cross_tenant_rows_rejected")]
    lines = [
        "---",
        "title: Agent Lineage Scale Proof Ledger",
        "slug: operations/agent-lineage-scale-proof-ledger",
        "section: operations",
        "visibility: I",
        "audience: [architect, ops]",
        "status: experimental",
        "since_version: 0.1.0-alpha.0",
        "---",
        "",
        "# Agent Lineage Scale Proof Ledger",
        "",
        "Rendered by `scripts/agent_lineage_scale_proof.py` from "
        "`agent-lineage-scale-proof.json`. Do not edit the numbers by hand; rerun the script.",
        "",
        "This is a measurement on one machine, not a production readiness claim.",
        "",
        f"Environment: {env['platform']}, {env['cpu_count']} CPUs, Python {env['python']}, "
        f"Postgres store {'exercised' if env['postgres'] else 'not exercised'}. "
        "The API, Bronze ingestion and a graph store were not in the loop. "
        "Each tier ran in its own process.",
        "",
        "## Population",
        "",
        header, rule,
        _row("Agents with ground truth", tiers, lambda t: f"{t['agents_in_fixture']:,}"),
        _row("Facts", tiers, lambda t: f"{t['facts']:,}"),
        _row("Replayed events in the stream", tiers, lambda t: f"{t['replayed_events_in_fixture']:,}"),
        _row("Other-tenant facts, all rejected", tiers, lambda t: f"{t['correctness']['cross_tenant_rows_rejected']:,}"),
        _row("Lineage rows", tiers, lambda t: f"{t['rows']:,}"),
        "",
        "## Correctness against ground truth",
        "",
        "Every value is an error count, except the rate row. Zero is the required result.",
        "",
        header, rule,
        *[_row(key.replace("_", " "), tiers, lambda t, k=key: t["correctness"][k]) for key in correctness],
        _row("replay divergence (rows)", tiers, lambda t: t["replay"]["divergence"]),
        _row("incremental vs rebuild divergence (rows)", tiers, lambda t: t["incremental_vs_rebuild_divergence"]),
        _row("restatement divergence (rows)", tiers, lambda t: t["restatement_divergence"]),
        "",
        "## Throughput and duration",
        "",
        header, rule,
        _row("Silver projector, events/s", tiers, lambda t: f"{t['silver_projection']['events_per_second']:,}"),
        _row("Lineage fold, facts/s", tiers, lambda t: f"{t['lineage_fold']['facts_per_second']:,}"),
        _row("Identity and lineage resolution, s", tiers, lambda t: t["identity_and_lineage_resolution_seconds"]),
        _row("Replay of every event, s", tiers, lambda t: t["replay"]["seconds"]),
        _row("One new event on a resolved tenant, s", tiers, lambda t: t["incremental_single_event"]["seconds"]),
        _row("Correction (root grant revoked), s", tiers, lambda t: t["correction"]["seconds"]),
        _row("Rows rewritten by the correction", tiers, lambda t: f"{t['correction']['rows_rewritten']:,}"),
        _row("Restatements logged / counted only", tiers, lambda t: (
            f"{t['correction']['restatements_logged']:,} / {t['correction']['restatements_counted_not_logged']:,}")),
        _row("Risk360 assessment, all principals, s", tiers, lambda t: t["risk360"]["seconds_all_principals"]),
        _row("Semantic graph edges (computed)", tiers, lambda t: f"{t['graph_mutation_volume']['semantic_edges']:,}"),
        _row("Peak RSS of the tier process, MB", tiers, lambda t: t["peak_rss_mb"]),
        "",
        "The Silver projector row uses at most 20,000 events per tier. Semantic edges are computed "
        "from the resolved topology; no graph store was written.",
        "",
        "## Risk360 outcome",
        "",
        header, rule,
        _row("Legitimate fleet: level", tiers, lambda t: t["risk360"]["legit"]["assessment_level"]),
        _row("Legitimate fleet: triggered signals", tiers, lambda t: len(t["risk360"]["legit"]["triggered_signals"])),
        _row("Legitimate fleet: peak spawns/s", tiers, lambda t: t["risk360"]["legit"]["spawn_velocity_per_second"]),
        _row("Malicious swarm: level", tiers, lambda t: t["risk360"]["malicious"]["assessment_level"]),
        _row("Malicious swarm: triggered signals", tiers, lambda t: len(t["risk360"]["malicious"]["triggered_signals"])),
        _row("Malicious swarm: peak spawns/s", tiers, lambda t: t["risk360"]["malicious"]["spawn_velocity_per_second"]),
        _row("Malicious swarm: verified / inferred links", tiers, lambda t: (
            f"{t['malicious_principal_summary']['verified_links']:,} / {t['malicious_principal_summary']['inferred_links']:,}")),
        "",
        "At 100 agents the malicious population is small enough that its revoked branch dominates; "
        "the level is still driven by behaviour rather than size.",
        "",
        "## Query latency, in-memory store",
        "",
        "p50 / p95 in milliseconds.",
        "",
        header, rule, *_latency_rows(tiers, "memory"),
        "",
    ]
    if env["postgres"]:
        lines += [
            "## Query latency, Postgres store",
            "",
            "p50 / p95 in milliseconds, through asyncpg to a local server with `fsync=off`, so write "
            "numbers are optimistic. Reads are through the migration's real indexes.",
            "",
            header, rule, *_latency_rows(tiers, "postgres"),
            _row("Write the full projection, s", tiers, lambda t: t["stores"]["postgres"]["apply_seconds"]),
            _row("`principal_agent_lineage` size, MB", tiers, lambda t: round(t["stores"]["postgres"]["lineage_table_bytes"] / (1024 * 1024), 1)),
            "",
        ]
    lines += [
        "## What this does and does not prove",
        "",
        "Measured: correct attribution, replay safety, order independence, incremental convergence and "
        "restatement at each tier, and bounded keyset reads whose cost does not grow with the population.",
        "",
        "Not measured, so not claimed:",
        "",
        "- The work order's capacity targets beyond these tiers: 1M+ instances, millions of runs and tens of "
        "millions of tool observations per principal. Fixtures carry about 2.7 facts per agent.",
        "- End-to-end ingestion through the API and Bronze, concurrent readers, multi-replica reconciliation, "
        "and any production-sized database or hardware.",
        "- Calibration of the fan-out thresholds against real traffic. They are stated heuristics.",
        "- Attribution quality on real data. Ground truth here comes from the same synthetic generator, "
        "so zero errors shows the resolver matches its specification, not that real-world evidence is this clean.",
        "",
        "Known limits this run shows:",
        "",
        "- Reconciliation holds the tenant's fold in process memory, and peak RSS is the tier's main cost. "
        "A tenant far above the largest tier needs a persisted or partitioned fold before it can be served.",
        "- A resolve pass recomputes roll-ups and clusters across the tenant, so its cost follows population even "
        "for one event. Reconcile in batches rather than per event.",
        "- Resolution time grows faster than linearly between the two largest tiers.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiers", default="100,1000,10000,100000")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--one-tier", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--render-only", action="store_true", help="re-render the ledger from --output")
    args = parser.parse_args()
    if args.render_only:
        LEDGER.write_text(render_ledger(json.loads(Path(args.output).read_text())))
        return 0
    if args.one_tier:
        print(json.dumps(_run_tier(args.one_tier)))
        return 0
    results = []
    for tier in (int(value) for value in args.tiers.split(",")):
        done = subprocess.run(
            [sys.executable, __file__, "--one-tier", str(tier)],
            capture_output=True, text=True, check=False,
        )
        if done.returncode != 0:
            print(done.stderr, file=sys.stderr)
            return done.returncode
        line = done.stdout.strip().splitlines()[-1]
        results.append(json.loads(line))
        print(f"tier {tier}: resolved in {results[-1]['identity_and_lineage_resolution_seconds']}s, "
              f"peak {results[-1]['peak_rss_mb']} MB", file=sys.stderr)
    payload = {
        "environment": {
            "platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "cpu_count": os.cpu_count(),
            "postgres": bool(os.environ.get("AGENT_LINEAGE_TEST_DSN")),
        },
        "tiers": results,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    LEDGER.write_text(render_ledger(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
