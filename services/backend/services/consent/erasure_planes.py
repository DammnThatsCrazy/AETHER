"""Per-store erasure executors for the ``consent.erasure`` job (DSR completeness).

Before this module, fifteen ``DSR_COMPONENTS`` were seeded ``pending`` on every
erasure request but nothing executed them, so a real DSR could never roll up to
``completed`` — and the subject data in those stores silently survived. Silver
fact tables and the hash-chained Bronze tier had no component at all.

Every executor here follows the erasure job's evidence contract
(``services/consent/erasure_jobs.py``):

* it touches ONLY the store(s) its component names, every statement carries the
  request's ``tenant_id`` (``delete_for_tenant_where`` refuses an empty tenant),
  and a retry is idempotent (a second run erases nothing and reports 0);
* it returns a :class:`Receipt` per component — the store's OWN counts, never a
  fabricated total — and the job marks each component with it;
* where a store is retained by policy (legal retention) the receipt says so
  (``skipped_legal_hold`` + the policy pointer); where the erasure needs a human
  decision it says so (``requires_manual_review`` + ``requires_retrain``); where
  the component has no backing store in this codebase the zero receipt names the
  proof (``policy_decision_id``) and a test pins that no store exists.

Subject resolution (:func:`resolve_subject`) runs once per attempt, BEFORE any
identity store is touched: the DSR's ``user_id`` and ``anonymous_id`` are looked
up in ``identity_aliases`` (``user_id`` / ``anonymous_id`` signals are stored
un-hashed) to find the canonical entity ids that represent the subject, plus
merge tombstones folded into those entities. The identity planes that destroy
this mapping (``identity_aliases`` / ``identity_subjects`` / ``graph_edges``)
run LAST and only when every entity-keyed plane succeeded in the same attempt,
so a retry can always re-resolve the subject.

Component → store map (see ``docs/privacy/dsr-erasure-coverage.md``):

  identity_aliases         identity_aliases + identity_signal_observations (hard delete)
  identity_subjects        identity_subjects + identity_clusters_v2 + identity_clusters
                           + entities (hard delete)
  graph_edges              identity_edges rows (hard delete) + graph-store edges
                           incident to the subject's vertices (governed soft-revoke
                           through GraphMutationGateway; the append-only mutation
                           ledger is preserve)
  profile360_snapshots     profiles + behavior_profiles + journey_chains (hard delete)
  feature_rows             lake Gold ``gold_*`` per-entity rows + the ML feature cache
  training_datasets        no backend store (offline ``services/ml`` plane); evidence =
                           training-eligible Gold rows erased + dsr_artifact_index
  model_artifacts          no backend store (artifact root / registry are offline);
                           evidence = dsr_artifact_index
  prediction_drift_buffers per-subject prediction cache entries (the only
                           backend-resident prediction buffer; drift monitoring
                           consumes offline DataFrames)
  exports                  export_artifacts (non-audit) whose rows name the subject
                           → content purged (tombstone) + mirrored egress objects
  audit_exports            export_artifacts of type ``audit_log`` → same purge; the
                           audit ledger itself is preserve (not an export)
  cached_tenant_views      tenant graph query/facet/replay caches, analytics query
                           cache, per-subject profile and consent caches
  replay_bundles           event_envelopes rows (+ the process hot cache)
  reward_decisions         reward_eligibility_decisions — legal retention
                           (``preserve``) → ``skipped_legal_hold`` with the count
  connector_derived_records comms_provider_identities (tombstone) + source_identities
                           + identity_claims (hard delete)
  financial_value_snapshots derivatives_pnl_snapshots of the subject's trading
                           accounts (hard delete); the value_* / valuation snapshot
                           stores carry no subject key (asset-level)
  silver_facts             every Silver fact table via the writer's introspected
                           schemas (typed columns and lake JSONB) — hard delete
  bronze_events            bronze_sdk_events: chain-preserving tombstone (+ re-pack
                           of externalized objects) and event_outbox payload
                           redaction; the hash chains still verify
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.consent.erasure_planes")

# ── Component names (must match dsr_propagation.models.DSR_COMPONENTS) ───────

IDENTITY_ALIASES_COMPONENT = "identity_aliases"
IDENTITY_SUBJECTS_COMPONENT = "identity_subjects"
GRAPH_EDGES_COMPONENT = "graph_edges"
PROFILE360_COMPONENT = "profile360_snapshots"
FEATURE_ROWS_COMPONENT = "feature_rows"
TRAINING_DATASETS_COMPONENT = "training_datasets"
MODEL_ARTIFACTS_COMPONENT = "model_artifacts"
PREDICTION_BUFFERS_COMPONENT = "prediction_drift_buffers"
EXPORTS_COMPONENT = "exports"
AUDIT_EXPORTS_COMPONENT = "audit_exports"
CACHED_VIEWS_COMPONENT = "cached_tenant_views"
REPLAY_BUNDLES_COMPONENT = "replay_bundles"
REWARD_DECISIONS_COMPONENT = "reward_decisions"
CONNECTOR_RECORDS_COMPONENT = "connector_derived_records"
FINANCIAL_SNAPSHOTS_COMPONENT = "financial_value_snapshots"
SILVER_FACTS_COMPONENT = "silver_facts"
BRONZE_EVENTS_COMPONENT = "bronze_events"

ERASURE_ACTOR = "dsr_erasure_job"
ERASURE_REASON = "dsr_erasure"

# Export types whose artifacts are audit exports (the ``/v1/audit/exports``
# reader behind the canonical ``audit_log`` exporter).
AUDIT_EXPORT_TYPES = frozenset({"audit_log"})

# Policy pointers recorded as ``policy_decision_id`` evidence.
POLICY_REWARD_RETENTION = "storage_policy:reward_eligibility_decisions:legal/preserve"
POLICY_NO_TRAINING_STORE = "dsr_policy:training_datasets:offline_ml_plane"
POLICY_NO_MODEL_STORE = "dsr_policy:model_artifacts:offline_ml_plane"

# Artifact-index kinds that mark an offline ML artifact embedding the subject.
TRAINING_DATASET_KINDS = frozenset({"training_dataset", "training_datasets"})
MODEL_ARTIFACT_KINDS = frozenset({"model_artifact", "model_artifacts"})

_PAGE = 500


# ═══════════════════════════════════════════════════════════════════════════
# Receipts + subject
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class Receipt:
    """One component's evidence, marked verbatim by the erasure job."""

    status: str = "completed"
    records_impacted: int = 0
    artifacts_impacted: int = 0
    requires_retrain: bool = False
    requires_recompute: bool = False
    policy_decision_id: Optional[str] = None
    blocked_reason: Optional[str] = None
    detail: dict[str, int] = field(default_factory=dict)

    def evidence(self) -> dict[str, Any]:
        """The ``mark_step`` evidence kwargs (``detail`` is log-only)."""
        out: dict[str, Any] = {
            "records_impacted": int(self.records_impacted),
            "artifacts_impacted": int(self.artifacts_impacted),
            "requires_retrain": bool(self.requires_retrain),
            "requires_recompute": bool(self.requires_recompute),
        }
        if self.policy_decision_id:
            out["policy_decision_id"] = self.policy_decision_id
        if self.blocked_reason:
            out["blocked_reason"] = self.blocked_reason
        return out


@dataclass(frozen=True)
class ErasureSubject:
    """Every identifier that names one data subject within one tenant."""

    tenant_id: str
    user_id: str
    anonymous_id: Optional[str] = None
    entity_ids: frozenset[str] = frozenset()

    @property
    def refs(self) -> frozenset[str]:
        """user_id + anonymous_id + resolved canonical entity ids."""
        refs = set(self.entity_ids) | {self.user_id}
        if self.anonymous_id:
            refs.add(self.anonymous_id)
        return frozenset(r for r in refs if r)

    @property
    def entity_refs(self) -> frozenset[str]:
        """Identifiers usable as an entity key (user_id + canonical ids)."""
        return frozenset(r for r in (set(self.entity_ids) | {self.user_id}) if r)


async def resolve_subject(
    tenant_id: str, user_id: str, anonymous_id: Optional[str] = None,
) -> ErasureSubject:
    """Resolve the subject's canonical entity ids from the identity plane.

    * owners of the ``user_id`` alias (stored un-hashed) are the subject;
    * owners of the ``anonymous_id`` alias are included ONLY when that entity
      carries no ``user_id`` alias for a DIFFERENT user — a shared device that
      resolved to another identified person is never erased as this subject;
    * merge tombstones (``identity_subjects.merged_into_entity_id``) folded into
      any resolved entity are the subject's pre-merge fragments (bounded walk).

    Read-only and tenant-scoped; revoked aliases still count (erasure must reach
    them too).
    """
    from services.identity.repository import IdentityResolutionRepository

    repo = IdentityResolutionRepository()
    entities: set[str] = set()

    async def _owners(alias_type: str, value: str) -> set[str]:
        rows = await repo._aliases.find_many(  # noqa: SLF001 — erasure reads raw rows
            filters={
                "tenant_id": tenant_id,
                "alias_type": alias_type,
                "alias_value_hash": value,
            },
            limit=_PAGE,
        )
        return {r["canonical_entity_id"] for r in rows if r.get("canonical_entity_id")}

    entities |= await _owners("user_id", user_id)
    if anonymous_id:
        for entity in await _owners("anonymous_id", anonymous_id):
            user_aliases = await repo._aliases.find_many(  # noqa: SLF001
                filters={
                    "tenant_id": tenant_id,
                    "canonical_entity_id": entity,
                    "alias_type": "user_id",
                },
                limit=_PAGE,
            )
            if any(a.get("alias_value_hash") not in (None, "", user_id) for a in user_aliases):
                continue  # another identified person's entity — not this subject
            entities.add(entity)

    frontier = set(entities)
    for _ in range(10):  # merge tombstones folded into the subject's entities
        found: set[str] = set()
        for entity in frontier:
            rows = await repo._subjects.find_many(  # noqa: SLF001
                filters={"tenant_id": tenant_id, "merged_into_entity_id": entity},
                limit=_PAGE,
            )
            found |= {r["canonical_entity_id"] for r in rows if r.get("canonical_entity_id")}
        found -= entities
        if not found:
            break
        entities |= found
        frontier = found
    return ErasureSubject(
        tenant_id=tenant_id,
        user_id=user_id,
        anonymous_id=anonymous_id or None,
        entity_ids=frozenset(entities),
    )


async def _delete_where(repo: Any, tenant_id: str, fields: Iterable[str], values: Iterable[str]) -> int:
    """Tenant-scoped hard delete of ``repo`` rows whose any ``field`` ∈ ``values``."""
    values = list(values)
    total = 0
    for name in fields:
        total += await repo.delete_for_tenant_where(tenant_id, name, values)
    return total


# ═══════════════════════════════════════════════════════════════════════════
# Identity plane — identity_aliases / identity_subjects / graph_edges
# ═══════════════════════════════════════════════════════════════════════════


async def erase_identity_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete the subject's identity-resolution rows + revoke graph edges.

    Append-only identity audit (``identity_merge_events``,
    ``identity_split_events``, ``identity_resolution_audit``) and the graph
    mutation ledger / fact versions are storage-policy ``preserve`` and are NOT
    erased here — they are the lawful audit trail of what the resolver did.
    """
    from repositories.repos import EntityRepository, IdentityClusterRepository
    from services.identity.repository import IdentityResolutionRepository

    tenant = subject.tenant_id
    ids = sorted(subject.entity_refs)
    direct = [r for r in (subject.user_id, subject.anonymous_id) if r]
    repo = IdentityResolutionRepository()

    # Aliases/observations owned by the subject's entities, plus the raw
    # user_id / anonymous_id signal rows themselves (stored un-hashed) even
    # when an alias was never linked to a resolved entity.
    alias_count = await _delete_where(
        repo._aliases, tenant, ["canonical_entity_id"], ids  # noqa: SLF001
    )
    alias_count += await _delete_where(
        repo._aliases, tenant, ["alias_value_hash"], direct  # noqa: SLF001
    )
    observations = await _delete_where(
        repo._observations, tenant, ["canonical_entity_id"], ids  # noqa: SLF001
    )
    observations += await _delete_where(
        repo._observations, tenant, ["signal_value_hash"], direct  # noqa: SLF001
    )

    subjects = await _delete_where(repo._subjects, tenant, ["canonical_entity_id"], ids)  # noqa: SLF001
    clusters_v2 = await _delete_where(repo._clusters, tenant, ["canonical_entity_id"], ids)  # noqa: SLF001
    legacy_clusters = await _delete_where(IdentityClusterRepository(), tenant, ["entity_id"], ids)
    entities = await _delete_where(EntityRepository(), tenant, ["entity_id"], ids)

    identity_edges = await _delete_where(
        repo._edges, tenant, ["source_entity_id", "target_entity_id"], ids  # noqa: SLF001
    )
    graph_revoked = await _revoke_graph_edges(tenant, subject.refs)

    return {
        IDENTITY_ALIASES_COMPONENT: Receipt(
            records_impacted=alias_count + observations,
            detail={"identity_aliases": alias_count,
                    "identity_signal_observations": observations},
        ),
        IDENTITY_SUBJECTS_COMPONENT: Receipt(
            records_impacted=subjects + clusters_v2 + legacy_clusters + entities,
            detail={"identity_subjects": subjects, "identity_clusters_v2": clusters_v2,
                    "identity_clusters": legacy_clusters, "entities": entities},
        ),
        GRAPH_EDGES_COMPONENT: Receipt(
            records_impacted=identity_edges + graph_revoked,
            detail={"identity_edges": identity_edges, "graph_edges_revoked": graph_revoked},
        ),
    }


async def _revoke_graph_edges(tenant_id: str, vertex_ids: Iterable[str]) -> int:
    """Soft-revoke every active graph edge incident to the subject's vertices.

    Goes through ``GraphMutationGateway`` (``edge_tombstoned``) so the ledger
    records the erasure; only edges whose tenant property equals ``tenant_id``
    are touched. Idempotent: revoked edges are excluded from ``get_edges``.
    """
    from shared.graph.graph import get_graph_client, tenant_of
    from shared.graph.mutation_gateway import GraphMutationGateway
    from shared.graph.mutation_intents import revocation_intent

    client = get_graph_client()
    gateway = GraphMutationGateway(graph_client=client)
    revoked = 0
    seen: set[tuple[str, str, str]] = set()
    for vertex_id in sorted(vertex_ids):
        edges = await client.get_edges(vertex_id, direction="both")
        for edge in edges:
            if str(tenant_of(edge.properties) or "") != tenant_id:
                continue
            key = (edge.from_vertex_id, edge.to_vertex_id, edge.edge_type)
            if key in seen:
                continue
            seen.add(key)
            await gateway.apply(revocation_intent(
                from_vertex_id=edge.from_vertex_id,
                to_vertex_id=edge.to_vertex_id,
                edge_type=edge.edge_type,
                reason=ERASURE_REASON,
                tenant_id=tenant_id,
                operation="edge_tombstoned",
                actor_id=ERASURE_ACTOR,
                subject_kind="entity",
                subject_id=vertex_id,
                reason_code=ERASURE_REASON,
            ))
            revoked += 1
    return revoked


# ═══════════════════════════════════════════════════════════════════════════
# Profile 360 snapshots
# ═══════════════════════════════════════════════════════════════════════════


async def erase_profile360_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete the Profile 360 snapshot stores for the subject.

    ``profiles`` (the identity profile row, keyed by user id), the derived
    ``behavior_profiles`` snapshot (keyed by entity id) and the cross-journey
    ``journey_chains`` memory. All three are ``hard_delete`` by storage policy.
    """
    from repositories.repos import (
        BehaviorProfileRepository,
        JourneyChainRepository,
        _ProfileStore,
    )

    tenant = subject.tenant_id
    ids = sorted(subject.entity_refs)
    profiles = await _delete_where(_ProfileStore(), tenant, ["id"], ids)
    behavior = await _delete_where(BehaviorProfileRepository(), tenant, ["entity_id"], ids)
    chains = await _delete_where(JourneyChainRepository(), tenant, ["entity_id"], ids)
    return {
        PROFILE360_COMPONENT: Receipt(
            records_impacted=profiles + behavior + chains,
            detail={"profiles": profiles, "behavior_profiles": behavior,
                    "journey_chains": chains},
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Feature rows (lake Gold) + ML planes
# ═══════════════════════════════════════════════════════════════════════════

# Gold tables owned by the semantic plane (erased by SemanticIntelligenceService
# under the semantic components) — never a lake feature row.
_SEMANTIC_GOLD_PREFIXES = (
    "gold_entity_semantic", "gold_entity_sentiment", "gold_relationship_",
    "gold_campaign_semantic", "gold_campaign_sentiment", "gold_narrative",
    "gold_semantic", "gold_agent_alignment",
)


async def _jsonb_lake_tables(prefix: str) -> list[str]:
    """JSONB-mode lake tables named ``<prefix>*`` (``id``/``data``/``tenant_id``).

    Local: the shared in-memory BaseRepository stores; PostgreSQL: the
    information_schema (tables that carry a ``data`` jsonb column).
    """
    from repositories.repos import _IN_MEMORY_STORES, get_pool

    pool = await get_pool()
    if pool is None:
        return sorted(t for t in _IN_MEMORY_STORES if t.startswith(prefix))
    rows = await pool.fetch(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name LIKE $1 "
        "AND column_name = 'data' AND data_type = 'jsonb'",
        prefix.replace("_", "\\_") + "%",
    )
    tables = {r["table_name"] for r in rows}
    with_tenant = await pool.fetch(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ANY($1::text[]) "
        "AND column_name = 'tenant_id'",
        sorted(tables),
    )
    return sorted(r["table_name"] for r in with_tenant)


def _lake_table(table: str) -> Any:
    """A JSONB ``BaseRepository`` bound to one discovered lake table."""
    from repositories.repos import BaseRepository

    class _LakeTableRepository(BaseRepository):
        pass

    return _LakeTableRepository(table)


async def erase_feature_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete the subject's per-entity Gold feature rows + feature cache.

    Lake Gold (``repositories.lake.GoldRepository`` → ``gold_<domain>``) is the
    backend's ML-ready feature store: one row per (tenant, metric, entity). Rows
    whose ``entity_id`` names the subject are deleted in every discovered Gold
    table (semantic-owned Gold tables excluded — the semantic plane owns them).
    ``detail['training_eligible']`` counts deleted rows flagged
    ``model_training_eligible`` — the evidence the ML planes read.
    The ML serving feature cache (``features:{tenant}:{entity}``) is dropped
    and reported as ``artifacts_impacted``.
    """
    from repositories.repos import get_pool

    tenant = subject.tenant_id
    ids = sorted(subject.entity_refs)
    deleted = 0
    eligible = 0
    detail: dict[str, int] = {}
    pool = await get_pool()
    for table in await _jsonb_lake_tables("gold_"):
        if table.startswith(_SEMANTIC_GOLD_PREFIXES):
            continue
        repo = _lake_table(table)
        if pool is None:
            eligible += sum(
                1 for row in repo._store.values()  # noqa: SLF001
                if row.get("tenant_id") == tenant
                and str(row.get("entity_id")) in ids
                and row.get("model_training_eligible")
            )
        else:
            eligible += int(await pool.fetchval(
                f"SELECT COUNT(*) FROM {table} WHERE tenant_id = $1 "
                "AND data->>'entity_id' = ANY($2::text[]) "
                "AND COALESCE(data->>'model_training_eligible', 'false') = 'true'",
                tenant, ids,
            ) or 0)
        n = await repo.delete_for_tenant_where(tenant, "entity_id", ids)
        if n:
            detail[table] = n
        deleted += n

    cache_keys = 0
    from dependencies.providers import get_registry
    from shared.cache.cache import CacheKey

    cache = get_registry().cache
    for ref in ids:
        key = CacheKey.custom(f"features:{tenant}:{ref}")
        if await cache.exists(key):
            await cache.delete(key)
            cache_keys += 1
    detail["training_eligible"] = eligible
    return {
        FEATURE_ROWS_COMPONENT: Receipt(
            records_impacted=deleted, artifacts_impacted=cache_keys, detail=detail,
        ),
    }


async def assess_ml_artifact_plane(
    subject: ErasureSubject, training_eligible_erased: int,
) -> dict[str, Receipt]:
    """Account for training datasets and model artifacts (no backend store).

    The backend holds neither training dataset bytes nor model artifacts: the
    offline ``services/ml`` pipeline trains from parquet at ``data_path`` / S3
    and writes artifacts under ``AETHER_MODEL_ARTIFACT_DIR``. The backend's
    register of derived artifacts embedding a subject is ``dsr_artifact_index``
    (``ArtifactIndex``). Evidence:

    * indexed training-dataset / model artifacts naming the subject →
      ``requires_manual_review`` + ``requires_retrain`` + ``artifacts_impacted``
      (the offline bytes cannot be purged from here — an operator rebuilds);
    * otherwise ``completed`` with a zero receipt; ``requires_retrain`` is set
      when the subject had training-eligible Gold rows (erased by
      ``feature_rows``), because a dataset built from them must be rebuilt.
    """
    from services.dsr_propagation.indexes import ArtifactIndex

    index = ArtifactIndex()
    artifacts: dict[str, str] = {}
    for ref in sorted(subject.refs):
        for row in await index.artifacts_for_subject(subject.tenant_id, ref):
            artifacts[row["artifact_id"]] = row.get("kind", "")
    datasets = sorted(a for a, k in artifacts.items() if k in TRAINING_DATASET_KINDS)
    models = sorted(a for a, k in artifacts.items() if k in MODEL_ARTIFACT_KINDS)
    retrain = training_eligible_erased > 0

    def _receipt(hits: list[str], policy: str, records: int) -> Receipt:
        if hits:
            return Receipt(
                status="requires_manual_review",
                records_impacted=records,
                artifacts_impacted=len(hits),
                requires_retrain=True,
                policy_decision_id=policy,
            )
        return Receipt(
            records_impacted=records,
            requires_retrain=retrain,
            policy_decision_id=policy,
        )

    return {
        TRAINING_DATASETS_COMPONENT: _receipt(
            datasets, POLICY_NO_TRAINING_STORE, training_eligible_erased,
        ),
        MODEL_ARTIFACTS_COMPONENT: _receipt(models, POLICY_NO_MODEL_STORE, 0),
    }


def _model_ids() -> list[str]:
    """Canonical model ids from the ML model registry (``common.model_registry``).

    The image puts ``services/ml/common`` on the path as ``common``; a checkout
    without it loads the same file by path. Raises when neither is available —
    the prediction cache cannot be enumerated, so the plane must fail (retry)
    rather than report a zero it cannot prove.
    """
    try:
        from common.model_registry import list_models  # type: ignore[import-not-found]
    except ImportError:
        import importlib.util
        import sys
        from pathlib import Path

        name = "_dsr_ml_model_registry"
        module = sys.modules.get(name)
        if module is None:
            path = Path(__file__).resolve().parents[3] / "ml" / "common" / "model_registry.py"
            if not path.exists():
                raise RuntimeError(
                    "ML model registry unavailable; cannot enumerate the prediction cache"
                )
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            sys.modules[name] = module  # dataclasses resolve their module by name
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        list_models = module.list_models
    return sorted({m.model_id for m in list_models()})


async def erase_prediction_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Drop every cached prediction for the subject's entities.

    ``/v1/ml/predict`` caches ``aether:ml:prediction:{model}:{entity}[:{ver}:{hash}]``
    (TTL 15 min). These are the only backend-resident per-subject prediction
    buffers; drift monitoring (``services/ml/monitoring``) consumes offline
    DataFrames and keeps no backend buffer. Both key shapes are removed per
    (model, entity) — the exact key and the ``:``-delimited versioned prefix,
    never a bare prefix that could match another entity id.
    """
    from dependencies.providers import get_registry
    from shared.cache.cache import CacheKey

    cache = get_registry().cache
    removed = 0
    for model_id in _model_ids():
        for ref in sorted(subject.entity_refs):
            key = CacheKey.prediction(model_id, ref)
            if await cache.exists(key):
                await cache.delete(key)
                removed += 1
            removed += int(await cache.delete_pattern(f"{key}:*") or 0)
    return {PREDICTION_BUFFERS_COMPONENT: Receipt(records_impacted=removed)}


# ═══════════════════════════════════════════════════════════════════════════
# Exports / audit exports
# ═══════════════════════════════════════════════════════════════════════════


def _scalar_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for v in value.values():
            yield from _scalar_values(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _scalar_values(v)
    elif value is not None:
        yield str(value)


def _artifact_values(content: bytes, content_type: str) -> Optional[set[str]]:
    """Every scalar cell/value in an export artifact, or ``None`` if unreadable."""
    ctype = (content_type or "").lower()
    try:
        if "parquet" in ctype:
            import pyarrow.parquet as pq  # optional extra

            rows = pq.read_table(io.BytesIO(content)).to_pylist()
            return set(_scalar_values(rows))
        text = content.decode("utf-8")
        if "csv" in ctype:
            return {cell for row in csv.reader(io.StringIO(text)) for cell in row}
        if "ndjson" in ctype:
            return {
                v for line in text.splitlines() if line.strip()
                for v in _scalar_values(json.loads(line))
            }
        return set(_scalar_values(json.loads(text)))
    except Exception:  # noqa: BLE001 — undecodable → caller treats conservatively
        return None


async def erase_export_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Purge every live export artifact whose rows name the subject.

    Each non-deleted artifact of the tenant is decoded (json / ndjson / csv /
    parquet) and purged when any value EQUALS a subject identifier (exact
    match — never a substring, so a short id cannot match another subject's
    value). An artifact that cannot be decoded is purged conservatively (it is
    a regenerable, 7-day derived copy). Purge = ``soft_delete`` (content NULLed,
    checksummed tombstone kept); a Data Exchange egress mirror of a purged
    artifact has its object deleted and its envelope row tombstoned.
    ``audit_log`` artifacts are receipted under ``audit_exports``; the audit
    ledger they were read from is storage-policy ``preserve`` and untouched.
    """
    from repositories.artifacts import get_artifact_repository

    tenant = subject.tenant_id
    refs = set(subject.refs)
    repo = get_artifact_repository()
    candidates: list[dict] = []
    offset = 0
    while True:
        page = await repo.list_for_tenant(tenant, limit=200, offset=offset)
        candidates.extend(page)
        if len(page) < 200:
            break
        offset += 200

    purged: dict[str, list[str]] = {EXPORTS_COMPONENT: [], AUDIT_EXPORTS_COMPONENT: []}
    for meta in candidates:
        if meta.get("deleted_at"):
            continue
        try:
            meta, content = await repo.get_content(tenant, meta["id"])
        except Exception:  # noqa: BLE001 — expired/absent content holds no data
            continue
        values = _artifact_values(content, meta.get("content_type", ""))
        if values is not None and not (values & refs):
            continue
        await repo.soft_delete(tenant, meta["id"])
        component = (
            AUDIT_EXPORTS_COMPONENT
            if meta.get("export_type") in AUDIT_EXPORT_TYPES
            else EXPORTS_COMPONENT
        )
        purged[component].append(meta["id"])

    mirrors = await _purge_egress_mirrors(
        tenant, set(purged[EXPORTS_COMPONENT]) | set(purged[AUDIT_EXPORTS_COMPONENT])
    )
    return {
        EXPORTS_COMPONENT: Receipt(
            artifacts_impacted=len(purged[EXPORTS_COMPONENT]),
            records_impacted=mirrors.get(EXPORTS_COMPONENT, 0),
        ),
        AUDIT_EXPORTS_COMPONENT: Receipt(
            artifacts_impacted=len(purged[AUDIT_EXPORTS_COMPONENT]),
            records_impacted=mirrors.get(AUDIT_EXPORTS_COMPONENT, 0),
        ),
    }


async def _purge_egress_mirrors(tenant_id: str, artifact_ids: set[str]) -> dict[str, int]:
    """Delete Data Exchange egress mirrors of purged canonical artifacts."""
    if not artifact_ids:
        return {}
    from repositories.data_artifacts import get_data_artifact_repository
    from shared.storage.object_store import get_object_store

    repo = get_data_artifact_repository()
    rows: list[dict] = []
    offset = 0
    while True:
        page = await repo.list_for_tenant(
            tenant_id, limit=200, offset=offset, direction="egress", status="available",
        )
        rows.extend(page)
        if len(page) < 200:
            break
        offset += 200
    store = None
    removed = 0
    for row in rows:
        meta = row.get("source_or_destination") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        if meta.get("canonical_artifact_id") not in artifact_ids:
            continue
        store = store or get_object_store()
        if row.get("object_key"):
            store.delete(row["object_key"])
        await repo.mark_deleted(tenant_id, row["artifact_id"])
        removed += 1
    return {EXPORTS_COMPONENT: removed} if removed else {}


# ═══════════════════════════════════════════════════════════════════════════
# Cached tenant views
# ═══════════════════════════════════════════════════════════════════════════


async def erase_cached_views_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Drop every cache that can serve a view built over the subject's data.

    Tenant-wide read caches (graph query / facet / replay results, analytics
    query results) are dropped by ``:``-delimited tenant prefix — they aggregate
    many subjects and cannot be filtered, so the whole tenant scope is rebuilt
    on the next read. Subject-keyed caches (identity profile, consent state)
    are deleted by exact key. Every count is the cache backend's own.
    """
    from dependencies.providers import get_registry
    from repositories.repos import analytics_query_cache_pattern
    from shared.cache.cache import CacheKey

    cache = get_registry().cache
    tenant = subject.tenant_id
    removed = 0
    for pattern in (
        f"aether:graph:query:{tenant}:*",
        f"aether:graph:facets:{tenant}:*",
        f"aether:graph:replay:{tenant}:*",
        analytics_query_cache_pattern(tenant),
    ):
        removed += int(await cache.delete_pattern(pattern) or 0)
    for ref in sorted(subject.refs):
        for key in (CacheKey.profile(tenant, ref), CacheKey.consent(tenant, ref)):
            if await cache.exists(key):
                await cache.delete(key)
                removed += 1
    return {CACHED_VIEWS_COMPONENT: Receipt(records_impacted=removed)}


# ═══════════════════════════════════════════════════════════════════════════
# Replay bundles (event envelopes)
# ═══════════════════════════════════════════════════════════════════════════


def _envelope_names_subject(envelope: dict, refs: set[str]) -> bool:
    subject = envelope.get("subject") or {}
    if isinstance(subject, dict) and str(subject.get("id") or "") in refs:
        return True
    payload = envelope.get("payload") or {}
    if isinstance(payload, dict):
        for key in ("user_id", "userId", "anonymous_id", "anonymousId",
                    "entity_id", "profile_id"):
            if str(payload.get(key) or "") in refs:
                return True
    return False


async def erase_replay_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete the subject's replayable event envelopes.

    ``event_envelopes`` (storage policy ``hard_delete``) is the replay source:
    each envelope names its tenant in ``tenantId`` and the subject in
    ``subject.id`` and/or payload identifiers. Matching envelopes are deleted
    and evicted from the replay router's process-local hot cache.
    """
    from repositories.repos import EventEnvelopeRepository

    tenant = subject.tenant_id
    refs = set(subject.refs)
    repo = EventEnvelopeRepository()
    doomed: list[str] = []
    offset = 0
    while True:
        page = await repo.find_many(filters={"tenantId": tenant}, limit=_PAGE, offset=offset)
        doomed.extend(
            str(e["id"]) for e in page
            if e.get("tenantId") == tenant and _envelope_names_subject(e, refs)
        )
        if len(page) < _PAGE:
            break
        offset += _PAGE
    deleted = 0
    for envelope_id in doomed:
        if await repo.delete(envelope_id):
            deleted += 1
    try:
        from services.events import routes as event_routes

        for envelope_id in doomed:
            event_routes._EVENTS.pop(envelope_id, None)  # noqa: SLF001
    except Exception:  # noqa: BLE001 — the hot cache is best-effort, process-local
        pass
    return {REPLAY_BUNDLES_COMPONENT: Receipt(records_impacted=deleted)}


# ═══════════════════════════════════════════════════════════════════════════
# Reward decisions (legal retention)
# ═══════════════════════════════════════════════════════════════════════════


async def assess_reward_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Account for the subject's reward eligibility decisions.

    ``reward_eligibility_decisions`` is storage policy ``retention_class: legal``
    / ``delete_behavior: preserve`` (financial decision record + fraud-control
    evidence), so the lawful resolution is retention, not erasure: the step is
    ``skipped_legal_hold`` with the number of retained decisions naming the
    subject (``user_id`` / ``wallet_address``) and the policy pointer.
    """
    from services.rewards.repositories import RewardDecisionRepository

    repo = RewardDecisionRepository()
    refs = set(subject.refs)
    retained = 0
    offset = 0
    while True:
        page = await repo.find_many(
            filters={"tenant_id": subject.tenant_id}, limit=_PAGE, offset=offset,
        )
        retained += sum(
            1 for r in page
            if str(r.get("user_id") or "") in refs
            or str(r.get("wallet_address") or "") in refs
        )
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return {
        REWARD_DECISIONS_COMPONENT: Receipt(
            status="skipped_legal_hold",
            records_impacted=retained,
            policy_decision_id=POLICY_REWARD_RETENTION,
            blocked_reason=(
                "reward_eligibility_decisions is legal-retention (preserve); "
                f"{retained} decision(s) retained"
            ),
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Connector-derived records
# ═══════════════════════════════════════════════════════════════════════════

_PROVIDER_IDENTITY_TOMBSTONE = {
    "provider_profile_id": None,
    "provider_recipient_id": None,
    "email_alias_hash": None,
    "canonical_entity_id": None,
    "canonical_profile_id": None,
    "identity_cluster_id": None,
    "source_evidence": None,
    "resolution_status": "erased",
}


async def erase_connector_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Erase identities derived from customer connectors.

    * ``comms_provider_identities`` (policy ``tombstone``): the provider →
      canonical mapping row is kept as a structural stub with every subject
      identifier cleared and ``resolution_status='erased'``;
    * ``source_identities`` (source-scoped identities, blueprint §5.2) and their
      ``identity_claims``: hard-deleted.
    """
    from services.comms.identity_bridge import ProviderIdentityRepository
    from services.identity.repository import IdentityResolutionRepository

    tenant = subject.tenant_id
    ids = sorted(subject.entity_refs)

    bridge = ProviderIdentityRepository()
    tombstoned = 0
    for field_name in ("canonical_entity_id", "canonical_profile_id"):
        while True:
            rows = []
            for ref in ids:
                rows.extend(await bridge.find_many(
                    {"tenant_id": tenant, field_name: ref}, limit=_PAGE,
                ))
            rows = [r for r in rows if r.get("tenant_id") == tenant]
            if not rows:
                break
            for row in rows:
                await bridge.update(row["id"], dict(_PROVIDER_IDENTITY_TOMBSTONE))
                tombstoned += 1

    identity = IdentityResolutionRepository()
    sources: list[dict] = []
    for field_name, values in (
        ("user_id", [subject.user_id]),
        ("anonymous_id", [subject.anonymous_id] if subject.anonymous_id else []),
        ("canonical_entity_id", ids),
    ):
        for value in values:
            sources.extend(await identity._source_identities.find_many(  # noqa: SLF001
                filters={"tenant_id": tenant, field_name: value}, limit=_PAGE,
            ))
    source_ids = sorted({s["id"] for s in sources if s.get("tenant_id") == tenant})
    claims = await identity._claims.delete_for_tenant_where(  # noqa: SLF001
        tenant, "source_identity_id", source_ids,
    )
    source_count = await identity._source_identities.delete_for_tenant_where(  # noqa: SLF001
        tenant, "id", source_ids,
    )
    return {
        CONNECTOR_RECORDS_COMPONENT: Receipt(
            records_impacted=tombstoned + source_count + claims,
            detail={"comms_provider_identities": tombstoned,
                    "source_identities": source_count, "identity_claims": claims},
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Financial value snapshots
# ═══════════════════════════════════════════════════════════════════════════


async def erase_financial_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete materialized P&L snapshots of the subject's trading accounts.

    ``derivatives_pnl_snapshots`` (policy ``hard_delete``) is keyed by
    ``trading_account_id``; accounts owned by the subject are found through
    ``derivatives_trading_accounts.owner_entity_id``. The value-semantics
    snapshot stores (``value_valuation_snapshots``, ``value_rollup_snapshots``,
    ``value_price_snapshots``, ``valuation_snapshots``) record asset / metric
    valuations with no subject key (see their writers), so they hold no subject
    data — pinned by ``test_value_snapshot_stores_carry_no_subject_key``.
    """
    from repositories.derivatives_repos import PnlSnapshotRepo, TradingAccountRepo

    tenant = subject.tenant_id
    accounts: set[str] = set()
    for ref in sorted(subject.entity_refs):
        offset = 0
        while True:
            page = await TradingAccountRepo().find_many(
                {"tenant_id": tenant, "owner_entity_id": ref}, limit=_PAGE, offset=offset,
            )
            accounts |= {a["trading_account_id"] for a in page if a.get("trading_account_id")}
            if len(page) < _PAGE:
                break
            offset += _PAGE
    deleted = await PnlSnapshotRepo().delete_for_tenant_where(
        tenant, "trading_account_id", sorted(accounts),
    )
    return {
        FINANCIAL_SNAPSHOTS_COMPONENT: Receipt(
            records_impacted=deleted, artifacts_impacted=len(accounts),
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Silver facts
# ═══════════════════════════════════════════════════════════════════════════

# Identifier columns (typed) / JSONB keys (lake) that name a data subject in a
# Silver fact row. A row is the subject's when ANY of them equals a subject ref.
SILVER_SUBJECT_COLUMNS: tuple[str, ...] = (
    "user_id", "anonymous_id", "actor_id", "profile_id", "entity_id",
    "canonical_entity_id", "canonical_entity_ref", "canonical_profile_id",
    "sender_entity_id", "recipient_entity_id", "subject_ref", "owner_entity_id",
)

# Silver tables erased by ANOTHER component (never double-owned):
#   attribution_records → touchpoints + canonical conversions (tombstoned by the
#                         measurement privacy handler, which rebuilds journeys);
#   semantic_*          → the semantic privacy handler's tables.
SILVER_EXCLUDED_TABLES = frozenset({
    "silver_campaign_touchpoint_facts",
    "canonical_conversions",
    "silver_semantic_observations",
    "silver_semantic_entity_mentions",
    "silver_semantic_subject_links",
    "silver_semantic_claims",
    "silver_sentiment_observations",
})


def _silver_projector_tables() -> list[str]:
    from services.silver.generated_ownership import PROJECTOR_TABLES

    return sorted(set(PROJECTOR_TABLES.values()) - SILVER_EXCLUDED_TABLES)


def _row_is_subject(row: dict, refs: set[str]) -> bool:
    for col in SILVER_SUBJECT_COLUMNS:
        value = row.get(col)
        if value not in (None, "") and str(value) in refs:
            return True
    return False


def _purge_local(store: dict, tenant: str, refs: set[str]) -> int:
    doomed = [
        k for k, row in store.items()
        if row.get("tenant_id") == tenant and _row_is_subject(row, refs)
    ]
    for k in doomed:
        del store[k]
    return len(doomed)


async def erase_silver_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Hard-delete the subject's rows across every Silver fact table.

    Tables: every projector table (``generated_ownership.PROJECTOR_TABLES``) and
    every other ``silver_*`` table, minus the ones another component owns
    (:data:`SILVER_EXCLUDED_TABLES`). Schemas are introspected through the
    Silver writer (``SilverFactWriter._table_columns`` — the same cached
    information_schema read the durable write path uses): the subject columns
    present in a table (:data:`SILVER_SUBJECT_COLUMNS`) and, for lake Silver
    (JSONB ``data``), the same keys inside ``data``. One tenant-scoped DELETE per
    table; a table without ``tenant_id`` is skipped (cannot be tenant-scoped)
    and reported in the log. Storage policy for ``silver_*`` is ``hard_delete``.
    """
    from repositories.repos import get_pool

    tenant = subject.tenant_id
    refs = set(subject.refs)
    detail: dict[str, int] = {}
    pool = await get_pool()

    if pool is None:
        from repositories.repos import _IN_MEMORY_STORES
        from services.comms import repository as comms_repo
        from services.silver import writer as silver_writer
        from services.silver.repositories import social_facts

        stores: dict[str, dict] = {}
        for table, store in silver_writer._local_tables.items():  # noqa: SLF001
            stores[table] = store
        for table, store in social_facts._local_rows.items():  # noqa: SLF001
            stores[table] = store
        stores["silver_comms_facts"] = comms_repo._local_facts  # noqa: SLF001
        for table, store in _IN_MEMORY_STORES.items():
            if table.startswith("silver_"):
                stores.setdefault(table, store)
        for table, store in stores.items():
            if table in SILVER_EXCLUDED_TABLES:
                continue
            n = _purge_local(store, tenant, refs)
            if n:
                detail[table] = n
    else:
        from services.silver.writer import SilverFactWriter

        writer = SilverFactWriter()
        rows = await pool.fetch(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name LIKE 'silver\\_%'"
        )
        tables = sorted(
            ({r["table_name"] for r in rows} | set(_silver_projector_tables()))
            - SILVER_EXCLUDED_TABLES
        )
        wanted = sorted(refs)
        for table in tables:
            columns = dict(await writer._table_columns(pool, table))  # noqa: SLF001
            if not columns:
                continue
            if "tenant_id" not in columns:
                logger.warning("silver_dsr_skip_untenanted table=%s", table)
                continue
            predicates = [f"{c}::text = ANY($2::text[])"
                          for c in SILVER_SUBJECT_COLUMNS if c in columns]
            if columns.get("data") == "jsonb":
                predicates += [f"data->>'{c}' = ANY($2::text[])"
                               for c in SILVER_SUBJECT_COLUMNS if c not in columns]
            if not predicates:
                continue  # no subject identity in this table's schema
            status = await pool.execute(
                f"DELETE FROM {table} WHERE tenant_id = $1 AND ({' OR '.join(predicates)})",
                tenant, wanted,
            )
            try:
                n = int(str(status).split()[-1])
            except (ValueError, IndexError):
                n = 0
            if n:
                detail[table] = n
    return {
        SILVER_FACTS_COMPONENT: Receipt(
            records_impacted=sum(detail.values()), detail=detail,
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Bronze (hash-chained) + event outbox
# ═══════════════════════════════════════════════════════════════════════════

_OUTBOX_CLAIMABLE = ("pending", "retry", "claimed")


async def erase_bronze_plane(subject: ErasureSubject) -> dict[str, Receipt]:
    """Chain-preserving erasure of the subject's Bronze events.

    ``bronze_sdk_events`` rows are hash-chained per tenant (LEDGER M2): each
    ``integrity_hash`` folds ``(tenant_id, event_id, schema_version,
    event_type, event_timestamp, payload_hash)`` with the previous row's hash.
    None of the hashed fields identifies the subject, and the payload enters
    the chain only through its ``payload_hash`` digest — so the erasure
    TOMBSTONES chained rows (payload ``{}``, ``user_id`` / ``anonymous_id`` /
    ``entity_id`` / ``session_id`` cleared, ``tombstoned`` stamp) and keeps the
    hashed fields + backlinks: ``chain_verifier.verify_tenant_chain`` still
    passes and the row count never regresses. Externalized (object-backed)
    payloads are re-packed without the subject by
    ``StorageLifecycle.dsr_erase_subject``, which applies this rule. An active
    legal hold covering the subject blocks the whole plane with no mutation →
    ``skipped_legal_hold`` carrying the hold id.

    ``event_outbox`` rows for the subject's events keep their chain the same
    way: ``payload`` is redacted to ``{}`` (``payload_hash`` retained) and a row
    not yet published is moved to ``dead_letter`` (``last_error='dsr_erased'``)
    so the relay never publishes it. The outbox chain's ``partition_key``
    (hashed; = user_id or anonymous_id for SDK events) cannot be rewritten
    without breaking the chain — see the DSR coverage doc's open decision.
    """
    from shared.storage.compaction import BRONZE_RESOURCE_TYPE
    from shared.storage.lifecycle import StorageLifecycle

    tenant = subject.tenant_id
    lifecycle = StorageLifecycle()
    # A hold on ANY of the subject's identifiers holds the whole subject: check
    # them all before mutating anything (an erasure keyed on the anonymous id
    # must not proceed while the user id is under hold — the rows overlap).
    for ref in sorted(subject.refs):
        hold = await lifecycle.active_hold(tenant, BRONZE_RESOURCE_TYPE, ref)
        if hold is not None:
            return {
                BRONZE_EVENTS_COMPONENT: Receipt(
                    status="skipped_legal_hold",
                    policy_decision_id=f"storage_legal_hold:{hold.get('hold_id')}",
                    blocked_reason=str(hold.get("reason") or "legal hold"),
                ),
            }
    rows = packed = 0
    for ref in sorted(subject.refs):
        report = await lifecycle.dsr_erase_subject(tenant, ref)
        if report.get("status") == "blocked_legal_hold":
            # A hold placed between the pre-check and this ref: fail (retry
            # re-evaluates) rather than report a partial erasure as lawful.
            raise RuntimeError(f"legal hold {report.get('hold_id')!r} placed mid-erasure")
        if report.get("status") != "completed":
            raise RuntimeError(f"bronze erasure incomplete for a subject ref: {report.get('status')}")
        rows += int(report.get("rows_removed", 0))
        packed += int(report.get("packed_records_removed", 0))
    outbox = await _redact_outbox(tenant, sorted(subject.refs))
    return {
        BRONZE_EVENTS_COMPONENT: Receipt(
            records_impacted=rows + packed + outbox,
            detail={"bronze_rows": rows, "packed_records": packed, "outbox_rows": outbox},
        ),
    }


async def _redact_outbox(tenant_id: str, refs: list[str]) -> int:
    from repositories.repos import _IN_MEMORY_STORES, get_pool
    from shared.common.common import utc_now

    pool = await get_pool()
    if pool is None:
        store = _IN_MEMORY_STORES.setdefault("event_outbox", {})
        wanted = set(refs)
        redacted = 0
        now = utc_now().isoformat()
        for row in store.values():
            if row.get("tenant_id") != tenant_id or row.get("dsr_erased"):
                continue
            payload = row.get("payload") or {}
            if not (
                str(row.get("partition_key") or "") in wanted
                or str(payload.get("user_id") or "") in wanted
                or str(payload.get("anonymous_id") or "") in wanted
            ):
                continue
            row["payload"] = {}
            row["dsr_erased"] = True
            if row.get("status") in _OUTBOX_CLAIMABLE:
                row["status"] = "dead_letter"
                row["last_error"] = "dsr_erased"
            row["updated_at"] = now
            redacted += 1
        return redacted
    status = await pool.execute(
        """
        UPDATE event_outbox
        SET payload = '{}'::jsonb,
            status = CASE WHEN status = ANY($3::text[]) THEN 'dead_letter' ELSE status END,
            last_error = CASE WHEN status = ANY($3::text[]) THEN 'dsr_erased' ELSE last_error END,
            data = data || jsonb_build_object(
                'payload', '{}'::jsonb,
                'dsr_erased', true,
                'status', CASE WHEN status = ANY($3::text[]) THEN 'dead_letter' ELSE status END),
            updated_at = now()
        WHERE tenant_id = $1
          AND COALESCE(data->>'dsr_erased', 'false') <> 'true'
          AND (partition_key = ANY($2::text[])
               OR payload->>'user_id' = ANY($2::text[])
               OR payload->>'anonymous_id' = ANY($2::text[]))
        """,
        tenant_id, refs, list(_OUTBOX_CLAIMABLE),
    )
    try:
        return int(str(status).split()[-1])
    except (ValueError, IndexError):
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Plane registry (execution order)
# ═══════════════════════════════════════════════════════════════════════════

PlaneFn = Callable[[ErasureSubject], Awaitable[dict[str, Receipt]]]

# Entity-keyed planes, run in this order before the identity plane. The ML
# artifact assessment is sequenced by the job right after ``feature_rows``
# (it reads the feature plane's training-eligible count).
ENTITY_PLANES: tuple[tuple[str, tuple[str, ...], PlaneFn], ...] = (
    ("profile360", (PROFILE360_COMPONENT,), erase_profile360_plane),
    ("feature", (FEATURE_ROWS_COMPONENT,), erase_feature_plane),
    ("prediction", (PREDICTION_BUFFERS_COMPONENT,), erase_prediction_plane),
    ("export", (EXPORTS_COMPONENT, AUDIT_EXPORTS_COMPONENT), erase_export_plane),
    ("replay", (REPLAY_BUNDLES_COMPONENT,), erase_replay_plane),
    ("reward", (REWARD_DECISIONS_COMPONENT,), assess_reward_plane),
    ("connector", (CONNECTOR_RECORDS_COMPONENT,), erase_connector_plane),
    ("financial", (FINANCIAL_SNAPSHOTS_COMPONENT,), erase_financial_plane),
    ("silver", (SILVER_FACTS_COMPONENT,), erase_silver_plane),
    ("bronze", (BRONZE_EVENTS_COMPONENT,), erase_bronze_plane),
    ("cached_views", (CACHED_VIEWS_COMPONENT,), erase_cached_views_plane),
)
ML_ARTIFACT_COMPONENTS = (TRAINING_DATASETS_COMPONENT, MODEL_ARTIFACTS_COMPONENT)
IDENTITY_COMPONENTS = (
    IDENTITY_ALIASES_COMPONENT, IDENTITY_SUBJECTS_COMPONENT, GRAPH_EDGES_COMPONENT,
)
