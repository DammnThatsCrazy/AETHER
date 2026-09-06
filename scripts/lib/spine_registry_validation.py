"""Importable validation core for the Spine Registry (Spine P0, Wave 2A).

The spine registry (``packages/shared/contracts/spine-registry.json``) is the
canonical governing statement of what a "spine" is (ADR-011 D1): every spine is
a governed authority or cross-cutting control boundary — never a private
platform inside the platform. Each row declares what it owns, which canonical
contracts it references (never re-defines), which authorities it depends on,
how it degrades, and how it is exposed. This module is the mechanical
enforcement of that doctrine against the registry plus the registries it must
resolve against (surface-capability, readiness-vocabulary, consent, metric,
graph-mutation, event, temporal-policy, evidence-manifest, model, kyber,
context-capsule, intelligence-projection). It is a library — there is no CLI
here; ``scripts/validate_spine_registry.py`` (Wave 2A) calls into it.

Rule groups (each returns ``list[Violation]``; severity ``"error"`` gates CI):

- registry_schema — the 9 required top-level keys present; ``planes`` /
  ``spineKinds`` / ``implementationStates`` / ``graphMutationPolicies`` are
  non-empty lower_snake lists; ``conformanceChecks`` ids are exactly the
  canonical 14 (ADR-011 D6); spine ids unique + lower_snake; every required
  per-entry field present and typed; ``plane`` / ``spineKind`` /
  ``implementationState`` / ``graphMutationPolicy`` members of the file's vocab
  arrays; ``description`` non-empty.
- dependency_dag — ``dependencies`` keys limited to {hard, soft, runtime,
  policy}; every dependency ref resolves to a spine entry ``id`` in the SAME
  file; no self-dependency; the hard-dependency graph is acyclic (a hard cycle
  is an ordering deadlock — an authority that can never be stood up).
- cross_registry — every ``surfaces`` token resolves against the surface
  registry (no declared-pending surface mechanism: a spine is either exposed
  through a registered surface or silent); ``readinessKey`` is None or a token
  from readiness-vocabulary.json (D5 presentation-only join); every
  ``canonicalContractRefs[].registry`` exists under
  ``packages/shared/contracts/`` and parses as JSON, and every ``refIds`` entry
  actually occurs in that owning file (permissive-but-correct owned-id
  resolution — only a refId that appears NOWHERE under an owned-id position is
  an error; one that appears only as a loose string is a warning);
  ``legacyBindings.services`` entries that look like paths must exist on disk
  (the tetris "fold in what exists" gate; missing ones are flagged as warnings
  so a stale-lane checkout cannot hard-fail the registry, and are reported for
  data review); no-parallel-registry — an entry ``id`` must not collide with an
  id owned by another canonical registry (surface, readiness token, consent
  purpose key, metric id, graph mutation type, event type) unless the token is
  a documented cross-plane homonym (the ``graph`` spine is exposed through the
  ``graph`` surface; the ``consent`` spine is the authority over the
  ``consent`` event family); ``unresolvedRefs`` entries are well-formed
  ``{ref|id, kind, reason, resolvesIn}`` with ``kind`` in the curated set.
- conformance_gate — a non-``program_capability`` spine's ``conformance``
  object contains EXACTLY the canonical 14 conformance-check ids and every value
  is ``"open"`` or ``"verified"``; a ``program_capability`` spine's
  ``conformance`` is ``{}``. P6 enforcement: an entry whose
  ``implementationState`` is ``"canonical"`` or ``"deprecated"`` must have ALL
  14 checks ``"verified"`` — a state flip with an open gap is a hard error.
- lifecycle_honesty — ``implementationState "pending"`` entries must carry at
  least one ``unresolvedRefs`` declaration or a documented pending rationale;
  ``lifecycle`` booleans are booleans; ``tenantBoundary`` /
  ``securityCompliance`` are well-typed.
- ownership — each entry carries a non-empty ``authorityDeclaration`` and
  ``nonOwnershipStatement`` and a boolean ``ownsCanonicalTruth``;
  ``legacyBindings`` is present with ``aliases`` / ``services`` /
  ``migrationMode``, and ``migrationMode`` is one of {formalize_existing,
  adapter, net_new}.
- inventory_honesty — conservative, advisory-only honesty checks: a spine in
  ``"pending"`` state must not declare ``migrationMode "formalize_existing"``
  (you cannot be formalizing work that you are declaring has not started).

Order-resilience doctrine (tetris): the spine plane formalizes the projection
plane's five ``pendingAuthority {kind:"spine"}`` targets
(``journey_continuity``, ``graph_history_replay``, ``context_capsule_semantics``,
``grouping_membership``, ``reconciled_control_plane``). Those rows are present
here in ``implementationState "pending"`` with an ``unresolvedRefs`` declaration
so the projection validator's SPINE_INDEX can later derive from this file. A
reference that does not yet resolve is never a silent string.
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

# The canonical 14-item conformance contract (ADR-011 D6, listed in order in
# docs/source-of-truth/SPINE_P0_ARCHITECTURE.md §7). A spine row's `conformance`
# object is compared against this set, and the file's own `conformanceChecks`
# array must declare exactly these ids. Kept here so a check can never silently
# drift out of the canonical contract; additions must land here (and in the
# conformance-checklist doc) in the same change.
CONFORMANCE_CHECK_IDS = (
    "authority_non_ownership_statement",
    "canonical_contract_registration",
    "port_adapter_declaration",
    "dependency_dag_validation",
    "typed_degradation_behavior",
    "temporal_watermark_behavior",
    "evidence_restatement_behavior",
    "tenant_consent_rights_retention_residency_export",
    "graph_mutation_policy",
    "api_event_ui_kyber_integration",
    "readiness_entitlement_integration",
    "security_compliance_observability_evidence",
    "migration_recompute_rollback_compatibility",
    "positive_negative_replay_isolation_golden_tests",
)
_CANONICAL_CONFORMANCE = frozenset(CONFORMANCE_CHECK_IDS)

# The dependency kinds a spine row may declare. Every dependency ref inside any
# of these lists must resolve to a spine ``id`` in the SAME file.
DEPENDENCY_KINDS = frozenset({"hard", "soft", "runtime", "policy"})

# ADR-011 D4: legacy bindings describe how existing work is folded into the
# spine — it is either formalized (already exists under a current name),
# adapted (wrapped behind an adapter), or net-new (no prior machinery).
MIGRATION_MODES = frozenset({"formalize_existing", "adapter", "net_new"})

_CONFORMANCE_VALUES = frozenset({"open", "verified"})

# unresolvedRefs declares a reference that does not yet resolve and the
# milestone that resolves it. The identifier field is `ref` in the committed
# registry (`id` is accepted for forward-compatibility).
_UNRESOLVED_REF_REQUIRED_KEYS = ("kind", "reason", "resolvesIn")
_UNRESOLVED_REF_IDENTIFIER_KEYS = ("ref", "id")
# Curated kinds an unresolvedRef may declare. Kept here so an unresolved
# reference can never silently drift out of the curated plane.
_UNRESOLVED_REF_KINDS = frozenset({"spine", "envelope_field", "vocabulary"})

# Owned-id namespaces that a spine ``id`` must not re-define (D2: a spine row
# references — never re-defines — an id owned by another canonical registry).
# Two tokens are documented cross-plane homonyms and are exempt: the ``graph``
# spine is exposed through the ``graph`` surface (its own ``surfaces`` array
# declares ``["graph"]``), and the ``consent`` spine is the canonical authority
# over the ``consent`` event family. A collision with any OTHER owned id (a
# surface id, readiness token, consent purpose key, metric id, graph mutation
# type or event type) is a hard parallel-registry violation.
_CROSS_PLANE_HOMONYM_EXCEPTIONS = frozenset({"graph", "consent"})

# The nine required top-level keys of the registry file.
_REQUIRED_TOP_LEVEL_KEYS = (
    "schemaVersion",
    "contractVersion",
    "description",
    "planes",
    "spineKinds",
    "implementationStates",
    "graphMutationPolicies",
    "conformanceChecks",
    "spines",
)
_VOCAB_ARRAYS = ("planes", "spineKinds", "implementationStates", "graphMutationPolicies")

# Per-entry fields every spine row must carry (the union observed across the
# committed registry — a spine row declares ownership/non-ownership, ports,
# dependencies, boundaries, lifecycle, surfaces, security, observability,
# conformance, unresolved refs and legacy bindings).
_REQUIRED_ENTRY_FIELDS = (
    "id",
    "displayName",
    "description",
    "plane",
    "spineKind",
    "implementationState",
    "ownsCanonicalTruth",
    "authorityDeclaration",
    "nonOwnershipStatement",
    "canonicalContractRefs",
    "ports",
    "adapters",
    "dependencies",
    "graphMutationPolicy",
    "tenantBoundary",
    "lifecycle",
    "readinessKey",
    "surfaces",
    "securityCompliance",
    "observabilityRecovery",
    "conformance",
    "unresolvedRefs",
    "legacyBindings",
    "implementationBlueprint",
)

_STRING_FIELDS = (
    "id",
    "displayName",
    "description",
    "plane",
    "spineKind",
    "implementationState",
    "graphMutationPolicy",
    "authorityDeclaration",
    "nonOwnershipStatement",
)
# present-but-nullable strings (``readinessKey`` is the D5 presentation-only
# join; ``implementationBlueprint`` is null until a blueprint lands).
_NULLABLE_STRING_FIELDS = ("readinessKey", "implementationBlueprint")

_LIST_FIELDS = ("surfaces", "adapters", "canonicalContractRefs", "unresolvedRefs")

_DICT_FIELDS = (
    "ports",
    "dependencies",
    "tenantBoundary",
    "lifecycle",
    "securityCompliance",
    "observabilityRecovery",
    "conformance",
    "legacyBindings",
)

_LOWER_SNAKE_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")

# Keys whose list-of-str values are prose, NOT vocabularies (used only to keep
# the permissive owned-id resolver from treating description text as owned ids).
_PROSE_LIST_KEYS = frozenset(
    {
        "required",
        "enum",
        "description",
        "label",
        "notes",
        "reason",
        "_comment",
        "title",
        "docstring",
        "errorMessage",
    }
)

# Object keys that carry an owned identifier value. Used by the permissive
# owned-id resolver to tell "strongly resolved" refs (real owned ids) apart from
# "loose" refs (strings that merely appear somewhere in the owning file).
_ID_LIKE_KEYS = frozenset(
    {
        "id",
        "ids",
        "key",
        "name",
        "code",
        "type",
        "ref",
        "surfaceId",
        "modelId",
        "feature_id",
        "mutationType",
        "actorKind",
        "causalityClass",
        "explanationType",
        "purpose",
        "token",
        "metric",
        "event",
        "member",
        "provider",
        "family",
        "category",
        "disposition",
        "enforcementMode",
        "locationSource",
        "contextState",
        "conflictState",
        "precisionClass",
        "reasonCode",
        "class",
    }
)

# Rule groups in the order ``validate_all`` runs them (registry order is the
# canonical reading order for the report).
_GROUP_ORDER = (
    "registry_schema",
    "dependency_dag",
    "cross_registry",
    "conformance_gate",
    "lifecycle_honesty",
    "ownership",
    "inventory_honesty",
)
_GROUP_RANK = {name: i for i, name in enumerate(_GROUP_ORDER)}


@dataclass
class Violation:
    """One validator finding.

    ``id`` is a rule-group-scoped identifier — ``"<group>.<finding>"``, e.g.
    ``"conformance_gate.missing_check"`` — so two rule groups never share a
    finding id. ``severity`` is ``"error"`` (gates CI) or ``"warning"``
    (advisory). ``spine_id`` names the offending spine entry (``None`` for
    top-level/registry-wide findings). ``message`` is human-readable and
    actionable.
    """

    id: str
    severity: str
    message: str
    spine_id: Optional[str] = None

    @property
    def rule(self) -> str:
        """The rule-group name (the id prefix before the first dot)."""
        return self.id.partition(".")[0]

    def __str__(self) -> str:  # pragma: no cover - debug/CLI convenience
        scope = self.spine_id or "<registry>"
        return f"[{self.id}:{self.severity}] {scope}: {self.message}"


# ---------------------------------------------------------------------------
# Context loading
# ---------------------------------------------------------------------------


def _load_json(rel_path: str) -> Optional[dict]:
    """Load a repo-relative JSON file, returning None if missing/invalid."""
    path = ROOT / rel_path
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, (dict, list)) else None


@functools.lru_cache(maxsize=1)
def _load_surface_ids() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/surface-capability-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(s["surfaceId"] for s in doc.get("surfaces", []) if isinstance(s, dict))


@functools.lru_cache(maxsize=1)
def _load_readiness_tokens() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/readiness-vocabulary.json")
    if not isinstance(doc, dict):
        return frozenset()
    tokens = {t["id"] for t in doc.get("tokens", []) if isinstance(t, dict) and t.get("id")}
    # release-plan and progression vocabulary members are also first-class
    # readiness tokens a spine's readinessKey / contract refs may join.
    tokens |= set(doc.get("releasePlanVocabulary", []))
    tokens |= set(doc.get("progressionOrder", []))
    return frozenset(tokens)


@functools.lru_cache(maxsize=1)
def _load_readiness_progression() -> tuple[str, ...]:
    doc = _load_json("packages/shared/contracts/readiness-vocabulary.json")
    if not isinstance(doc, dict):
        return ()
    order = doc.get("progressionOrder")
    return tuple(order) if isinstance(order, list) else ()


@functools.lru_cache(maxsize=1)
def _load_consent_purpose_keys() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/consent-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(
        p["key"] for p in doc.get("purposes", []) if isinstance(p, dict) and p.get("key")
    )


@functools.lru_cache(maxsize=1)
def _load_metric_ids() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/metric-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(
        m["name"] for m in doc.get("metrics", []) if isinstance(m, dict) and m.get("name")
    )


@functools.lru_cache(maxsize=1)
def _load_graph_mutation_types() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/graph-mutation-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(doc.get("mutationTypes", []))


@functools.lru_cache(maxsize=1)
def _load_graph_mutation_policies() -> frozenset[str]:
    # The projection plane owns the canonical graphMutationPolicies vocabulary
    # (intelligence-projection-registry.json); the spine registry must not
    # drift from it.
    doc = _load_json("packages/shared/contracts/intelligence-projection-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(doc.get("graphMutationPolicies", []))


@functools.lru_cache(maxsize=1)
def _load_event_types() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/event-registry.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(
        e["type"] for e in doc.get("events", []) if isinstance(e, dict) and e.get("type")
    )


@functools.lru_cache(maxsize=1)
def _load_evidence_def_keys() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/evidence-manifest.schema.json")
    if not isinstance(doc, dict):
        return frozenset()
    defs = doc.get("$defs")
    return frozenset(defs.keys()) if isinstance(defs, dict) else frozenset()


@functools.lru_cache(maxsize=1)
def _load_kyber_feature_ids() -> frozenset[str]:
    doc = _load_json("packages/shared/contracts/kyber-feature-surface-manifest.json")
    if not isinstance(doc, dict):
        return frozenset()
    return frozenset(
        s["feature_id"]
        for s in doc.get("surfaces", [])
        if isinstance(s, dict) and s.get("feature_id")
    )


def load_context() -> dict:
    """Load the cross-registry context once.

    Returns a dict of cross-registry facts read directly from the owning
    canonical registries (each is the single source of truth for its ids):

    - ``surface_ids`` — surfaceId values from surface-capability-registry.json;
    - ``readiness_tokens`` — readiness token ids + release-plan/progression
      vocabulary members from readiness-vocabulary.json;
    - ``readiness_progression`` — the progressionOrder list, if present;
    - ``consent_purpose_keys`` — purpose ``key`` values from consent-registry.json;
    - ``metric_ids`` — metric ``name`` values from metric-registry.json;
    - ``graph_mutation_types`` — mutationTypes from graph-mutation-registry.json;
    - ``graph_mutation_policies`` — the projection plane's graphMutationPolicies
      vocabulary (intelligence-projection-registry.json);
    - ``event_types`` — event ``type`` values from event-registry.json;
    - ``evidence_def_keys`` — ``$defs`` keys of evidence-manifest.schema.json;
    - ``kyber_feature_ids`` — feature ids from kyber-feature-surface-manifest.json;
    - ``owned_id_namespaces`` — ``{namespace: set_of_owned_ids}`` used by the
      no-parallel-registry collision check.
    """
    surface_ids = _load_surface_ids()
    readiness_tokens = _load_readiness_tokens()
    consent_purpose_keys = _load_consent_purpose_keys()
    metric_ids = _load_metric_ids()
    graph_mutation_types = _load_graph_mutation_types()
    graph_mutation_policies = _load_graph_mutation_policies()
    event_types = _load_event_types()
    evidence_def_keys = _load_evidence_def_keys()
    kyber_feature_ids = _load_kyber_feature_ids()
    return {
        "surface_ids": surface_ids,
        "readiness_tokens": readiness_tokens,
        "readiness_progression": _load_readiness_progression(),
        "consent_purpose_keys": consent_purpose_keys,
        "metric_ids": metric_ids,
        "graph_mutation_types": graph_mutation_types,
        "graph_mutation_policies": graph_mutation_policies,
        "event_types": event_types,
        "evidence_def_keys": evidence_def_keys,
        "kyber_feature_ids": kyber_feature_ids,
        "owned_id_namespaces": {
            "surface id": surface_ids,
            "readiness token": readiness_tokens,
            "consent purpose key": consent_purpose_keys,
            "metric id": metric_ids,
            "graph mutation type": graph_mutation_types,
            "event type": event_types,
        },
    }


# ---------------------------------------------------------------------------
# Owned-id resolution (canonicalContractRefs)
# ---------------------------------------------------------------------------


def _collect_owned_ids(doc) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(strong, weak)`` string ids collected from an owning registry.

    ``strong`` is the set of owned identifiers: string values under an id-like
    key, members of vocab arrays (list-of-str fields that are not prose), and
    the keys of any ``$defs`` / ``definitions`` schema map. ``weak`` is every
    other string in the document (description prose, labels, notes, ...). A
    ``canonicalContractRefs`` refId is an ERROR only if it appears in neither
    set; a refId that resolves only weakly is a warning (it exists somewhere in
    the owning file but not under an owned-id position — worth a human look).
    """
    strong: set[str] = set()
    weak: set[str] = set()

    def walk(node) -> None:
        nonlocal strong, weak
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("$defs", "definitions") and isinstance(value, dict):
                    strong |= set(value.keys())
                if isinstance(value, str):
                    (strong if key in _ID_LIKE_KEYS else weak).add(value)
                elif isinstance(value, list):
                    if value and all(isinstance(item, str) for item in value):
                        if key in _PROSE_LIST_KEYS:
                            weak |= set(value)
                        else:
                            strong |= set(value)
                    else:
                        walk(value)
                elif isinstance(value, dict):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    walk(item)

    walk(doc)
    return frozenset(strong), frozenset(weak)


@functools.lru_cache(maxsize=64)
def _owned_ids_for(registry_rel: str) -> tuple[Optional[frozenset[str]], Optional[frozenset[str]]]:
    """(strong, weak) owned ids for a canonical-contract registry path, or
    ``(None, None)`` when the file is missing / not valid JSON."""
    path = ROOT / registry_rel
    if not path.is_file():
        return None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    return _collect_owned_ids(doc)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _hard_dependency_edges(reg: dict) -> dict[str, set[str]]:
    """Spine id -> hard dependency spine ids (the acyclic-graph check)."""
    edges: dict[str, set[str]] = {}
    for spine in reg.get("spines", []):
        deps = (spine.get("dependencies") or {}).get("hard", [])
        edges.setdefault(spine.get("id"), set()).update(d for d in deps if isinstance(d, str))
    return edges


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


def _is_path_like(value: str) -> bool:
    """True when a ``legacyBindings.services`` string looks like a file/dir path
    (and so must exist on disk). Bare service names are not verifiable."""
    if not isinstance(value, str):
        return False
    return "/" in value or "." in value or value.endswith((".py", ".ts", ".md", ".json"))


def _lower_snake(value: object) -> bool:
    return isinstance(value, str) and bool(_LOWER_SNAKE_RE.fullmatch(value))


# ---------------------------------------------------------------------------
# Rule groups
# ---------------------------------------------------------------------------


def validate_registry_schema(reg: dict) -> list[Violation]:
    """Registry-integrity rules (rule group ``registry_schema``)."""
    violations: list[Violation] = []

    if not isinstance(reg, dict):
        return [
            Violation("registry_schema.not_an_object", "error", "registry must be a JSON object")
        ]

    for key in _REQUIRED_TOP_LEVEL_KEYS:
        if key not in reg:
            violations.append(
                Violation(
                    "registry_schema.missing_top_level_key",
                    "error",
                    f"missing top-level key {key!r}",
                )
            )

    for vocab in _VOCAB_ARRAYS:
        values = reg.get(vocab)
        if not isinstance(values, list) or not values:
            violations.append(
                Violation(
                    "registry_schema.empty_vocab_array",
                    "error",
                    f"vocab array {vocab!r} missing or empty",
                )
            )
            continue
        if len(set(values)) != len(values):
            violations.append(
                Violation(
                    "registry_schema.duplicate_vocab_value",
                    "error",
                    f"vocab array {vocab!r} contains duplicates",
                )
            )
        for value in values:
            if not _lower_snake(value):
                violations.append(
                    Violation(
                        "registry_schema.non_snake_vocab_value",
                        "error",
                        f"vocab value {value!r} in {vocab!r} is not lower_snake",
                    )
                )

    conformance_checks = reg.get("conformanceChecks")
    if isinstance(conformance_checks, list):
        check_ids = [c.get("id") for c in conformance_checks if isinstance(c, dict)]
        if set(check_ids) != _CANONICAL_CONFORMANCE:
            violations.append(
                Violation(
                    "registry_schema.conformance_check_mismatch",
                    "error",
                    "conformanceChecks ids must be exactly the canonical 14 "
                    f"(got {sorted(set(check_ids))})",
                )
            )
    elif "conformanceChecks" in reg:
        violations.append(
            Violation(
                "registry_schema.bad_top_level_type", "error", "'conformanceChecks' must be a list"
            )
        )

    spines = reg.get("spines")
    if not isinstance(spines, list) or not spines:
        return violations + [
            Violation(
                "registry_schema.missing_spines_array", "error", "spines array missing or empty"
            )
        ]

    ids = [spine.get("id") for spine in spines]
    if len(set(ids)) != len(ids):
        violations.append(
            Violation("registry_schema.duplicate_spine_id", "error", "spine ids must be unique")
        )
    for spine_id in ids:
        if not _lower_snake(spine_id):
            violations.append(
                Violation(
                    "registry_schema.non_snake_spine_id",
                    "error",
                    f"spine id {spine_id!r} must be lower_snake",
                )
            )

    planes = set(reg.get("planes", []))
    kinds = set(reg.get("spineKinds", []))
    states = set(reg.get("implementationStates", []))
    policies = set(reg.get("graphMutationPolicies", []))

    for spine in spines:
        spine_id = spine.get("id")
        for field in _REQUIRED_ENTRY_FIELDS:
            if field not in spine:
                violations.append(
                    Violation(
                        "registry_schema.missing_entry_field",
                        "error",
                        f"missing required field {field!r}",
                        spine_id,
                    )
                )
        for field in _STRING_FIELDS:
            if field in spine and not isinstance(spine[field], str):
                violations.append(
                    Violation(
                        "registry_schema.bad_string_field",
                        "error",
                        f"{field!r} must be a string",
                        spine_id,
                    )
                )
        for field in _NULLABLE_STRING_FIELDS:
            value = spine.get(field)
            if field in spine and value is not None and not isinstance(value, str):
                violations.append(
                    Violation(
                        "registry_schema.bad_string_field",
                        "error",
                        f"{field!r} must be a string or null",
                        spine_id,
                    )
                )
        if "ownsCanonicalTruth" in spine and not isinstance(spine["ownsCanonicalTruth"], bool):
            violations.append(
                Violation(
                    "registry_schema.bad_bool_field",
                    "error",
                    "'ownsCanonicalTruth' must be a boolean",
                    spine_id,
                )
            )
        for field in _LIST_FIELDS:
            value = spine.get(field)
            if field in spine and not isinstance(value, list):
                violations.append(
                    Violation(
                        "registry_schema.bad_list_field",
                        "error",
                        f"{field!r} must be a list",
                        spine_id,
                    )
                )
        for field in _DICT_FIELDS:
            value = spine.get(field)
            if field in spine and not isinstance(value, dict):
                violations.append(
                    Violation(
                        "registry_schema.bad_dict_field",
                        "error",
                        f"{field!r} must be an object",
                        spine_id,
                    )
                )

        if not isinstance(spine.get("description"), str) or not spine["description"].strip():
            violations.append(
                Violation(
                    "registry_schema.empty_description",
                    "error",
                    "'description' must be a non-empty string",
                    spine_id,
                )
            )

        if spine.get("plane") not in planes:
            violations.append(
                Violation(
                    "registry_schema.unknown_plane",
                    "error",
                    f"unknown plane {spine.get('plane')!r}",
                    spine_id,
                )
            )
        if spine.get("spineKind") not in kinds:
            violations.append(
                Violation(
                    "registry_schema.unknown_spine_kind",
                    "error",
                    f"unknown spineKind {spine.get('spineKind')!r}",
                    spine_id,
                )
            )
        if spine.get("implementationState") not in states:
            violations.append(
                Violation(
                    "registry_schema.unknown_implementation_state",
                    "error",
                    f"unknown implementationState {spine.get('implementationState')!r}",
                    spine_id,
                )
            )
        if spine.get("graphMutationPolicy") not in policies:
            violations.append(
                Violation(
                    "registry_schema.unknown_graph_mutation_policy",
                    "error",
                    f"unknown graphMutationPolicy {spine.get('graphMutationPolicy')!r}",
                    spine_id,
                )
            )

    return violations


def validate_dependency_dag(reg: dict) -> list[Violation]:
    """Dependency-DAG rules (rule group ``dependency_dag``)."""
    violations: list[Violation] = []
    spines = reg.get("spines", [])
    ids = {spine.get("id") for spine in spines}

    for spine in spines:
        spine_id = spine.get("id")
        deps = spine.get("dependencies")
        if deps is None:
            continue
        if not isinstance(deps, dict):
            continue  # typing reported by registry_schema
        for kind in deps:
            if kind not in DEPENDENCY_KINDS:
                violations.append(
                    Violation(
                        "dependency_dag.unknown_dependency_kind",
                        "error",
                        f"dependency kind {kind!r} must be one of {sorted(DEPENDENCY_KINDS)}",
                        spine_id,
                    )
                )
        for kind, refs in deps.items():
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if not isinstance(ref, str):
                    continue
                if ref == spine_id:
                    violations.append(
                        Violation(
                            "dependency_dag.self_dependency",
                            "error",
                            f"self-dependency on {ref!r}",
                            spine_id,
                        )
                    )
                elif ref not in ids:
                    violations.append(
                        Violation(
                            "dependency_dag.unresolved_dependency",
                            "error",
                            f"{kind} dependency {ref!r} is not a spine id in this registry",
                            spine_id,
                        )
                    )

    for cycle in _find_cycles(_hard_dependency_edges(reg)):
        path = " -> ".join(cycle + [cycle[0]])
        violations.append(
            Violation("dependency_dag.cycle", "error", f"hard-dependency cycle: {path}", cycle[0])
        )

    return violations


def validate_conformance_gate(reg: dict) -> list[Violation]:
    """Conformance-gate rules (rule group ``conformance_gate``).

    Every non-``program_capability`` spine's ``conformance`` object must contain
    EXACTLY the canonical 14 conformance-check ids with every value
    ``"open"``/``"verified"``; a ``program_capability`` spine's ``conformance``
    must be ``{}``. P6: an entry whose ``implementationState`` is ``"canonical"``
    or ``"deprecated"`` must have ALL 14 checks ``"verified"`` — a state flip
    with an open gap is a hard error.
    """
    violations: list[Violation] = []
    for spine in reg.get("spines", []):
        spine_id = spine.get("id")
        conformance = spine.get("conformance")
        is_program = spine.get("spineKind") == "program_capability"

        if is_program:
            if conformance != {}:
                violations.append(
                    Violation(
                        "conformance_gate.program_nonempty_conformance",
                        "error",
                        "program_capability spine must have conformance == {} (program "
                        "capabilities do not carry the 14-item spine conformance contract)",
                        spine_id,
                    )
                )
            continue

        if conformance is None:
            violations.append(
                Violation(
                    "conformance_gate.missing_check",
                    "error",
                    "conformance object is required",
                    spine_id,
                )
            )
            continue
        if not isinstance(conformance, dict):
            continue  # typing reported by registry_schema
        if not conformance:
            violations.append(
                Violation(
                    "conformance_gate.nonprogram_empty_conformance",
                    "error",
                    "non-program_capability spine must carry all 14 conformance checks",
                    spine_id,
                )
            )
        for check in CONFORMANCE_CHECK_IDS:
            if check not in conformance:
                violations.append(
                    Violation(
                        "conformance_gate.missing_check",
                        "error",
                        f"missing conformance check {check!r}",
                        spine_id,
                    )
                )
        for check in conformance:
            if check not in _CANONICAL_CONFORMANCE:
                violations.append(
                    Violation(
                        "conformance_gate.unexpected_check",
                        "error",
                        f"conformance check {check!r} is not one of the canonical 14",
                        spine_id,
                    )
                )
        for check, value in conformance.items():
            if check not in _CANONICAL_CONFORMANCE:
                continue
            if value not in _CONFORMANCE_VALUES:
                violations.append(
                    Violation(
                        "conformance_gate.invalid_conformance_value",
                        "error",
                        f"conformance check {check!r} has value {value!r}; expected 'open' or 'verified'",
                        spine_id,
                    )
                )

        state = spine.get("implementationState")
        if state in ("canonical", "deprecated"):
            open_checks = [
                check for check in CONFORMANCE_CHECK_IDS if conformance.get(check) != "verified"
            ]
            if open_checks:
                violations.append(
                    Violation(
                        "conformance_gate.state_flip_open_gap",
                        "error",
                        f"implementationState {state!r} requires all 14 conformance checks "
                        f"'verified', but {sorted(open_checks)} are not",
                        spine_id,
                    )
                )

    return violations


def validate_cross_registry(reg: dict, ctx: dict) -> list[Violation]:
    """Cross-registry resolution rules (rule group ``cross_registry``).

    Every reference a spine row makes must resolve against the registry that
    owns the id (D2). ``surfaces`` and ``readinessKey`` resolve against the
    surface / readiness registries; ``canonicalContractRefs`` resolve against
    their owning registry files; no spine ``id`` may re-define an id owned by
    another canonical registry; unresolved refs must be declared.
    """
    violations: list[Violation] = []
    spines = reg.get("spines", [])
    ids = {spine.get("id") for spine in spines}

    surface_ids = ctx.get("surface_ids", set())
    readiness_tokens = ctx.get("readiness_tokens", set())
    policies = set(reg.get("graphMutationPolicies", []))
    ctx_policies = ctx.get("graph_mutation_policies", set())

    for spine in spines:
        spine_id = spine.get("id")

        for surface in spine.get("surfaces", []):
            if surface not in surface_ids:
                violations.append(
                    Violation(
                        "cross_registry.surface_unresolved",
                        "error",
                        f"surface {surface!r} is not a registered surfaceId in surface-capability-registry.json",
                        spine_id,
                    )
                )

        readiness_key = spine.get("readinessKey")
        if readiness_key is not None and readiness_key not in readiness_tokens:
            violations.append(
                Violation(
                    "cross_registry.readiness_key_unresolved",
                    "error",
                    f"readinessKey {readiness_key!r} is not a readiness-vocabulary token "
                    "(D5: presentation-only join, never a certification token)",
                    spine_id,
                )
            )

        policy = spine.get("graphMutationPolicy")
        if policy not in policies and policy not in ctx_policies and policy is not None:
            violations.append(
                Violation(
                    "cross_registry.graph_mutation_policy_divergence",
                    "error",
                    f"graphMutationPolicy {policy!r} is not in the spine registry vocab "
                    "nor the projection plane's graphMutationPolicies vocab",
                    spine_id,
                )
            )

        for ref in spine.get("canonicalContractRefs", []):
            if not isinstance(ref, dict):
                continue
            registry_rel = ref.get("registry")
            if not isinstance(registry_rel, str):
                violations.append(
                    Violation(
                        "cross_registry.contract_registry_missing",
                        "error",
                        "canonicalContractRefs registry must be a path string",
                        spine_id,
                    )
                )
                continue
            if not (
                registry_rel.startswith("packages/shared/contracts/")
                and (ROOT / registry_rel).is_file()
            ):
                violations.append(
                    Violation(
                        "cross_registry.contract_registry_missing",
                        "error",
                        f"canonicalContractRefs registry {registry_rel!r} does not exist under packages/shared/contracts/",
                        spine_id,
                    )
                )
                continue
            strong, weak = _owned_ids_for(registry_rel)
            if strong is None:
                violations.append(
                    Violation(
                        "cross_registry.contract_registry_invalid",
                        "error",
                        f"canonicalContractRefs registry {registry_rel!r} is not valid JSON",
                        spine_id,
                    )
                )
                continue
            for ref_id in ref.get("refIds", []):
                if ref_id in strong:
                    continue
                if ref_id in weak:
                    violations.append(
                        Violation(
                            "cross_registry.contract_ref_id_loose",
                            "warning",
                            f"refId {ref_id!r} in {registry_rel!r} appears only as a loose string, "
                            "not under an owned-id position — verify it is a real owned id",
                            spine_id,
                        )
                    )
                    continue
                violations.append(
                    Violation(
                        "cross_registry.contract_ref_id_unresolved",
                        "error",
                        f"refId {ref_id!r} does not occur in {registry_rel!r}",
                        spine_id,
                    )
                )

        bindings = spine.get("legacyBindings") or {}
        for service in bindings.get("services", []):
            if _is_path_like(service) and not (ROOT / service).exists():
                violations.append(
                    Violation(
                        "cross_registry.legacy_service_missing",
                        "error",
                        f"legacy service path {service!r} does not exist on disk in this checkout — "
                        "a spine row must bind to machinery that exists (tetris inventory gate); "
                        "correct the binding or declare the dependency pending in unresolvedRefs",
                        spine_id,
                    )
                )

        for unresolved in spine.get("unresolvedRefs", []):
            if not isinstance(unresolved, dict):
                violations.append(
                    Violation(
                        "cross_registry.unresolved_ref_incomplete",
                        "error",
                        "unresolvedRefs entry must be an object",
                        spine_id,
                    )
                )
                continue
            has_identifier = any(
                key in unresolved
                and isinstance(unresolved.get(key), str)
                and unresolved[key].strip()
                for key in _UNRESOLVED_REF_IDENTIFIER_KEYS
            )
            missing = [
                key
                for key in _UNRESOLVED_REF_REQUIRED_KEYS
                if not isinstance(unresolved.get(key), str) or not unresolved[key].strip()
            ]
            if not has_identifier or missing:
                violations.append(
                    Violation(
                        "cross_registry.unresolved_ref_incomplete",
                        "error",
                        "unresolvedRefs entry must carry an identifier ('ref' or 'id') plus "
                        f"non-empty {list(_UNRESOLVED_REF_REQUIRED_KEYS)}",
                        spine_id,
                    )
                )
            kind = unresolved.get("kind")
            if kind not in _UNRESOLVED_REF_KINDS:
                violations.append(
                    Violation(
                        "cross_registry.unresolved_ref_kind",
                        "error",
                        f"unresolvedRef kind {kind!r} must be one of {sorted(_UNRESOLVED_REF_KINDS)}",
                        spine_id,
                    )
                )

    # No-parallel-registry: a spine entry id must not collide with an id owned by
    # another canonical registry. Documented cross-plane homonyms are exempt.
    for namespace, owned in ctx.get("owned_id_namespaces", {}).items():
        collisions = sorted((ids & set(owned)) - _CROSS_PLANE_HOMONYM_EXCEPTIONS)
        for spine_id in collisions:
            violations.append(
                Violation(
                    "cross_registry.parallel_id_collision",
                    "error",
                    f"spine id {spine_id!r} collides with a canonical {namespace} owned by another registry — "
                    "a spine row references, never re-defines, an id owned elsewhere",
                    spine_id,
                )
            )

    return violations


def validate_lifecycle_honesty(reg: dict) -> list[Violation]:
    """Lifecycle-honesty rules (rule group ``lifecycle_honesty``).

    ``implementationState`` is repo metadata, never readiness (ADR-011 D5). A
    ``"pending"`` spine must declare where it is heading (an ``unresolvedRefs``
    entry or a documented rationale); lifecycle/tenant/security fields are
    well-typed.
    """
    violations: list[Violation] = []
    for spine in reg.get("spines", []):
        spine_id = spine.get("id")
        state = spine.get("implementationState")
        if state == "pending":
            has_declaration = bool(spine.get("unresolvedRefs"))
            has_rationale = bool(
                isinstance(spine.get("pendingRationale"), str) and spine["pendingRationale"].strip()
            )
            if not has_declaration and not has_rationale:
                violations.append(
                    Violation(
                        "lifecycle_honesty.pending_without_declaration",
                        "error",
                        "pending spine must carry at least one unresolvedRefs entry or a "
                        "documented pendingRationale",
                        spine_id,
                    )
                )

        lifecycle = spine.get("lifecycle")
        if isinstance(lifecycle, dict):
            for field, value in lifecycle.items():
                if not isinstance(value, bool):
                    violations.append(
                        Violation(
                            "lifecycle_honesty.non_boolean_lifecycle",
                            "error",
                            f"lifecycle.{field} must be a boolean",
                            spine_id,
                        )
                    )

        boundary = spine.get("tenantBoundary")
        if isinstance(boundary, dict):
            for field in ("tenantScoped", "consentRequired"):
                if field in boundary and not isinstance(boundary[field], bool):
                    violations.append(
                        Violation(
                            "lifecycle_honesty.tenant_boundary_malformed",
                            "error",
                            f"tenantBoundary.{field} must be a boolean",
                            spine_id,
                        )
                    )
            if "rightsBoundary" in boundary and not isinstance(boundary["rightsBoundary"], str):
                violations.append(
                    Violation(
                        "lifecycle_honesty.tenant_boundary_malformed",
                        "error",
                        "tenantBoundary.rightsBoundary must be a string",
                        spine_id,
                    )
                )

        compliance = spine.get("securityCompliance")
        if isinstance(compliance, dict):
            for field, value in compliance.items():
                if not isinstance(value, str):
                    violations.append(
                        Violation(
                            "lifecycle_honesty.security_compliance_malformed",
                            "error",
                            f"securityCompliance.{field} must be a string",
                            spine_id,
                        )
                    )

    return violations


def validate_ownership(reg: dict) -> list[Violation]:
    """Ownership-integrity rules (rule group ``ownership``).

    Every spine declares its authority and non-ownership boundaries (D1) and
    how it folds existing work into the kernel (D4 legacy bindings).
    """
    violations: list[Violation] = []
    for spine in reg.get("spines", []):
        spine_id = spine.get("id")
        declaration = spine.get("authorityDeclaration")
        if not isinstance(declaration, str) or not declaration.strip():
            violations.append(
                Violation(
                    "ownership.missing_authority_declaration",
                    "error",
                    "authorityDeclaration must be a non-empty statement of what this spine owns",
                    spine_id,
                )
            )
        non_ownership = spine.get("nonOwnershipStatement")
        if not isinstance(non_ownership, str) or not non_ownership.strip():
            violations.append(
                Violation(
                    "ownership.missing_non_ownership_statement",
                    "error",
                    "nonOwnershipStatement must be a non-empty statement of what this spine does NOT own",
                    spine_id,
                )
            )
        if "ownsCanonicalTruth" in spine and not isinstance(spine["ownsCanonicalTruth"], bool):
            violations.append(
                Violation(
                    "ownership.non_boolean_owns_canonical_truth",
                    "error",
                    "ownsCanonicalTruth must be a boolean",
                    spine_id,
                )
            )

        bindings = spine.get("legacyBindings")
        if not isinstance(bindings, dict):
            violations.append(
                Violation(
                    "ownership.missing_legacy_bindings",
                    "error",
                    "legacyBindings object is required",
                    spine_id,
                )
            )
            continue
        missing = [
            field for field in ("aliases", "services", "migrationMode") if field not in bindings
        ]
        if missing:
            violations.append(
                Violation(
                    "ownership.missing_binding_fields",
                    "error",
                    f"legacyBindings missing {missing}",
                    spine_id,
                )
            )
        if (
            isinstance(bindings.get("migrationMode"), str)
            and bindings["migrationMode"] not in MIGRATION_MODES
        ):
            violations.append(
                Violation(
                    "ownership.unknown_migration_mode",
                    "error",
                    f"migrationMode {bindings['migrationMode']!r} must be one of {sorted(MIGRATION_MODES)}",
                    spine_id,
                )
            )
        for field in ("aliases", "services"):
            value = bindings.get(field)
            if value is not None and (
                not isinstance(value, list) or not all(isinstance(item, str) for item in value)
            ):
                violations.append(
                    Violation(
                        "ownership.bad_binding_list",
                        "error",
                        f"legacyBindings.{field} must be a list of strings",
                        spine_id,
                    )
                )

    return violations


def validate_inventory_honesty(reg: dict, ctx: dict) -> list[Violation]:
    """Inventory-honesty rules (rule group ``inventory_honesty``).

    Conservative, advisory-only honesty checks (warnings over errors where the
    registry leaves room for judgment): a spine must not claim it is folding
    existing work into the kernel (``migrationMode "formalize_existing"``)
    while also declaring it has not started (``implementationState "pending"``).
    """
    del ctx  # reserved for future advisory checks; kept for a stable signature
    violations: list[Violation] = []
    for spine in reg.get("spines", []):
        spine_id = spine.get("id")
        bindings = spine.get("legacyBindings") or {}
        if (
            bindings.get("migrationMode") == "formalize_existing"
            and spine.get("implementationState") == "pending"
        ):
            violations.append(
                Violation(
                    "inventory_honesty.formalize_existing_pending",
                    "warning",
                    "migrationMode 'formalize_existing' declares existing work to formalize, but "
                    "implementationState 'pending' declares no work started — reconcile",
                    spine_id,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def validate_all(reg: dict, ctx: Optional[dict] = None) -> list[Violation]:
    """Run every rule group and return a flat, deterministically sorted list.

    Ordering is by rule group (the canonical registry reading order), then by
    violation id, then spine id and message.
    """
    if ctx is None:
        ctx = load_context()
    results = (
        validate_registry_schema(reg)
        + validate_dependency_dag(reg)
        + validate_cross_registry(reg, ctx)
        + validate_conformance_gate(reg)
        + validate_lifecycle_honesty(reg)
        + validate_ownership(reg)
        + validate_inventory_honesty(reg, ctx)
    )
    return sorted(
        results,
        key=lambda v: (
            _GROUP_RANK.get(v.rule, len(_GROUP_ORDER)),
            v.id,
            v.spine_id or "",
            v.message,
        ),
    )
