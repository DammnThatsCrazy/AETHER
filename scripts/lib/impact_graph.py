"""Deterministic component, contract, and deployable impact indexing.

``config/impact_graph.json`` is a small relationship registry, not a second
runtime topology.  Its references are checked against the canonical
verification-router and test-suite registries before an index can be built.
The index is read-only: changed paths become direct nodes, and directed impact
edges are traversed in stable lexical order to produce the transitive scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from scripts.lib.test_suites import TestSuite, load_suites
from scripts.lib.verification_router import (
    VerificationRouterConfig,
    classify_impact,
    load_router_registry,
    matches as router_matches,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = ROOT / "config" / "impact_graph.json"
SCHEMA_VERSION = 1
KINDS = ("component", "contract", "deployable")
_TOP_KEYS = {"schema_version", "canonical_source", "components", "contracts", "deployables"}


class ImpactGraphConfigError(ValueError):
    """The impact graph is incomplete or references an unknown authority."""


def node_ref(kind: str, identifier: str) -> str:
    if kind not in KINDS or not identifier.strip():
        raise ValueError(f"invalid impact graph node {kind!r}:{identifier!r}")
    return f"{kind}:{identifier}"


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ImpactGraphConfigError(f"{where} must be an object")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImpactGraphConfigError(f"{where} must be a non-empty string")
    return value


def _string_list(value: Any, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ImpactGraphConfigError(
            f"{where} must be a {'possibly empty ' if allow_empty else ''}list of strings"
        )
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ImpactGraphConfigError(f"{where} must contain only non-empty strings")
    if len(value) != len(set(value)):
        raise ImpactGraphConfigError(f"{where} must not contain duplicates")
    return tuple(value)


@dataclass(frozen=True)
class ComponentDefinition:
    id: str
    paths: tuple[str, ...]
    domains: tuple[str, ...]
    contract_ids: tuple[str, ...]
    deployable_ids: tuple[str, ...]
    depends_on_components: tuple[str, ...]


@dataclass(frozen=True)
class ContractDefinition:
    id: str
    paths: tuple[str, ...]
    registry_ref: str
    suite_ids: tuple[str, ...]


@dataclass(frozen=True)
class DeployableDefinition:
    id: str
    paths: tuple[str, ...]
    component_ids: tuple[str, ...]
    contract_ids: tuple[str, ...]
    depends_on_deployables: tuple[str, ...]


@dataclass(frozen=True)
class ImpactGraph:
    schema_version: int
    canonical_source: str
    components: Mapping[str, ComponentDefinition]
    contracts: Mapping[str, ContractDefinition]
    deployables: Mapping[str, DeployableDefinition]
    edges: Mapping[str, tuple[str, ...]]
    test_suites: tuple[TestSuite, ...]

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                (
                    *(node_ref("component", identifier) for identifier in self.components),
                    *(node_ref("contract", identifier) for identifier in self.contracts),
                    *(node_ref("deployable", identifier) for identifier in self.deployables),
                )
            )
        )

    def node_kind(self, reference: str) -> str:
        kind, separator, identifier = reference.partition(":")
        if not separator or kind not in KINDS or identifier not in getattr(self, f"{kind}s"):
            raise ImpactGraphConfigError(f"unknown graph node {reference!r}")
        return kind

    def direct_nodes(self, changed_paths: Sequence[str]) -> tuple[str, ...]:
        changed = tuple(sorted(set(changed_paths)))
        direct: set[str] = set()
        for kind, definitions in (
            ("component", self.components),
            ("contract", self.contracts),
            ("deployable", self.deployables),
        ):
            for identifier, definition in definitions.items():
                if any(
                    _path_matches(path, pattern) for path in changed for pattern in definition.paths
                ):
                    direct.add(node_ref(kind, identifier))
        return tuple(sorted(direct))

    def transitive_nodes(self, direct_nodes: Iterable[str]) -> tuple[str, ...]:
        """Return direct nodes plus all downstream impact edges."""
        seen = set(direct_nodes)
        for reference in seen:
            self.node_kind(reference)
        frontier = sorted(seen)
        while frontier:
            current = frontier.pop(0)
            for target in self.edges.get(current, ()):
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)
            frontier.sort()
        return tuple(sorted(seen))


@dataclass(frozen=True)
class ShadowComparison:
    classification: str
    expected_nodes: tuple[str, ...]
    targeted_nodes: tuple[str, ...]
    legacy_nodes: tuple[str, ...]
    targeted_missing: tuple[str, ...]
    legacy_extra: tuple[str, ...]
    legacy_missing: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "expected_nodes": list(self.expected_nodes),
            "targeted_nodes": list(self.targeted_nodes),
            "legacy_nodes": list(self.legacy_nodes),
            "targeted_missing": list(self.targeted_missing),
            "legacy_extra": list(self.legacy_extra),
            "legacy_missing": list(self.legacy_missing),
        }


def _path_matches(path: str, pattern: str) -> bool:
    """Use the router's repository-relative ``/**`` semantics for consistency."""
    return router_matches(path, pattern) or fnmatchcase(path, pattern)


def _parse_definition_list(raw: Any, key: str) -> list[Mapping[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise ImpactGraphConfigError(f"impact graph.{key} must be a non-empty list")
    return [
        _require_mapping(item, f"impact graph.{key}[{index}]") for index, item in enumerate(raw)
    ]


def _parse_ids(raw: Any, where: str) -> tuple[str, ...]:
    return _string_list(raw, where, allow_empty=True)


def load_impact_graph(
    path: str | Path = DEFAULT_REGISTRY,
    *,
    root: Path = ROOT,
    router: VerificationRouterConfig | None = None,
    suites: Sequence[TestSuite] | None = None,
) -> ImpactGraph:
    """Load the graph and validate its bindings to existing registries."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImpactGraphConfigError(f"cannot read impact graph {resolved}: {exc}") from exc
    top = _require_mapping(raw, "impact graph")
    unknown = sorted(set(top) - _TOP_KEYS)
    if unknown:
        raise ImpactGraphConfigError(f"impact graph has unknown key(s): {', '.join(unknown)}")
    if top.get("schema_version") != SCHEMA_VERSION:
        raise ImpactGraphConfigError("impact graph.schema_version must be 1")
    canonical_source = _require_string(top.get("canonical_source"), "impact graph.canonical_source")
    router = router or load_router_registry(root / "config" / "verification_router.yaml")
    suites = tuple(suites or load_suites(root / "config" / "test_suites.yaml", root=root))
    suite_ids = {suite.id for suite in suites}

    components: dict[str, ComponentDefinition] = {}
    for index, item in enumerate(_parse_definition_list(top.get("components"), "components")):
        identifier = _require_string(item.get("id"), f"components[{index}].id")
        if identifier in components:
            raise ImpactGraphConfigError(f"duplicate component id {identifier!r}")
        allowed = {
            "id",
            "paths",
            "domains",
            "contract_ids",
            "deployable_ids",
            "depends_on_components",
        }
        extra = sorted(set(item) - allowed)
        if extra:
            raise ImpactGraphConfigError(
                f"component {identifier} has unknown key(s): {', '.join(extra)}"
            )
        definition = ComponentDefinition(
            identifier,
            _string_list(item.get("paths"), f"component {identifier}.paths"),
            _string_list(item.get("domains"), f"component {identifier}.domains"),
            _parse_ids(item.get("contract_ids"), f"component {identifier}.contract_ids"),
            _parse_ids(item.get("deployable_ids"), f"component {identifier}.deployable_ids"),
            _parse_ids(
                item.get("depends_on_components"), f"component {identifier}.depends_on_components"
            ),
        )
        for domain in definition.domains:
            if domain not in router.domains:
                raise ImpactGraphConfigError(
                    f"component {identifier} references unknown router domain {domain!r}"
                )
        _ensure_paths(definition.paths, root, f"component {identifier}")
        components[identifier] = definition

    contracts: dict[str, ContractDefinition] = {}
    for index, item in enumerate(_parse_definition_list(top.get("contracts"), "contracts")):
        identifier = _require_string(item.get("id"), f"contracts[{index}].id")
        if identifier in contracts:
            raise ImpactGraphConfigError(f"duplicate contract id {identifier!r}")
        allowed = {"id", "paths", "registry_ref", "suite_ids"}
        extra = sorted(set(item) - allowed)
        if extra:
            raise ImpactGraphConfigError(
                f"contract {identifier} has unknown key(s): {', '.join(extra)}"
            )
        definition = ContractDefinition(
            identifier,
            _string_list(item.get("paths"), f"contract {identifier}.paths"),
            _require_string(item.get("registry_ref"), f"contract {identifier}.registry_ref"),
            _parse_ids(item.get("suite_ids"), f"contract {identifier}.suite_ids"),
        )
        _ensure_paths(definition.paths, root, f"contract {identifier}")
        _ensure_paths((definition.registry_ref,), root, f"contract {identifier}.registry_ref")
        unknown_suites = sorted(set(definition.suite_ids) - suite_ids)
        if unknown_suites:
            raise ImpactGraphConfigError(
                f"contract {identifier} references unknown test suite(s): {', '.join(unknown_suites)}"
            )
        contracts[identifier] = definition

    deployables: dict[str, DeployableDefinition] = {}
    for index, item in enumerate(_parse_definition_list(top.get("deployables"), "deployables")):
        identifier = _require_string(item.get("id"), f"deployables[{index}].id")
        if identifier in deployables:
            raise ImpactGraphConfigError(f"duplicate deployable id {identifier!r}")
        allowed = {"id", "paths", "component_ids", "contract_ids", "depends_on_deployables"}
        extra = sorted(set(item) - allowed)
        if extra:
            raise ImpactGraphConfigError(
                f"deployable {identifier} has unknown key(s): {', '.join(extra)}"
            )
        definition = DeployableDefinition(
            identifier,
            _string_list(item.get("paths"), f"deployable {identifier}.paths"),
            _parse_ids(item.get("component_ids"), f"deployable {identifier}.component_ids"),
            _parse_ids(item.get("contract_ids"), f"deployable {identifier}.contract_ids"),
            _parse_ids(
                item.get("depends_on_deployables"),
                f"deployable {identifier}.depends_on_deployables",
            ),
        )
        _ensure_paths(definition.paths, root, f"deployable {identifier}")
        deployables[identifier] = definition

    component_ids = set(components)
    contract_ids = set(contracts)
    deployable_ids = set(deployables)
    for definition in components.values():
        _ensure_refs(
            definition.contract_ids, contract_ids, f"component {definition.id}.contract_ids"
        )
        _ensure_refs(
            definition.deployable_ids, deployable_ids, f"component {definition.id}.deployable_ids"
        )
        _ensure_refs(
            definition.depends_on_components,
            component_ids,
            f"component {definition.id}.depends_on_components",
        )
    for definition in deployables.values():
        _ensure_refs(
            definition.component_ids, component_ids, f"deployable {definition.id}.component_ids"
        )
        _ensure_refs(
            definition.contract_ids, contract_ids, f"deployable {definition.id}.contract_ids"
        )
        _ensure_refs(
            definition.depends_on_deployables,
            deployable_ids,
            f"deployable {definition.id}.depends_on_deployables",
        )

    edges: dict[str, set[str]] = {
        reference: set()
        for reference in (
            *(node_ref("component", identifier) for identifier in components),
            *(node_ref("contract", identifier) for identifier in contracts),
            *(node_ref("deployable", identifier) for identifier in deployables),
        )
    }

    def add(source: str, target: str) -> None:
        edges[source].add(target)

    for component in components.values():
        source = node_ref("component", component.id)
        for contract_id in component.contract_ids:
            add(source, node_ref("contract", contract_id))
        for deployable_id in component.deployable_ids:
            add(source, node_ref("deployable", deployable_id))
        for dependency_id in component.depends_on_components:
            add(node_ref("component", dependency_id), source)
    for deployable in deployables.values():
        source = node_ref("deployable", deployable.id)
        for component_id in deployable.component_ids:
            add(node_ref("component", component_id), source)
        for contract_id in deployable.contract_ids:
            add(node_ref("contract", contract_id), source)
        for dependency_id in deployable.depends_on_deployables:
            add(node_ref("deployable", dependency_id), source)

    return ImpactGraph(
        SCHEMA_VERSION,
        canonical_source,
        components,
        contracts,
        deployables,
        {source: tuple(sorted(targets)) for source, targets in sorted(edges.items())},
        tuple(sorted(suites, key=lambda suite: suite.id)),
    )


def _ensure_paths(paths: Iterable[str], root: Path, where: str) -> None:
    for path in paths:
        if not (root / path).is_file():
            raise ImpactGraphConfigError(f"{where} references missing file {path!r}")


def _ensure_refs(references: Iterable[str], known: set[str], where: str) -> None:
    unknown = sorted(set(references) - known)
    if unknown:
        raise ImpactGraphConfigError(f"{where} references unknown id(s): {', '.join(unknown)}")


def build_impact_index(
    changed_paths: Sequence[str],
    graph: ImpactGraph | None = None,
    *,
    requested_lane: str | None = None,
    router: VerificationRouterConfig | None = None,
) -> dict[str, Any]:
    """Build one stable graph index and preserve router evidence alongside it."""
    graph = graph or load_impact_graph(router=router)
    router = router or load_router_registry(ROOT / "config" / "verification_router.yaml")
    changed = tuple(sorted(set(changed_paths)))
    direct = graph.direct_nodes(changed)
    transitive = graph.transitive_nodes(direct)
    router_impact = classify_impact(changed, router, requested_lane)
    known_suites = {suite.id for suite in graph.test_suites}
    selected_suites = tuple(sorted(set(router_impact.selected_checks) & known_suites))
    unresolved = tuple(
        sorted(
            set(changed)
            - {
                path
                for kind, definitions in (
                    ("component", graph.components),
                    ("contract", graph.contracts),
                    ("deployable", graph.deployables),
                )
                for definition in definitions.values()
                for path in changed
                if any(_path_matches(path, pattern) for pattern in definition.paths)
            }
        )
    )
    by_kind = {
        kind: tuple(
            sorted(
                reference.split(":", 1)[1]
                for reference in transitive
                if reference.startswith(f"{kind}:")
            )
        )
        for kind in KINDS
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "changed_files": list(changed),
        "direct_nodes": list(direct),
        "transitive_nodes": list(transitive),
        "impacted_components": list(by_kind["component"]),
        "impacted_contracts": list(by_kind["contract"]),
        "impacted_deployables": list(by_kind["deployable"]),
        "unresolved_paths": list(unresolved),
        "router": {
            "affected_domains": list(router_impact.affected_domains),
            "global_change": router_impact.global_change,
            "minimum_lane": router_impact.minimum_lane,
            "selected_lane": router_impact.selected_lane,
            "followup_required": router_impact.followup_required,
            "selected_checks": list(router_impact.selected_checks),
            "selected_test_suites": list(selected_suites),
        },
    }


def compare_shadow_scopes(
    *,
    expected_nodes: Iterable[str],
    targeted_nodes: Iterable[str],
    legacy_nodes: Iterable[str],
) -> ShadowComparison:
    """Classify targeted misses and legacy broad results against graph truth."""
    expected = tuple(sorted(set(expected_nodes)))
    targeted = tuple(sorted(set(targeted_nodes)))
    legacy = tuple(sorted(set(legacy_nodes)))
    targeted_missing = tuple(sorted(set(expected) - set(targeted)))
    legacy_extra = tuple(sorted(set(legacy) - set(expected)))
    legacy_missing = tuple(sorted(set(expected) - set(legacy)))
    if targeted_missing and legacy_extra:
        classification = "targeted_miss_and_legacy_broad"
    elif targeted_missing:
        classification = "targeted_miss"
    elif legacy_extra:
        classification = "legacy_broad_result"
    elif legacy_missing:
        classification = "legacy_narrow_result"
    else:
        classification = "equivalent"
    return ShadowComparison(
        classification,
        expected,
        targeted,
        legacy,
        targeted_missing,
        legacy_extra,
        legacy_missing,
    )


__all__ = [
    "DEFAULT_REGISTRY",
    "ImpactGraph",
    "ImpactGraphConfigError",
    "ShadowComparison",
    "build_impact_index",
    "compare_shadow_scopes",
    "load_impact_graph",
    "node_ref",
]
