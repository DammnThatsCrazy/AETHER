"""Importable validation core for the Intelligence Projection Registry (P0.2).

A 360 is an intelligence projection over canonical Aether truth — never a
competing system of record. This module is the mechanical enforcement of that
doctrine against ``packages/shared/contracts/intelligence-projection-registry.json``
plus the registries it must resolve against (surface-capability, metric,
graph-mutation, route-registry). It is a library — there is no CLI here; the
``scripts/validate_intelligence_projections.py`` wrapper (P0.8) and the contract
generator (P0.3) both call into it.

Rule groups (each returns ``list[Violation]``; severity ``"error"`` gates CI):

- registry_schema — schemaVersion/contractVersion present; vocab arrays non-empty
  unique lower_snake; ids unique + lower_snake; every required per-entry field
  present and typed; ``ownsCanonicalTruth is False``; enum membership for
  kind/state/policy/migration-mode/temporal-mode/subject-kind; pending entries
  well-formed ``{id, kind, reason, resolvesInProjection}`` with ``kind`` ∈
  {spine, projection, metric, surface} and ``resolvesInProjection`` a registry
  projection id.
- dependency_dag — projection deps ⊆ registry ids or declared pending (a dep
  counts as declared-pending ONLY via a ``kind=="projection"`` pending entry —
  a kind:"metric"/"spine" pending carrying the same id does not declare a
  projection dep); no self-dependency; required ``projectionDependencies``
  cycles are ``error`` (an ordering deadlock — a projection can never
  implement); union cycles (required ∪ optional) that exist only through an
  optional edge are ``warning`` (benign — the lazy runtime degrades missing
  optional deps to ``not_applicable``); ``implemented`` ⇒ zero pending + zero
  unresolved; dangling pending (target now resolves in the spine or projection
  id space, whatever the declared ``kind`` label) ⇒ error; a ``kind:"spine"``
  pending whose target is neither resolved nor a spine-registry ``pending`` row
  ⇒ error (the spine plane's vocabulary is canonical spine-registry.json);
  ``in_flight``/``registered`` may carry pending.
- cross_registry — surfaceIds ⊆ surface registry (a surfaceId is declared
  pending only via ``kind=="surface"``); supportedTemporalModes ⊆ the union of
  the projection's surfaces' modes; metricRefs ⊆ metric registry (a metricRef is
  declared pending only via ``kind=="metric"``); capabilityKeys well-formed
  ``<id>.<verb>``; graphMutationPolicy valid + ``canonical_gateway_only``
  requires a non-empty graph-mutation registry; unresolved-but-declared-pending
  legal for non-implemented, illegal for implemented; dangling pending (target
  resolves in the metric or surface id space, whatever the declared ``kind``
  label) ⇒ error. Pending-related rows are tagged ``rule="order_resilience"``.
- inventory — ``in_flight`` ⇒ legacyBindings non-empty and every binding
  resolves (routes against route_registry.yaml ``known_prefixes`` OR backend
  Python source route-DECLARATION lines; surfaces against the surface registry;
  services exist on disk); ``registered`` ⇒ non-empty blueprint; ``implemented``
  ⇒ migrationMode ``converged`` + zero pending + implementationBlueprint exists
  on disk; ``deprecated`` ⇒ deprecatedReason present; non-deprecated ⇒ blueprint
  is a ``docs/**.md`` path.
- ownership — canonicalAuthorities ⊆ AUTHORITY_INDEX or declared pending;
  ``projector-ownership`` is never a canonical authority.
- surface_honesty — surfaceIds non-empty; ``in_flight`` resolved surfaceIds ⊆
  legacyBindings.surfaceIds.
- metric_honesty — measurement/risk projections with metricRefs must require
  evidence and limitations.

Order-resilience contract (tetris): any cross-registry ref or dependency that
does not yet resolve MUST be declared in ``pendingAuthority``/``pendingReference``
— never a silent string. Declared-but-unresolved is legal for
``registered``/``in_flight``/``deprecated``; ``implemented`` must have zero
pending and zero unresolved; a pending declaration whose target later resolves
is a dangling declaration and errors ("remove it"). Follow-up blueprints may
land in any order the DAG + pending rules permit without disturbing the placed
rows.

Cycle semantics: required-projection cycles are errors (an ordering deadlock —
a projection can never implement). Cycles that exist only through an optional
edge are warnings: the lazy runtime degrades missing optional deps to
``not_applicable``, so a union cycle is benign and never an ordering deadlock.
The real registry intentionally contains optional↔required union cycles (e.g.
relationship360 optionally referencing economic360 while economic360 requires
relationship360); they surface as labelled warnings, never errors. Optional
dependencies are resolution-checked exactly like required ones.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Curated vocabularies
# ---------------------------------------------------------------------------

# Union of every canonicalAuthorities value across the 18-projection registry.
# Alphabetized. Kept here so an authority can never silently drift out of the
# curated plane; additions to a projection must land here (or be declared
# pending) in the same change.
AUTHORITY_INDEX = frozenset(
    {
        "actions",
        "agent_access",
        "agent_entities",
        "agent_entity",
        "agent_executions",
        "ai_execution_facts",
        "attribution_credits",
        "attribution_runs",
        "behavioral_signals",
        "campaign_facts",
        "campaign_touchpoints",
        "canonical_conversions",
        "cluster_definitions",
        "cluster_membership",
        "cohort_membership",
        "commerce",
        "commerce_intent_authority",
        "commerce_product_offer_graph",
        "communication",
        "communication_facts",
        "computation",
        "consent_policy_decisions",
        "connection_config",
        "connection_permissions",
        "context_capsules",
        "credential_readiness",
        "currency_value_normalization",
        "deployments",
        "economic",
        "economic_facts",
        "entities",
        "entity_graph",
        "entity_registry",
        "episode_facts",
        "evidence",
        "events",
        "execution_facts",
        "flow_trace_paths",
        "flow_traces",
        "fraud_synthesis",
        "geo_observations",
        "gold_temporal_heatmap",
        "graph",
        "graph_motifs",
        "graph_snapshots",
        "identity",
        "influence_propagation",
        "ingestion_health",
        "infrastructure_facts",
        "infrastructure_state",
        "journeys",
        "locations",
        "managed_integration_lifecycle",
        "measurement_contract",
        "model_governance",
        "mutation_history",
        "observations",
        "outcome_facts",
        "outcomes",
        "payments",
        "population",
        "population_definitions",
        "provider_connections",
        "provider_health",
        "provider_registry",
        "relationship_facts",
        "relationship_fidelity",
        "relationship_predicate_registry",
        "resources",
        "risk_assessments",
        "risk_outputs",
        "risk_signals",
        "semantic_memory_graph",
        "semantic_memory_records",
        "silver_semantic_observations",
        "social_observations",
        "source_coverage",
        "source_facts",
        "source_provenance",
        "source_schema",
        "support_callback_events",
        "support_callbacks",
        "support_cases",
        "support_case_events",
        "sync_state",
        "temporal",
        "temporal_kernel",
        "targeting_leakage_findings",
        "tools",
        "touchpoints",
        "transfers",
        "validity_state",
    }
)

# The spine plane's vocabulary is the canonical spine registry
# (packages/shared/contracts/spine-registry.json) — the projection plane does
# NOT hand-maintain its own spine list. Every spine row the registry does not
# mark "pending" counts as resolved in the spine plane (implemented AND
# in_flight both mean declared + owner-bound, so pendingAuthority to an
# in_flight row is already dangling). Rows the registry marks "pending" are the
# ONLY legal pendingAuthority kind:"spine" targets, declared per-projection
# until the spine plane lands them — enforced by the order_resilience ratchet.
_SPINE_ROWS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "packages"
        / "shared"
        / "contracts"
        / "spine-registry.json"
    ).read_text(encoding="utf-8")
).get("spines", [])
SPINE_INDEX = frozenset(
    row["id"] for row in _SPINE_ROWS if row.get("implementationState") != "pending"
)
PENDING_SPINE_INDEX = frozenset(
    row["id"] for row in _SPINE_ROWS if row.get("implementationState") == "pending"
)

# Canonical request/context primitives (reused repo-wide; never re-declared).
INPUT_REF_INDEX = frozenset(
    {
        "EntityRef",
        "RelationshipRef",
        "EvidenceRef",
        "GraphSnapshotRef",
        "GraphResult",
        "PageRequest",
        "TimeRangeFilter",
        "MutationIntent",
        "FilterExpression",
    }
)

# The projection plane owns its own capability namespace <projectionId>.<verb>.
PROJECTION_CAPABILITY_VERBS = frozenset({"read", "explore", "manage"})

# Measurement / risk projection kinds — metric honesty applies to them.
_MEASUREMENT_OR_RISK_KINDS = frozenset({"measurement_360", "risk_360"})

_OUTPUT_SECTIONS = frozenset(
    {
        "summary",
        "state",
        "financial_risk",
        "timeline",
        "evidence",
        "interactions",
        "journeys",
        "anomalies",
        "normalization",
        "stages",
        "paths",
        "sessions",
        "outcomes",
        "findings",
        "influence",
        "propagation",
        "health",
        "coverage",
        "deployments",
        "episode_context",
        "policy_boundary",
        "agent_spawned_agents",
        "agent_delegations",
        "syndicates",
        "signal_summary",
        "source_inventory",
        "classification",
        "quality",
        "normalization",
        "linked_entities",
        "campaign_links",
        "risk_flags",
        "freshness",
        "evidence_trace",
        "semantic_summary",
        "memories",
        "cards",
        "topics",
        "embeddings_meta",
        "source_links",
        "decay",
        "conflicts",
        "policy_state",
        "product_offer_summary",
        "catalog_links",
        "exposures",
        "intent",
        "cart_checkout",
        "purchase",
        "availability_price",
        "value",
        "risk",
        "workflow_summary",
        "triggers",
        "runs",
        "actors",
        "approvals",
        "agent_steps",
        "actions",
        "failures",
    }
)

_VOCAB_FIELDS = (
    "projectionKinds",
    "implementationStates",
    "graphMutationPolicies",
    "sectionStates",
    "temporalModes",
    "migrationModes",
    "subjectKinds",
)

_REQUIRED_ENTRY_FIELDS = (
    "id",
    "displayName",
    "projectionKind",
    "implementationState",
    "implementationBlueprint",
    "ownsCanonicalTruth",
    "subjectKinds",
    "canonicalAuthorities",
    "hardDependencies",
    "projectionDependencies",
    "optionalProjectionDependencies",
    "inputRefs",
    "outputSections",
    "supportedTemporalModes",
    "surfaceIds",
    "capabilityKeys",
    "metricRefs",
    "graphMutationPolicy",
    "requiresEvidence",
    "requiresDimensionState",
    "requiresFreshness",
    "requiresLimitations",
    "tenantScoped",
    "policyScoped",
    "readinessRequirements",
    "security",
    "costProfile",
    "commercialClassification",
    "legacyBindings",
    "deprecatedReason",
    "successorId",
    "pendingAuthority",
    "pendingReference",
)

_STR_FIELDS = (
    "id",
    "displayName",
    "projectionKind",
    "implementationState",
    "implementationBlueprint",
    "graphMutationPolicy",
)

_BOOL_FIELDS = (
    "ownsCanonicalTruth",
    "requiresEvidence",
    "requiresDimensionState",
    "requiresFreshness",
    "requiresLimitations",
    "tenantScoped",
    "policyScoped",
)

_LIST_FIELDS = (
    "subjectKinds",
    "canonicalAuthorities",
    "hardDependencies",
    "projectionDependencies",
    "optionalProjectionDependencies",
    "inputRefs",
    "outputSections",
    "supportedTemporalModes",
    "surfaceIds",
    "capabilityKeys",
    "metricRefs",
)

_DICT_FIELDS = (
    "readinessRequirements",
    "security",
    "costProfile",
    "commercialClassification",
    "legacyBindings",
)

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
_ROUTE_FRAGMENT_RE = re.compile(r"/v1/[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*")
_ROUTE_FULL_RE = re.compile(r"^/v1/[a-z0-9][a-z0-9_-]*(?:/[a-z0-9][a-z0-9_-]*)*$")
# A route-declaration line: one of these markers must be present before a
# ``/v1/...`` literal counts as evidence of a mounted router. String literals
# in tests/assertions/config are NOT route declarations.
_ROUTE_DECL_LINE_RE = re.compile(
    r"APIRouter\(|include_router\(|@router\.|@app\.|add_api_route\(|prefix="
)

_PENDING_REQUIRED_KEYS = ("id", "kind", "reason", "resolvesInProjection")
# A pending declaration's ``kind`` namespaces its ``id`` into one of the four
# canonical id spaces (spine plane, projection registry, metric registry,
# surface registry).
_PENDING_KINDS = frozenset({"spine", "projection", "metric", "surface"})

# The product catalog is a separate namespace from the technical projection
# registry. A product surface may compose one or more providers, but must not
# be inferred from the projection rows or their UI ``surfaceIds``.
EXPECTED_PRODUCT_360_SURFACE_IDS = frozenset(
    {
        "account360",
        "agent360",
        "campaign360",
        "commerce360",
        "communications360",
        "episode360",
        "execution360",
        "identity360",
        "journey360",
        "location360",
        "memory360",
        "profile360",
        "risk360",
        "signals360",
        "social360",
        "support360",
        "value360",
        "workflow360",
    }
)
# Direct product-surface providers are a separate namespace from technical
# projection providers. Keep this allowlist tied to the code-wired paths that
# currently exist; adding a row here requires the corresponding frame-runtime
# call path and focused integration coverage.
EXPECTED_DIRECT_PROVIDER_BINDINGS = {
    "account360": [
        {
            "providerClass": "Account360Provider",
            "providerKind": "surface_frame_provider",
            "bindingStatus": "runtime_wired",
            "subjectKinds": ["entity"],
            "domainSlotIds": ["account_summary", "members", "agents", "profiles", "risk"],
            "canonicalAuthorityRefs": [
                "entities",
                "entity_registry",
                "graph",
                "identity",
                "risk_outputs",
            ],
            "implementationRef": "services/api/identity/account360_provider.py",
            "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
        }
    ],
    "identity360": [
        {
            "providerClass": "Identity360Provider",
            "providerKind": "surface_authority_reader",
            "bindingStatus": "runtime_wired",
            "subjectKinds": ["agent", "entity", "source"],
            "domainSlotIds": [
                "identifier_inventory",
                "namespace_map",
                "match_evidence",
                "conflicts",
                "confidence",
                "aliases",
                "devices_sessions",
                "wallets",
                "policy_redactions",
                "evidence_trace",
            ],
            "canonicalAuthorityRefs": [
                "entities",
                "entity_registry",
                "evidence",
                "identity",
                "provider_registry",
                "source_provenance",
            ],
            "implementationRef": "services/api/identity/identity/identity360_provider.py",
            "runtimeBindingRef": "services/api/shared/intelligence_projections/frame_runtime.py",
        }
    ],
}
EXPERIENCE_360_FRAME_STATES = frozenset(
    {
        "ready",
        "partial",
        "empty",
        "missing",
        "unknown",
        "suppressed",
        "stale",
        "degraded",
        "unavailable",
        "conflicted",
    }
)

# ── Projection engine (A8) constants ─────────────────────────────────────────

# A lens is ``base`` (a composable viewing frame that stands alone — exactly one
# default base lens: ``standard``) or ``overlay`` (refines a declared base).
_LENS_KINDS = frozenset({"base", "overlay"})

_LENS_REQUIRED_FIELDS = (
    "id",
    "displayName",
    "kind",
    "baseLens",
    "description",
    "domain",
    "applicableSubjectKinds",
    "temporalModes",
    "default",
)

# Every SectionState the projection engine (A8) may emit when it degrades a
# section. The intelligence-projection registry's ``sectionStates`` vocab MUST
# be a superset of this set (validate_degradation_vocab) so the engine can map
# every degradation onto a registered state without inventing a parallel vocab.
ENGINE_SECTION_STATES = frozenset(
    {
        "available",
        "empty",
        "missing",
        "degraded",
        "not_applicable",
        "unknown",
        "suppressed",
        "stale",
    }
)


@dataclass
class Violation:
    """One validator finding.

    ``rule`` is the rule-group id (registry_schema / dependency_dag /
    cross_registry / inventory / ownership / surface_honesty / metric_honesty /
    order_resilience). ``severity`` is ``"error"`` (gates CI) or ``"warning"``.
    ``projection`` names the offending projection id (``None`` for top-level
    findings). ``message`` is human-readable and actionable.
    """

    rule: str
    severity: str
    message: str
    projection: Optional[str] = None

    def __str__(self) -> str:  # pragma: no cover - debug/CLI convenience
        scope = self.projection or "<registry>"
        return f"[{self.rule}:{self.severity}] {scope}: {self.message}"


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _backend_py_paths() -> tuple[str, ...]:
    """Repo-relative paths of every ``*.py`` under the backend (sorted)."""
    backend = ROOT / "services" / "api"
    rels = sorted(
        str(p.relative_to(ROOT)) for p in backend.rglob("*.py") if p.is_file()
    )
    return tuple(rels)


@functools.lru_cache(maxsize=1)
def _backend_route_strings() -> frozenset[str]:
    """Every ``/v1/...`` path literal on a ROUTE-DECLARATION line in backend
    Python source, plus each of its segment prefixes.

    Only lines carrying a route-declaration marker count — ``APIRouter(``,
    ``include_router(``, an ``@router.``/``@app.`` decorator, ``add_api_route(``
    or ``prefix=``. A ``/v1/...`` string that appears in a test assertion,
    config literal or docstring is NOT evidence of a mounted route and must not
    let a fictional legacy binding through the inventory gate. The genuinely
    mounted but feature-flag-gated routers (``/v1/risk-overlays``,
    ``/v1/integrations``, ``/v1/provider-connections``, ``/v1/client-sync``,
    ``/v1/agent``) are all declared this way — sometimes only as the prefix of
    a longer literal (e.g. ``/v1/integrations`` appears as
    ``/v1/integrations/connectors``), which is why every segment prefix of a
    matched declaration line is indexed.
    """
    found: set[str] = set()
    for rel in _backend_py_paths():
        try:
            content = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in content.splitlines():
            if not _ROUTE_DECL_LINE_RE.search(line):
                continue
            for match in _ROUTE_FRAGMENT_RE.findall(line):
                prefix = ""
                for part in match.split("/")[1:]:
                    prefix += "/" + part
                    found.add(prefix)
    return frozenset(found)


def load_context() -> dict:
    """Load the cross-registry context once.

    Returns ``{surface_ids, surface_temporal_modes, metric_names,
    graph_mutation_types, route_prefixes, backend_source_paths,
    lens_registry, outcome_registry}``:
    - ``surface_ids`` / ``surface_temporal_modes`` from
      ``packages/shared/contracts/surface-capability-registry.json``;
    - ``metric_names`` from ``packages/shared/contracts/metric-registry.json``;
    - ``graph_mutation_types`` from
      ``packages/shared/contracts/graph-mutation-registry.json``;
    - ``route_prefixes`` (the ``known_prefixes`` list) from
      ``config/route_registry.yaml`` (pyyaml);
    - ``backend_source_paths`` — repo-relative paths of every ``*.py`` under
      ``services/api`` (route-existence source grep);
    - ``lens_registry`` — the parsed projection-engine lens registry
      (``packages/shared/contracts/lens-registry.json``), validated by the
      ``lens_registry`` rule group (A8);
    - ``outcome_registry`` — the parsed Outcome360 outcome-type registry
      (``packages/shared/contracts/outcome-type-registry.json``), validated by
      the ``outcome_registry`` rule group.
    """
    import yaml

    surface_reg = json.loads(
        (ROOT / "packages/shared/contracts/surface-capability-registry.json").read_text(
            encoding="utf-8"
        )
    )
    metric_reg = json.loads(
        (ROOT / "packages/shared/contracts/metric-registry.json").read_text(
            encoding="utf-8"
        )
    )
    mutation_reg = json.loads(
        (ROOT / "packages/shared/contracts/graph-mutation-registry.json").read_text(
            encoding="utf-8"
        )
    )
    route_cfg = yaml.safe_load(
        (ROOT / "config/route_registry.yaml").read_text(encoding="utf-8")
    )
    lens_reg = json.loads(
        (ROOT / "packages/shared/contracts/lens-registry.json").read_text(
            encoding="utf-8"
        )
    )
    outcome_reg = json.loads(
        (ROOT / "packages/shared/contracts/outcome-type-registry.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "surface_ids": {s["surfaceId"] for s in surface_reg["surfaces"]},
        "surface_temporal_modes": {
            s["surfaceId"]: set(s["supportedTemporalModes"])
            for s in surface_reg["surfaces"]
        },
        "metric_names": {m["name"] for m in metric_reg["metrics"]},
        "graph_mutation_types": set(mutation_reg["mutationTypes"]),
        "route_prefixes": set(route_cfg["known_prefixes"]),
        "backend_source_paths": set(_backend_py_paths()),
        "lens_registry": lens_reg,
        "outcome_registry": outcome_reg,
    }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _routes(reg: dict) -> list[tuple[str, str]]:
    """Flatten every legacy binding route as ``(projection_id, route)``."""
    out: list[tuple[str, str]] = []
    for p in reg.get("projections", []):
        for route in (p.get("legacyBindings") or {}).get("routes", []):
            out.append((p["id"], route))
    return out


def _dependencies(reg: dict) -> dict[str, set[str]]:
    """Projection-id -> required projection dependencies (cycle graph)."""
    return {
        p["id"]: set(p.get("projectionDependencies", []))
        for p in reg.get("projections", [])
    }


def _prefix2(route: str) -> str:
    """First two path segments, e.g. ``/v1/foo/bar`` -> ``/v1/foo``."""
    parts = [part for part in route.split("/") if part]
    if len(parts) >= 2:
        return "/" + parts[0] + "/" + parts[1]
    return route


def _well_formed_route(route: str) -> bool:
    return bool(_ROUTE_FULL_RE.fullmatch(route))


def _route_resolves(route: str, ctx: dict) -> bool:
    """A legacy route resolves if its 2-segment prefix is a known route prefix,
    or if the full path string appears in backend Python source (the OR rule
    for feature-flag-gated routers absent from route_registry.yaml)."""
    if _prefix2(route) in ctx.get("route_prefixes", set()):
        return True
    return route in _backend_route_strings()


def _find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """DFS cycle detection returning a representative cycle path per SCC."""
    cycles: list[list[str]] = []
    visited: set[str] = set()
    stack: list[str] = []
    on_stack: set[str] = set()

    def visit(node: str) -> None:
        visited.add(node)
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(edges.get(node, ())):
            if nxt in on_stack:
                start = stack.index(nxt)
                cycles.append(stack[start:])
            elif nxt not in visited:
                visit(nxt)
        stack.pop()
        on_stack.discard(node)

    for node in sorted(edges):
        if node not in visited:
            visit(node)

    unique: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for cycle in cycles:
        key = tuple(sorted(cycle))
        if key not in seen:
            seen.add(key)
            unique.append(cycle)
    return unique


def _cycle_has_optional_edge(cycle: list[str], optional_edges: dict[str, set[str]]) -> bool:
    """True if any edge of the cycle is an optional projection dependency."""
    for i in range(len(cycle)):
        src = cycle[i]
        dst = cycle[(i + 1) % len(cycle)]
        if dst in optional_edges.get(src, set()):
            return True
    return False


def _format_optional_cycle_path(cycle: list[str], optional_edges: dict[str, set[str]]) -> str:
    """Render a cycle path with an ``(optional)`` marker on each optional edge.

    The marker sits on the destination node of the optional edge, e.g. for a
    cycle ``r -> e -> r`` whose ``r -> e`` edge is optional:
    ``r -> e(optional) -> r``.
    """
    segments = [cycle[0]]
    for i in range(len(cycle)):
        src = cycle[i]
        dst = cycle[(i + 1) % len(cycle)]
        if dst in optional_edges.get(src, set()):
            segments.append(f"{dst}(optional)")
        else:
            segments.append(dst)
    return " -> ".join(segments)


def _pending_ids(p: dict) -> set[str]:
    return {d.get("id") for d in p.get("pendingAuthority", [])} | {
        d.get("id") for d in p.get("pendingReference", [])
    }


def _pending_decls(p: dict) -> list[dict]:
    return list(p.get("pendingAuthority", [])) + list(p.get("pendingReference", []))


# ---------------------------------------------------------------------------
# Rule groups
# ---------------------------------------------------------------------------


def validate_registry_schema(reg: dict) -> list[Violation]:
    """Registry-integrity rules (rule group ``registry_schema``)."""
    violations: list[Violation] = []

    for key in ("schemaVersion", "contractVersion"):
        if not isinstance(reg.get(key), str) or not reg.get(key):
            violations.append(
                Violation("registry_schema", "error", f"top-level {key!r} missing or empty")
            )

    for vocab in _VOCAB_FIELDS:
        values = reg.get(vocab)
        if not isinstance(values, list) or not values:
            violations.append(
                Violation("registry_schema", "error", f"vocab array {vocab!r} missing or empty")
            )
            continue
        if not all(isinstance(v, str) and _LOWER_SNAKE_RE.fullmatch(v) for v in values):
            violations.append(
                Violation("registry_schema", "error", f"vocab array {vocab!r} contains non-lower_snake idents")
            )
        if len(set(values)) != len(values):
            violations.append(
                Violation("registry_schema", "error", f"vocab array {vocab!r} contains duplicates")
            )

    projections = reg.get("projections")
    if not isinstance(projections, list) or not projections:
        return [
            Violation("registry_schema", "error", "projections array missing or empty")
        ]

    ids = [p.get("id") for p in projections]
    id_set = {i for i in ids if isinstance(i, str)}
    if len(set(ids)) != len(ids):
        violations.append(
            Violation("registry_schema", "error", "projection ids must be unique")
        )
    for pid in ids:
        if not isinstance(pid, str) or not _LOWER_SNAKE_RE.fullmatch(pid):
            violations.append(
                Violation("registry_schema", "error", f"id {pid!r} must be lower_snake")
            )

    projection_kinds = set(reg.get("projectionKinds", []))
    implementation_states = set(reg.get("implementationStates", []))
    graph_policies = set(reg.get("graphMutationPolicies", []))
    migration_modes = set(reg.get("migrationModes", []))
    temporal_modes = set(reg.get("temporalModes", []))
    subject_kinds = set(reg.get("subjectKinds", []))

    for p in projections:
        pid = p.get("id")
        for field in _REQUIRED_ENTRY_FIELDS:
            if field not in p:
                violations.append(
                    Violation("registry_schema", "error", f"missing required field {field!r}", pid)
                )
        for field in _STR_FIELDS:
            if field in p and not isinstance(p[field], str):
                violations.append(
                    Violation("registry_schema", "error", f"{field!r} must be a string", pid)
                )
        for field in _BOOL_FIELDS:
            if field in p and not isinstance(p[field], bool):
                violations.append(
                    Violation("registry_schema", "error", f"{field!r} must be a boolean", pid)
                )
        for field in _LIST_FIELDS:
            value = p.get(field)
            if value is not None and (
                not isinstance(value, list)
                or not all(isinstance(v, str) for v in value)
            ):
                violations.append(
                    Violation("registry_schema", "error", f"{field!r} must be a list of strings", pid)
                )
        for field in _DICT_FIELDS:
            if field in p and not isinstance(p[field], dict):
                violations.append(
                    Violation("registry_schema", "error", f"{field!r} must be an object", pid)
                )

        if p.get("ownsCanonicalTruth") is not False:
            violations.append(
                Violation(
                    "registry_schema",
                    "error",
                    "ownsCanonicalTruth must be False (a 360 is never a competing system of record)",
                    pid,
                )
            )

        if p.get("projectionKind") not in projection_kinds:
            violations.append(
                Violation("registry_schema", "error", f"unknown projectionKind {p.get('projectionKind')!r}", pid)
            )
        if p.get("implementationState") not in implementation_states:
            violations.append(
                Violation("registry_schema", "error", f"unknown implementationState {p.get('implementationState')!r}", pid)
            )
        if p.get("graphMutationPolicy") not in graph_policies:
            violations.append(
                Violation("registry_schema", "error", f"unknown graphMutationPolicy {p.get('graphMutationPolicy')!r}", pid)
            )
        bindings = p.get("legacyBindings") or {}
        if bindings.get("migrationMode") not in migration_modes:
            violations.append(
                Violation("registry_schema", "error", f"unknown migrationMode {bindings.get('migrationMode')!r}", pid)
            )
        for kind in p.get("subjectKinds", []):
            if kind not in subject_kinds:
                violations.append(
                    Violation("registry_schema", "error", f"unknown subjectKind {kind!r}", pid)
                )
        for mode in p.get("supportedTemporalModes", []):
            if mode not in temporal_modes:
                violations.append(
                    Violation("registry_schema", "error", f"unknown temporalMode {mode!r}", pid)
                )
        for ref in p.get("inputRefs", []):
            if ref not in INPUT_REF_INDEX:
                violations.append(
                    Violation("registry_schema", "error", f"inputRef {ref!r} not in INPUT_REF_INDEX", pid)
                )
        for section in p.get("outputSections", []):
            if section not in _OUTPUT_SECTIONS:
                violations.append(
                    Violation("registry_schema", "error", f"outputSection {section!r} not in the curated set", pid)
                )

        for decl in _pending_decls(p):
            if not isinstance(decl, dict) or any(
                k not in decl for k in _PENDING_REQUIRED_KEYS
            ):
                violations.append(
                    Violation(
                        "registry_schema",
                        "error",
                        "pending declaration must be {id, kind, reason, resolvesInProjection}",
                        pid,
                    )
                )
                continue
            kind = decl.get("kind")
            if kind not in _PENDING_KINDS:
                violations.append(
                    Violation(
                        "registry_schema",
                        "error",
                        f"pending kind {kind!r} must be one of {sorted(_PENDING_KINDS)}",
                        pid,
                    )
                )
            resolves = decl.get("resolvesInProjection")
            if (
                not isinstance(resolves, str)
                or not _LOWER_SNAKE_RE.fullmatch(resolves)
                or resolves not in id_set
            ):
                violations.append(
                    Violation(
                        "registry_schema",
                        "error",
                        f"pending resolvesInProjection {resolves!r} must be a registry projection id",
                        pid,
                    )
                )

    return violations


def validate_dependency_dag(reg: dict) -> list[Violation]:
    """Dependency-DAG rules (rule group ``dependency_dag``)."""
    violations: list[Violation] = []
    projections = reg.get("projections", [])
    ids = {p.get("id") for p in projections}

    for p in projections:
        pid = p.get("id")
        # A projection dependency may count as declared-pending ONLY via a
        # pending entry whose kind namespaces the projection id space
        # (kind=="projection"). A kind:"metric"/"spine" pending that happens to
        # carry the same id does not declare a projection dep pending.
        declared = {
            d.get("id")
            for d in _pending_decls(p)
            if d.get("kind") == "projection"
        }
        for dep in list(p.get("projectionDependencies", [])) + list(
            p.get("optionalProjectionDependencies", [])
        ):
            if dep == pid:
                violations.append(
                    Violation("dependency_dag", "error", f"self-dependency on {pid!r}", pid)
                )
            elif dep not in ids and dep not in declared:
                violations.append(
                    Violation(
                        "dependency_dag",
                        "error",
                        f"dependency {dep!r} is neither a registry id nor declared pending",
                        pid,
                    )
                )

    required_edges = _dependencies(reg)
    optional_edges = {
        p.get("id"): set(p.get("optionalProjectionDependencies", []))
        for p in projections
    }

    # Required-projection cycles are ordering deadlocks → error: a required
    # cycle means neither projection can ever implement.
    for cycle in _find_cycles(required_edges):
        path = " -> ".join(cycle + [cycle[0]])
        violations.append(
            Violation("dependency_dag", "error", f"dependency cycle: {path}", cycle[0])
        )

    # Union cycles (required ∪ optional) that exist only through an optional
    # edge are benign → warning: the lazy runtime degrades missing optional deps
    # to not_applicable, so a union cycle is never an ordering deadlock. Each
    # warning labels the optional edge(s) with an ``(optional)`` marker.
    union_edges = {
        pid: set(required_edges.get(pid, ())) | set(optional_edges.get(pid, ()))
        for pid in ids
    }
    for cycle in _find_cycles(union_edges):
        if not _cycle_has_optional_edge(cycle, optional_edges):
            continue  # fully-required cycle already reported as an error above
        path = _format_optional_cycle_path(cycle, optional_edges)
        violations.append(
            Violation(
                "dependency_dag",
                "warning",
                f"dependency cycle (via optional edge): {path}",
                cycle[0],
            )
        )

    for p in projections:
        pid = p.get("id")
        if p.get("implementationState") != "implemented":
            continue
        if _pending_decls(p):
            violations.append(
                Violation(
                    "dependency_dag",
                    "error",
                    "implemented projection must have zero pending declarations",
                    pid,
                )
            )
        unresolved = [
            d
            for d in list(p.get("projectionDependencies", []))
            + list(p.get("optionalProjectionDependencies", []))
            if d not in ids
        ]
        if unresolved:
            violations.append(
                Violation(
                    "dependency_dag",
                    "error",
                    f"implemented projection has unresolved dependencies: {unresolved}",
                    pid,
                )
            )

    for p in projections:
        pid = p.get("id")
        for decl in _pending_decls(p):
            target = decl.get("id")
            # Kind-label-immune dangling ratchet: a pending declaration is
            # dangling the moment its target resolves in the spine or projection
            # id space, REGARDLESS of the declared ``kind``. Relabelling a
            # now-resolved projection as kind:"spine" (or a resolved spine as
            # kind:"projection") must not dodge the ratchet.
            if target in SPINE_INDEX:
                violations.append(
                    Violation(
                        "order_resilience",
                        "error",
                        f"dangling pending spine {target!r}: now resolved in the canonical spine registry — remove the declaration",
                        pid,
                    )
                )
            elif target in ids:
                violations.append(
                    Violation(
                        "order_resilience",
                        "error",
                        f"dangling pending projection {target!r}: target now exists in the registry — remove the declaration",
                        pid,
                    )
                )
            elif decl.get("kind") == "spine" and target not in PENDING_SPINE_INDEX:
                violations.append(
                    Violation(
                        "order_resilience",
                        "error",
                        f"undeclared pending spine {target!r}: the spine plane's vocabulary is spine-registry.json — formalize it there as a \"pending\" row (with reason + resolving milestone) or correct the declaration",
                        pid,
                    )
                )

    return violations


def validate_cross_registry(reg: dict, ctx: dict) -> list[Violation]:
    """Cross-registry resolution rules (rule group ``cross_registry``)."""
    violations: list[Violation] = []
    surface_ids = ctx.get("surface_ids", set())
    surface_modes = ctx.get("surface_temporal_modes", {})
    metric_names = ctx.get("metric_names", set())
    mutation_types = ctx.get("graph_mutation_types", set())
    policies = set(reg.get("graphMutationPolicies", []))

    for p in reg.get("projections", []):
        pid = p.get("id")
        state = p.get("implementationState")
        # Kind-namespaced declared sets: a surfaceId may be declared pending
        # only via a kind=="surface" pending; a metricRef only via kind=="metric".
        surface_declared = {
            d.get("id")
            for d in _pending_decls(p)
            if d.get("kind") == "surface"
        }
        metric_declared = {
            d.get("id")
            for d in _pending_decls(p)
            if d.get("kind") == "metric"
        }

        for surface in p.get("surfaceIds", []):
            if surface in surface_ids:
                continue
            if surface in surface_declared:
                if state == "implemented":
                    violations.append(
                        Violation(
                            "order_resilience",
                            "error",
                            f"implemented projection declares pending surface {surface!r}",
                            pid,
                        )
                    )
                continue
            violations.append(
                Violation(
                    "cross_registry",
                    "error",
                    f"surfaceId {surface!r} is neither a registered surface nor declared pending",
                    pid,
                )
            )

        known_modes: set[str] = set()
        for surface in p.get("surfaceIds", []):
            if surface in surface_modes:
                known_modes |= set(surface_modes[surface])
        if known_modes:
            for mode in p.get("supportedTemporalModes", []):
                if mode not in known_modes:
                    violations.append(
                        Violation(
                            "cross_registry",
                            "error",
                            f"temporal mode {mode!r} is not supported by any of the projection's surfaces",
                            pid,
                        )
                    )

        for metric in p.get("metricRefs", []):
            if metric in metric_names:
                continue
            if metric in metric_declared:
                if state == "implemented":
                    violations.append(
                        Violation(
                            "order_resilience",
                            "error",
                            f"implemented projection declares pending metric {metric!r}",
                            pid,
                        )
                    )
                continue
            violations.append(
                Violation(
                    "cross_registry",
                    "error",
                    f"metricRef {metric!r} is neither in metric-registry.json nor declared pending",
                    pid,
                )
            )

        for key in p.get("capabilityKeys", []):
            prefix, sep, verb = key.partition(".")
            if sep != "." or prefix != pid or verb not in PROJECTION_CAPABILITY_VERBS:
                violations.append(
                    Violation(
                        "cross_registry",
                        "error",
                        f"malformed capabilityKey {key!r}: expected {pid!r}.<verb> "
                        f"with verb in {sorted(PROJECTION_CAPABILITY_VERBS)}",
                        pid,
                    )
                )

        policy = p.get("graphMutationPolicy")
        if policy not in policies:
            violations.append(
                Violation("cross_registry", "error", f"unknown graphMutationPolicy {policy!r}", pid)
            )
        elif policy == "canonical_gateway_only" and not mutation_types:
            violations.append(
                Violation(
                    "cross_registry",
                    "error",
                    "canonical_gateway_only requires a non-empty graph-mutation registry",
                    pid,
                )
            )

        for decl in _pending_decls(p):
            target = decl.get("id")
            # Kind-label-immune dangling ratchet over the metric/surface id
            # spaces: a pending entry is dangling once its target resolves in
            # either namespace, regardless of the declared ``kind``. Relabelling
            # a resolved metric as kind:"surface" (or vice-versa) cannot dodge
            # it. (Spine/projection ratchets live in validate_dependency_dag.)
            if target in metric_names:
                violations.append(
                    Violation(
                        "order_resilience",
                        "error",
                        f"dangling pending metric {target!r}: now in metric-registry.json — remove the declaration",
                        pid,
                    )
                )
            elif target in surface_ids:
                violations.append(
                    Violation(
                        "order_resilience",
                        "error",
                        f"dangling pending surface {target!r}: now in the surface registry — remove the declaration",
                        pid,
                    )
                )

    return violations


def validate_inventory(reg: dict, ctx: dict) -> list[Violation]:
    """Inventory-honesty rules (rule group ``inventory``).

    Every ``in_flight`` projection's legacyBindings must resolve against real
    routes, surfaces and services — no fictional claims about existing work.
    """
    violations: list[Violation] = []
    surface_ids = ctx.get("surface_ids", set())

    for p in reg.get("projections", []):
        pid = p.get("id")
        state = p.get("implementationState")
        bindings = p.get("legacyBindings") or {}

        if state == "in_flight":
            if not bindings:
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        "in_flight projection requires non-empty legacyBindings",
                        pid,
                    )
                )
                continue
            for route in bindings.get("routes", []):
                if not _well_formed_route(route):
                    violations.append(
                        Violation(
                            "inventory",
                            "error",
                            f"legacy route {route!r} is not a well-formed /v1/... path",
                            pid,
                        )
                    )
                elif not _route_resolves(route, ctx):
                    violations.append(
                        Violation(
                            "inventory",
                            "error",
                            f"legacy route {route!r} has no known prefix in route_registry.yaml "
                            "and was not found in backend source",
                            pid,
                        )
                    )
            for surface in bindings.get("surfaceIds", []):
                if surface not in surface_ids:
                    violations.append(
                        Violation(
                            "inventory",
                            "error",
                            f"legacy binding surface {surface!r} is not a registered surface",
                            pid,
                        )
                    )
            for service in bindings.get("services", []):
                if not (ROOT / service).exists():
                    violations.append(
                        Violation(
                            "inventory",
                            "error",
                            f"legacy service path {service!r} does not exist on disk",
                            pid,
                        )
                    )
        elif state == "registered":
            if not p.get("implementationBlueprint"):
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        "registered projection requires a non-empty implementationBlueprint",
                        pid,
                    )
                )
        elif state == "implemented":
            if bindings.get("migrationMode") != "converged":
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        "implemented projection requires legacyBindings.migrationMode == 'converged'",
                        pid,
                    )
                )
            if _pending_decls(p):
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        "implemented projection must have zero pending declarations",
                        pid,
                    )
                )
            blueprint = p.get("implementationBlueprint")
            if isinstance(blueprint, str) and not (ROOT / blueprint).exists():
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        f"implementationBlueprint {blueprint!r} does not exist on disk",
                        pid,
                    )
                )
        elif state == "deprecated":
            if not p.get("deprecatedReason"):
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        "deprecated projection requires deprecatedReason",
                        pid,
                    )
                )

        if state != "deprecated":
            blueprint = p.get("implementationBlueprint")
            if not (
                isinstance(blueprint, str)
                and blueprint.startswith("docs/")
                and blueprint.endswith(".md")
                and len(blueprint) > len("docs/")
            ):
                violations.append(
                    Violation(
                        "inventory",
                        "error",
                        f"implementationBlueprint {blueprint!r} must be a non-empty .md path under docs/",
                        pid,
                    )
                )

    return violations


def validate_ownership(reg: dict) -> list[Violation]:
    """Ownership-integrity rules (rule group ``ownership``)."""
    violations: list[Violation] = []
    for p in reg.get("projections", []):
        pid = p.get("id")
        declared = _pending_ids(p)
        for authority in p.get("canonicalAuthorities", []):
            if authority == "projector-ownership":
                violations.append(
                    Violation(
                        "ownership",
                        "error",
                        "projector-ownership-registry may be an inputRef but never a canonical authority",
                        pid,
                    )
                )
            elif authority not in AUTHORITY_INDEX and authority not in declared:
                violations.append(
                    Violation(
                        "ownership",
                        "error",
                        f"canonical authority {authority!r} is not in AUTHORITY_INDEX nor declared pending",
                        pid,
                    )
                )
    return violations


def validate_surface_honesty(reg: dict, ctx: dict) -> list[Violation]:
    """Surface-honesty rules (rule group ``surface_honesty``)."""
    violations: list[Violation] = []
    surface_ids = ctx.get("surface_ids", set())
    for p in reg.get("projections", []):
        pid = p.get("id")
        surface_ids_list = p.get("surfaceIds", [])
        if not surface_ids_list:
            violations.append(
                Violation("surface_honesty", "error", "surfaceIds must be non-empty", pid)
            )
        if p.get("implementationState") == "in_flight":
            bindings = p.get("legacyBindings") or {}
            resolved = {s for s in surface_ids_list if s in surface_ids}
            bound = set(bindings.get("surfaceIds", []))
            extra = resolved - bound
            if extra:
                violations.append(
                    Violation(
                        "surface_honesty",
                        "error",
                        f"resolved surfaces {sorted(extra)} are not declared in legacyBindings.surfaceIds",
                        pid,
                    )
                )
    return violations


def validate_metric_honesty(reg: dict, ctx: dict) -> list[Violation]:
    """Metric-honesty rules (rule group ``metric_honesty``)."""
    violations: list[Violation] = []
    for p in reg.get("projections", []):
        pid = p.get("id")
        if p.get("projectionKind") in _MEASUREMENT_OR_RISK_KINDS and p.get("metricRefs"):
            if p.get("requiresEvidence") is not True:
                violations.append(
                    Violation(
                        "metric_honesty",
                        "error",
                        "measurement/risk projection with metricRefs must set requiresEvidence=True",
                        pid,
                    )
                )
            if p.get("requiresLimitations") is not True:
                violations.append(
                    Violation(
                        "metric_honesty",
                        "error",
                        "measurement/risk projection with metricRefs must set requiresLimitations=True",
                        pid,
                    )
                )
    return violations


def validate_degradation_vocab(reg: dict) -> list[Violation]:
    """Degradation-vocabulary rule (rule group ``degradation_vocab``, A8).

    The projection-engine (A8) maps every degradation onto a registered
    SectionState. The registry's ``sectionStates`` vocab MUST be a superset of
    the engine's ``ENGINE_SECTION_STATES`` — otherwise the engine would invent
    a parallel section-state vocabulary, violating the single-vocab doctrine.
    """
    missing = sorted(ENGINE_SECTION_STATES - set(reg.get("sectionStates", ())))
    if not missing:
        return []
    return [
        Violation(
            "degradation_vocab",
            "error",
            "registry sectionStates must include every engine-emittable state; "
            f"missing {missing}",
            None,
        )
    ]


def validate_lens_registry(reg: dict, ctx: dict) -> list[Violation]:
    """Projection-engine lens-registry rules (rule group ``lens_registry``, A8).

    Validates the canonical lens registry (packages/shared/contracts/lens-registry.json)
    held in ``ctx["lens_registry"]``:

    * every lens ``kind`` is in ``{base, overlay}`` (and within the registry's
      declared ``lensKinds`` vocab);
    * ids are unique and lower-snake;
    * required fields are present;
    * an ``overlay`` declares a ``baseLens`` that resolves to a DIFFERENT lens
      id; a ``base`` declares ``baseLens: null``;
    * exactly one lens is ``default: true``, and it must be a ``base`` lens.
    """
    violations: list[Violation] = []
    # ``reg`` may BE the lens registry (generator path — validate the dict
    # about to be emitted) or the intelligence-projection registry (validator
    # path — validate the lens registry from cross-registry context).
    lens_reg = reg if isinstance(reg, dict) and reg.get("lenses") else ctx.get("lens_registry")
    if not lens_reg:
        return [
            Violation(
                "lens_registry",
                "error",
                "no lens registry in cross-registry context (load_context must "
                "load packages/shared/contracts/lens-registry.json)",
                None,
            )
        ]

    declared_kinds = set(lens_reg.get("lensKinds", ()))
    lenses = lens_reg.get("lenses", [])
    # Complete id map FIRST so an overlay may base on a lens declared later in
    # the array (id resolution must be order-independent).
    all_ids = [l.get("id") for l in lenses if l.get("id")]
    if len(all_ids) != len(set(all_ids)):
        seen: set[str] = set()
        for lid in all_ids:
            if lid in seen:
                violations.append(
                    Violation("lens_registry", "error", f"duplicate lens id {lid!r}", None)
                )
            seen.add(lid)
    ids: dict[str, dict] = {l.get("id"): l for l in lenses if l.get("id")}
    for lens in lenses:
        lid = lens.get("id")
        kind = lens.get("kind")
        for field in _LENS_REQUIRED_FIELDS:
            if field not in lens:
                violations.append(
                    Violation(
                        "lens_registry",
                        "error",
                        f"lens {lid!r} is missing required field {field!r}",
                        None,
                    )
                )
        if not _LOWER_SNAKE_RE.fullmatch(lid or ""):
            violations.append(
                Violation(
                    "lens_registry",
                    "error",
                    f"lens id {lid!r} must be lower-snake",
                    None,
                )
            )
        if kind not in _LENS_KINDS:
            violations.append(
                Violation(
                    "lens_registry",
                    "error",
                    f"lens {lid!r} kind {kind!r} must be in {sorted(_LENS_KINDS)}",
                    None,
                )
            )
            continue
        if kind not in declared_kinds:
            violations.append(
                Violation(
                    "lens_registry",
                    "error",
                    f"lens {lid!r} kind {kind!r} is not declared in lensKinds "
                    f"{sorted(declared_kinds)}",
                    None,
                )
            )
        if kind == "base":
            if lens.get("baseLens") is not None:
                violations.append(
                    Violation(
                        "lens_registry",
                        "error",
                        f"base lens {lid!r} must declare baseLens null",
                        None,
                    )
                )
        else:  # overlay
            base = lens.get("baseLens")
            if base is None:
                violations.append(
                    Violation(
                        "lens_registry",
                        "error",
                        f"overlay lens {lid!r} must declare a baseLens",
                        None,
                    )
                )
            elif base == lid:
                violations.append(
                    Violation(
                        "lens_registry",
                        "error",
                        f"overlay lens {lid!r} must not base on itself",
                        None,
                    )
                )
            elif base not in ids:
                violations.append(
                    Violation(
                        "lens_registry",
                        "error",
                        f"overlay lens {lid!r} baseLens {base!r} does not resolve to "
                        "a registered lens",
                        None,
                    )
                )
        if lens.get("default") is True and kind != "base":
            violations.append(
                Violation(
                    "lens_registry",
                    "error",
                    f"only a base lens may be default: true (offending: {lid!r})",
                    None,
                )
            )

    defaults = [l for l in lenses if l.get("default") is True]
    if len(defaults) != 1:
        violations.append(
            Violation(
                "lens_registry",
                "error",
                "exactly one lens must be default: true "
                f"(found {len(defaults)}: {sorted(l.get('id') for l in defaults)})",
                None,
            )
        )
    return violations


# ── Outcome-type registry (Outcome360) ─────────────────────────────────────

_OUTCOME_DOMAIN_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


def validate_outcome_registry(reg: dict, ctx: Optional[dict] = None) -> list[Violation]:
    """Outcome-type registry rules (rule group ``outcome_registry``, Outcome360).

    Dual-path like ``validate_lens_registry``: when ``reg`` is the outcome-type
    registry itself (generator REGISTRIES loop) it is validated directly;
    otherwise it falls back to ``ctx["outcome_registry"]`` (standalone
    projection-registry validation). Rules:

    * ``schemaVersion`` must be 1 and ``contractVersion`` a non-empty string;
    * ``domains`` is a non-empty list of unique lower-snake ids;
    * ``outcomeTypes`` is a non-empty list; every entry carries non-empty
      ``id`` / ``domain`` / ``name`` / ``description``;
    * outcome-type ids are unique and lower-snake, ordered by ``id`` ascending
      (order-stable generation);
    * every ``domain`` resolves within ``domains`` and every declared domain
      has at least one outcome type (full coverage).
    """
    outcome_reg = (
        reg
        if isinstance(reg, dict) and reg.get("outcomeTypes")
        else ((ctx or {}).get("outcome_registry"))
    )
    if not outcome_reg:
        return [
            Violation(
                "outcome_registry",
                "error",
                "no outcome-type registry in cross-registry context "
                "(load_context must load packages/shared/contracts/outcome-type-registry.json)",
                None,
            )
        ]
    violations: list[Violation] = []

    if outcome_reg.get("schemaVersion") != 1:
        violations.append(
            Violation("outcome_registry", "error", "schemaVersion must be 1", None)
        )
    contract_version = outcome_reg.get("contractVersion")
    if not isinstance(contract_version, str) or not contract_version:
        violations.append(
            Violation(
                "outcome_registry", "error", "contractVersion must be a non-empty string", None
            )
        )

    domains = outcome_reg.get("domains", [])
    if not isinstance(domains, list) or not domains:
        violations.append(
            Violation("outcome_registry", "error", "domains must be a non-empty list", None)
        )
        domains = []
    seen_domains: set[str] = set()
    for d in domains:
        if not isinstance(d, str) or not _OUTCOME_DOMAIN_RE.fullmatch(d):
            violations.append(
                Violation("outcome_registry", "error", f"domain {d!r} is not lower_snake", None)
            )
        if d in seen_domains:
            violations.append(
                Violation("outcome_registry", "error", f"duplicate domain {d!r}", None)
            )
        seen_domains.add(d)

    types = outcome_reg.get("outcomeTypes", [])
    if not isinstance(types, list) or not types:
        violations.append(
            Violation("outcome_registry", "error", "outcomeTypes must be a non-empty list", None)
        )
        types = []
    seen_ids: set[str] = set()
    ids_in_order: list[str] = []
    covered: set[str] = set()
    for t in types:
        if not isinstance(t, dict):
            violations.append(
                Violation("outcome_registry", "error", "each outcomeType must be an object", None)
            )
            continue
        tid = t.get("id")
        if not isinstance(tid, str) or not _OUTCOME_DOMAIN_RE.fullmatch(tid):
            violations.append(
                Violation("outcome_registry", "error", f"outcomeType id {tid!r} is not lower_snake", None)
            )
        if tid in seen_ids:
            violations.append(
                Violation("outcome_registry", "error", f"duplicate outcomeType id {tid!r}", None)
            )
        seen_ids.add(tid)
        for field in ("id", "domain", "name", "description"):
            if not isinstance(t.get(field), str) or not t[field]:
                violations.append(
                    Violation(
                        "outcome_registry",
                        "error",
                        f"outcomeType {tid!r} missing required field {field!r}",
                        None,
                    )
                )
        domain = t.get("domain")
        if domain not in seen_domains:
            violations.append(
                Violation(
                    "outcome_registry",
                    "error",
                    f"outcomeType {tid!r} domain {domain!r} not in domains",
                    None,
                )
            )
        else:
            covered.add(domain)
        ids_in_order.append(tid)

    if ids_in_order != sorted(ids_in_order):
        violations.append(
            Violation(
                "outcome_registry",
                "error",
                "outcomeTypes must be sorted by id ascending (order-stable generation)",
                None,
            )
        )
    missing = sorted(seen_domains - covered)
    if missing:
        violations.append(
            Violation(
                "outcome_registry",
                "error",
                f"domains with no outcome type: {', '.join(missing)}",
                None,
            )
        )
    return violations


def validate_product_surface_catalog(reg: dict) -> list[Violation]:
    """Validate the 18-product 360 catalog and its projection crosswalk.

    Product surfaces are a distinct catalog from technical projection
    providers. ``catalog_only`` bindings state only that an explicit mapping
    exists; provider implementation metadata is copied from the projection
    registry and is not a readiness claim.
    """
    violations: list[Violation] = []
    version = reg.get("productSurfaceCatalogVersion")
    if not isinstance(version, str) or not version:
        violations.append(
            Violation(
                "product_surface_catalog",
                "error",
                "productSurfaceCatalogVersion must be a non-empty string",
            )
        )

    frame_states = reg.get("experience360FrameStates")
    if (
        not isinstance(frame_states, list)
        or not all(isinstance(state, str) for state in frame_states)
        or set(frame_states) != EXPERIENCE_360_FRAME_STATES
    ):
        violations.append(
            Violation(
                "product_surface_catalog",
                "error",
                "experience360FrameStates must contain the canonical frame lifecycle states",
            )
        )

    surfaces = reg.get("productSurfaces")
    if not isinstance(surfaces, list) or not surfaces:
        return violations + [
            Violation(
                "product_surface_catalog",
                "error",
                "productSurfaces must be a non-empty catalog array",
            )
        ]

    projections_raw = reg.get("projections")
    projections = {
        row.get("id"): row
        for row in projections_raw
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    } if isinstance(projections_raw, list) else {}
    surface_ids = [row.get("id") if isinstance(row, dict) else None for row in surfaces]
    valid_ids = {item for item in surface_ids if isinstance(item, str)}
    if len(valid_ids) != len(surfaces):
        violations.append(
            Violation(
                "product_surface_catalog",
                "error",
                "product surface ids must be strings and unique",
            )
        )
    if valid_ids != EXPECTED_PRODUCT_360_SURFACE_IDS or len(surfaces) != 18:
        violations.append(
            Violation(
                "product_surface_catalog",
                "error",
                "productSurfaces must contain exactly the registered 18 product 360 ids",
            )
        )

    catalog_contract_states = {
        "draft_pending_source_alignment",
        "reconstructed_pending_source_alignment",
        "source_aligned",
    }
    for surface in surfaces:
        if not isinstance(surface, dict):
            violations.append(
                Violation("product_surface_catalog", "error", "each product surface must be an object")
            )
            continue
        sid = surface.get("id") if isinstance(surface.get("id"), str) else None
        if sid is not None and not re.fullmatch(r"[a-z][A-Za-z0-9]*360", sid):
            violations.append(
                Violation("product_surface_catalog", "error", "product surface id must be lower camel case ending in 360", sid)
            )
        for field in ("displayName", "description"):
            if not isinstance(surface.get(field), str) or not surface[field].strip():
                violations.append(
                    Violation("product_surface_catalog", "error", f"{field} must be a non-empty string", sid)
                )
        if surface.get("contractStatus") not in catalog_contract_states:
            violations.append(
                Violation("product_surface_catalog", "error", "contractStatus must be a recognized source-alignment state", sid)
            )
        subject_kinds = surface.get("subjectKinds")
        if (
            not isinstance(subject_kinds, list)
            or not subject_kinds
            or not all(isinstance(kind, str) and kind in set(reg.get("subjectKinds", [])) for kind in subject_kinds)
            or len(set(subject_kinds)) != len(subject_kinds)
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "subjectKinds must be unique registered subject kinds", sid)
            )

        slots = surface.get("domainSlots")
        if not isinstance(slots, list) or not slots:
            violations.append(
                Violation("product_surface_catalog", "error", "domainSlots must be a non-empty array", sid)
            )
            slots = []
        slot_ids: set[str] = set()
        slot_authorities: set[str] = set()
        aggregate_bindings: dict[str, str] = {}
        aggregate_capabilities: set[str] = set()
        direct_provider_bindings = surface.get("directProviderBindings", [])
        direct_authorities_by_slot: dict[str, set[str]] = {}
        if isinstance(direct_provider_bindings, list):
            for direct_binding in direct_provider_bindings:
                if not isinstance(direct_binding, dict):
                    continue
                direct_slot_ids = direct_binding.get("domainSlotIds")
                direct_authorities = direct_binding.get("canonicalAuthorityRefs")
                if not isinstance(direct_slot_ids, list) or not isinstance(direct_authorities, list):
                    continue
                authority_set = {
                    authority
                    for authority in direct_authorities
                    if isinstance(authority, str) and authority in AUTHORITY_INDEX
                }
                for direct_slot_id in direct_slot_ids:
                    if isinstance(direct_slot_id, str):
                        direct_authorities_by_slot.setdefault(direct_slot_id, set()).update(
                            authority_set
                        )
        for slot in slots:
            if not isinstance(slot, dict):
                violations.append(
                    Violation("product_surface_catalog", "error", "each domain slot must be an object", sid)
                )
                continue
            slot_id = slot.get("id")
            if not isinstance(slot_id, str) or not _LOWER_SNAKE_RE.fullmatch(slot_id) or slot_id in slot_ids:
                violations.append(
                    Violation("product_surface_catalog", "error", f"invalid or duplicate domain slot id {slot_id!r}", sid)
                )
            if isinstance(slot_id, str):
                slot_ids.add(slot_id)
            if slot.get("requirement") not in {"required", "optional"}:
                violations.append(
                    Violation("product_surface_catalog", "error", "domain slot requirement must be required or optional", sid)
                )
            if not isinstance(slot.get("description"), str) or not slot["description"].strip():
                violations.append(
                    Violation("product_surface_catalog", "error", "domain slot description must be non-empty", sid)
                )
            required_metadata = slot.get("requiredFrameMetadata", [])
            if (
                not isinstance(required_metadata, list)
                or not all(
                    item in {"slotActorAttribution", "slotAuthorityDecision"}
                    for item in required_metadata
                )
                or len(set(required_metadata)) != len(required_metadata)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "requiredFrameMetadata must list unique supported frame metadata requirements",
                        sid,
                    )
                )
            authorities = slot.get("canonicalAuthorityRefs")
            if (
                not isinstance(authorities, list)
                or not authorities
                or not all(isinstance(authority, str) and authority in AUTHORITY_INDEX for authority in authorities)
                or len(set(authorities)) != len(authorities)
            ):
                violations.append(
                    Violation("product_surface_catalog", "error", "canonicalAuthorityRefs must be unique registered authorities", sid)
                )
                authorities = []
            slot_authorities.update(authorities)

            bindings = slot.get("projectionBindings")
            if not isinstance(bindings, list):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "projectionBindings must be an array",
                        sid,
                    )
                )
                continue
            direct_authorities = direct_authorities_by_slot.get(slot_id, set())
            if "partialImplementationReason" in slot and (
                not isinstance(slot["partialImplementationReason"], str)
                or not slot["partialImplementationReason"].strip()
                or not (bindings or direct_authorities)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "partialImplementationReason requires a bound slot and non-empty reason",
                        sid,
                    )
                )
            if not bindings:
                if direct_authorities:
                    if slot.get("unboundReason") is not None:
                        violations.append(
                            Violation(
                                "product_surface_catalog",
                                "error",
                                "unboundReason is invalid when a direct provider is bound to the slot",
                                sid,
                            )
                        )
                    if isinstance(authorities, list) and not set(authorities).issubset(
                        direct_authorities
                    ):
                        violations.append(
                            Violation(
                                "product_surface_catalog",
                                "error",
                                "domain slot authorities lack a bound direct provider",
                                sid,
                            )
                        )
                else:
                    unbound_reason = slot.get("unboundReason")
                    if not isinstance(unbound_reason, str) or not unbound_reason.strip():
                        violations.append(
                            Violation(
                                "product_surface_catalog",
                                "error",
                                "an unbound slot must declare its implementation gap in unboundReason",
                                sid,
                            )
                        )
                continue
            if slot.get("unboundReason") is not None:
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "unboundReason is valid only when no projection or direct provider is bound",
                        sid,
                    )
                )
            slot_projection_ids: set[str] = set()
            slot_provider_authorities: set[str] = set(direct_authorities)
            for binding in bindings:
                if not isinstance(binding, dict):
                    violations.append(
                        Violation("product_surface_catalog", "error", "slot projection binding must be an object", sid)
                    )
                    continue
                projection_id = binding.get("projectionId")
                provider = projections.get(projection_id) if isinstance(projection_id, str) else None
                if provider is None:
                    violations.append(
                        Violation("product_surface_catalog", "error", f"unknown projection binding {projection_id!r}", sid)
                    )
                    continue
                if projection_id in slot_projection_ids:
                    violations.append(
                        Violation("product_surface_catalog", "error", f"duplicate projection binding {projection_id!r} in slot", sid)
                    )
                slot_projection_ids.add(projection_id)
                role = binding.get("role")
                if role not in {"primary", "supporting"}:
                    violations.append(
                        Violation("product_surface_catalog", "error", "projection binding role must be primary or supporting", sid)
                    )
                binding_subject_kinds = binding.get("subjectKinds")
                provider_subject_kinds = set(provider.get("subjectKinds", []))
                surface_subject_kinds = (
                    set(subject_kinds) if isinstance(subject_kinds, list) else set()
                )
                if (
                    not isinstance(binding_subject_kinds, list)
                    or not all(
                        isinstance(kind, str)
                        and kind in surface_subject_kinds
                        and kind in provider_subject_kinds
                        for kind in binding_subject_kinds
                    )
                    or len(set(binding_subject_kinds)) != len(binding_subject_kinds)
                ):
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            f"subjectKinds for {projection_id!r} must be unique declared surface and provider subject kinds",
                            sid,
                        )
                    )
                current_role = aggregate_bindings.get(projection_id)
                aggregate_bindings[projection_id] = (
                    "primary" if role == "primary" or current_role == "primary" else "supporting"
                )
                slot_provider_authorities.update(provider.get("canonicalAuthorities", []))
                sections = binding.get("sectionIds")
                declared_sections = set(provider.get("outputSections", []))
                if (
                    not isinstance(sections, list)
                    or not all(isinstance(section, str) for section in sections)
                    or len(set(sections)) != len(sections)
                    or set(sections) - declared_sections
                ):
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            f"sectionIds for {projection_id!r} must be unique declared outputSections",
                            sid,
                        )
                    )
                elif not sections and declared_sections:
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            f"sectionIds for {projection_id!r} cannot be empty while outputSections are declared",
                            sid,
                        )
                    )
            required_claim_projection_ids = slot.get("requiredClaimProjectionIds", [])
            if (
                not isinstance(required_claim_projection_ids, list)
                or not all(
                    isinstance(projection_id, str) and projection_id
                    for projection_id in required_claim_projection_ids
                )
                or len(set(required_claim_projection_ids)) != len(required_claim_projection_ids)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "requiredClaimProjectionIds must list unique bound projection ids",
                        sid,
                    )
                )
            elif set(required_claim_projection_ids) - slot_projection_ids:
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "requiredClaimProjectionIds must be included in the slot projection bindings",
                        sid,
                    )
                )
            if isinstance(authorities, list):
                missing_authorities = set(authorities) - slot_provider_authorities
                declared_gap = slot.get("unboundCanonicalAuthorityRefs", [])
                if (
                    not isinstance(declared_gap, list)
                    or not all(isinstance(ref, str) for ref in declared_gap)
                    or len(set(declared_gap)) != len(declared_gap)
                    or set(declared_gap) != missing_authorities
                ):
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            f"unboundCanonicalAuthorityRefs must exactly list authorities without a bound provider: {sorted(missing_authorities)}",
                            sid,
                        )
                    )
                if missing_authorities and not (
                    isinstance(slot.get("authorityGapReason"), str)
                    and slot["authorityGapReason"].strip()
                ):
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            "a partially bound slot must explain its unbound authorities",
                            sid,
                        )
                    )
                if not missing_authorities and slot.get("authorityGapReason") is not None:
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            "authorityGapReason is invalid when all authorities are bound",
                            sid,
                        )
                    )

        if not isinstance(direct_provider_bindings, list):
            violations.append(
                Violation(
                    "product_surface_catalog",
                    "error",
                    "directProviderBindings must be an array when declared",
                    sid,
                )
            )
            direct_provider_bindings = []
        if direct_provider_bindings != EXPECTED_DIRECT_PROVIDER_BINDINGS.get(sid, []):
            violations.append(
                Violation(
                    "product_surface_catalog",
                    "error",
                    "directProviderBindings must match the registered runtime-wired surface paths",
                    sid,
                )
            )
        direct_provider_classes: set[str] = set()
        for binding in direct_provider_bindings:
            if not isinstance(binding, dict):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct surface provider binding must be an object",
                        sid,
                    )
                )
                continue
            provider_class = binding.get("providerClass")
            if (
                not isinstance(provider_class, str)
                or not re.fullmatch(r"[A-Z][A-Za-z0-9]*", provider_class)
                or provider_class in direct_provider_classes
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider classes must be unique class names",
                        sid,
                    )
                )
            elif isinstance(provider_class, str):
                direct_provider_classes.add(provider_class)
            if binding.get("providerKind") not in {
                "surface_authority_reader",
                "surface_frame_provider",
            }:
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider kind must describe a surface authority reader or frame provider",
                        sid,
                    )
                )
            if binding.get("bindingStatus") != "runtime_wired":
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider status must attest only a runtime-wired call path",
                        sid,
                    )
                )
            direct_authority_refs = binding.get("canonicalAuthorityRefs")
            if (
                not isinstance(direct_authority_refs, list)
                or not direct_authority_refs
                or not all(
                    isinstance(authority, str) and authority in AUTHORITY_INDEX
                    for authority in direct_authority_refs
                )
                or len(set(direct_authority_refs)) != len(direct_authority_refs)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider canonicalAuthorityRefs must be unique registered authorities",
                        sid,
                    )
                )
            direct_subject_kinds = binding.get("subjectKinds")
            if (
                not isinstance(direct_subject_kinds, list)
                or not direct_subject_kinds
                or not all(
                    isinstance(kind, str)
                    and isinstance(subject_kinds, list)
                    and kind in subject_kinds
                    for kind in direct_subject_kinds
                )
                or len(set(direct_subject_kinds)) != len(direct_subject_kinds)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider subjectKinds must be unique declared surface subject kinds",
                        sid,
                    )
                )
            direct_slot_ids = binding.get("domainSlotIds")
            if (
                not isinstance(direct_slot_ids, list)
                or not direct_slot_ids
                or not all(isinstance(slot_id, str) and slot_id in slot_ids for slot_id in direct_slot_ids)
                or len(set(direct_slot_ids)) != len(direct_slot_ids)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "direct provider domainSlotIds must be unique declared surface slots",
                        sid,
                    )
                )
            for ref_field in ("implementationRef", "runtimeBindingRef"):
                ref_value = binding.get(ref_field)
                if (
                    not isinstance(ref_value, str)
                    or not ref_value.startswith("services/api/")
                    or not ref_value.endswith(".py")
                ):
                    violations.append(
                        Violation(
                            "product_surface_catalog",
                            "error",
                            f"direct provider {ref_field} must be a repository-relative backend source path",
                            sid,
                        )
                    )

        projection_bindings = surface.get("projectionBindings")
        if not isinstance(projection_bindings, list):
            violations.append(
                Violation("product_surface_catalog", "error", "surface projectionBindings must be an array", sid)
            )
            projection_bindings = []
        declared_top: dict[str, dict] = {}
        for binding in projection_bindings:
            if not isinstance(binding, dict):
                violations.append(
                    Violation("product_surface_catalog", "error", "surface projection binding must be an object", sid)
                )
                continue
            projection_id = binding.get("projectionId")
            provider = projections.get(projection_id) if isinstance(projection_id, str) else None
            if provider is None:
                violations.append(
                    Violation("product_surface_catalog", "error", f"unknown surface projection binding {projection_id!r}", sid)
                )
                continue
            if projection_id in declared_top:
                violations.append(
                    Violation("product_surface_catalog", "error", f"duplicate surface projection binding {projection_id!r}", sid)
                )
            declared_top[projection_id] = binding
            if binding.get("bindingStatus") != "catalog_only":
                violations.append(
                    Violation("product_surface_catalog", "error", "initial projection binding status must be catalog_only", sid)
                )
            if binding.get("providerImplementationState") != provider.get("implementationState"):
                violations.append(
                    Violation("product_surface_catalog", "error", f"provider implementation state for {projection_id!r} must mirror the projection registry", sid)
                )
            aggregate_capabilities.update(provider.get("capabilityKeys", []))
        if set(declared_top) != set(aggregate_bindings):
            violations.append(
                Violation("product_surface_catalog", "error", "top-level projectionBindings must equal the domain-slot binding union", sid)
            )
        for projection_id, role in aggregate_bindings.items():
            if declared_top.get(projection_id, {}).get("role") != role:
                violations.append(
                    Violation("product_surface_catalog", "error", f"top-level role for {projection_id!r} must reflect its slot roles", sid)
                )

        truth = surface.get("sourceOfTruth")
        if not isinstance(truth, dict) or truth.get("ownsCanonicalTruth") is not False:
            violations.append(
                Violation("product_surface_catalog", "error", "sourceOfTruth must declare ownsCanonicalTruth=false", sid)
            )
        else:
            truth_authorities = truth.get("canonicalAuthorities")
            if not isinstance(truth_authorities, list) or set(truth_authorities) != slot_authorities:
                violations.append(
                    Violation("product_surface_catalog", "error", "sourceOfTruth authorities must equal the domain-slot authority union", sid)
                )
            if not isinstance(truth.get("prohibitedOwnership"), list) or not truth["prohibitedOwnership"]:
                violations.append(
                    Violation("product_surface_catalog", "error", "sourceOfTruth must list prohibited truth ownership", sid)
                )

        freshness = surface.get("freshnessPolicy")
        if (
            not isinstance(freshness, dict)
            or freshness.get("required") is not True
            or freshness.get("sourceTimestamps") != "preserve"
            or freshness.get("missingTimestamp") != "unknown"
            or freshness.get("onStale") != "mark_affected_slots_stale"
            or freshness.get("requirementStatus") != "contract_requirement_not_provider_attestation"
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "freshnessPolicy must require freshness and preserve explicit missing/stale state", sid)
            )
        elif freshness.get("maxAgeSeconds") is not None and (
            not isinstance(freshness.get("maxAgeSeconds"), int) or freshness["maxAgeSeconds"] <= 0
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "maxAgeSeconds must be null or a positive integer", sid)
            )

        policy = surface.get("policyBehavior")
        if (
            not isinstance(policy, dict)
            or policy.get("tenantScopeRequired") is not True
            or policy.get("authorizationBeforeRead") is not True
            or policy.get("policyEvaluation") != "per_projection_before_composition"
            or policy.get("historicalConsentEvaluation") != "required_when_applicable"
            or policy.get("redactionBehavior") != "suppress_disallowed_slot_without_inference"
            or policy.get("requirementStatus") != "contract_requirement_not_provider_attestation"
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "policyBehavior must describe tenant-first governed reads and non-inferential redaction", sid)
            )

        capabilities = surface.get("backendCapabilities")
        required_capabilities = {
            "experience360.frame.compose",
            "experience360.tenant_scope.enforce",
            "experience360.policy.evaluate",
            "experience360.freshness.evaluate",
            "experience360.evidence.provenance",
        }
        if (
            not isinstance(capabilities, dict)
            or not isinstance(capabilities.get("required"), list)
            or not all(isinstance(capability, str) for capability in capabilities.get("required", []))
            or not required_capabilities.issubset(set(capabilities.get("required", [])))
            or not isinstance(capabilities.get("projectionCapabilityKeys"), list)
            or not all(isinstance(capability, str) for capability in capabilities.get("projectionCapabilityKeys", []))
            or set(capabilities.get("projectionCapabilityKeys", [])) != aggregate_capabilities
            or capabilities.get("providerCapabilityStatus") != "registry_requirements_not_route_attestation"
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "backendCapabilities must list frame requirements and the bound providers' capability keys", sid)
            )

        lens_contract = surface.get("lensContract")
        if (
            surface.get("contractStatus") == "source_aligned"
            and isinstance(lens_contract, dict)
            and lens_contract.get("sourceAlignmentStatus") != "source_aligned"
        ):
            violations.append(
                Violation(
                    "product_surface_catalog",
                    "error",
                    "source-aligned surface must have a source-aligned lensContract",
                    sid,
                )
            )
        if (
            not isinstance(lens_contract, dict)
            or not isinstance(lens_contract.get("lensIds"), list)
            or not all(isinstance(lens_id, str) for lens_id in lens_contract.get("lensIds", []))
            or len(set(lens_contract.get("lensIds", []))) != len(lens_contract.get("lensIds", []))
            or lens_contract.get("sourceAlignmentStatus")
            not in {"pending_source_alignment", "source_aligned"}
        ):
            violations.append(
                Violation("product_surface_catalog", "error", "lensContract must declare unique lens ids and an explicit alignment state", sid)
            )
        elif lens_contract.get("sourceAlignmentStatus") == "source_aligned":
            blueprint = surface.get("blueprintContract")
            blueprint_lens_ids = blueprint.get("requiredLensIds") if isinstance(blueprint, dict) else None
            lens_ids = lens_contract["lensIds"]
            if (
                not isinstance(blueprint_lens_ids, list)
                or not all(isinstance(lens_id, str) for lens_id in blueprint_lens_ids)
                or lens_ids != blueprint_lens_ids
                or lens_contract.get("expectedCount") != len(blueprint_lens_ids)
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "source-aligned lensContract must match blueprint requiredLensIds and expectedCount",
                        sid,
                    )
                )
            blueprint_slot_ids = (
                blueprint.get("requiredSlotIds") if isinstance(blueprint, dict) else None
            )
            required_slot_ids = [
                slot.get("id")
                for slot in slots
                if isinstance(slot, dict) and slot.get("requirement") == "required"
            ]
            if (
                not isinstance(blueprint_slot_ids, list)
                or required_slot_ids != blueprint_slot_ids
            ):
                violations.append(
                    Violation(
                        "product_surface_catalog",
                        "error",
                        "source-aligned required domain slots must match blueprint requiredSlotIds in order",
                        sid,
                    )
                )
        elif sid == "agent360":
            blueprint = surface.get("blueprintContract")
            blueprint_required_ids = (
                blueprint.get("requiredSlotIds") if isinstance(blueprint, dict) else None
            )
            actual_required_ids = {
                slot.get("id")
                for slot in slots
                if isinstance(slot, dict) and slot.get("requirement") == "required"
            }
            if (
                lens_contract.get("expectedCount") != 8
                or not isinstance(blueprint_required_ids, list)
                or len(blueprint_required_ids) != 11
                or actual_required_ids != set(blueprint_required_ids)
            ):
                violations.append(
                    Violation("product_surface_catalog", "error", "Agent 360 must preserve the recovered 11-slot and 8-lens counts", sid)
                )
        elif lens_contract.get("expectedCount") is not None:
            violations.append(
                Violation("product_surface_catalog", "error", "unverified non-Agent lens counts must remain unset", sid)
            )

    return violations


def validate_all(reg: dict, ctx: Optional[dict] = None) -> list[Violation]:
    """Run every rule group and return a flat, deterministically sorted list."""
    if ctx is None:
        ctx = load_context()
    results = (
        validate_registry_schema(reg)
        + validate_product_surface_catalog(reg)
        + validate_dependency_dag(reg)
        + validate_cross_registry(reg, ctx)
        + validate_inventory(reg, ctx)
        + validate_ownership(reg)
        + validate_surface_honesty(reg, ctx)
        + validate_metric_honesty(reg, ctx)
        + validate_degradation_vocab(reg)
        + validate_lens_registry(reg, ctx)
        + validate_outcome_registry(reg, ctx)
    )
    return sorted(
        results,
        key=lambda v: (v.projection or "", v.rule, v.severity, v.message),
    )
