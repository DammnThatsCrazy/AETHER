"""TS <-> Python parity for the principal <-> agent lineage contract.

`packages/shared/agent-lineage.ts` and `shared/agent_lineage/{vocabulary,models}.py`
are hand-authored twins; this fails on drift in any vocabulary, budget constant,
or interface field set. Also pins the structural invariants: weak evidence
classes are never proof classes, weak cluster bases are a subset of cluster
bases, and unknown aggregates are Optional (never defaulted to zero).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "services" / "api"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.agent_lineage import models as M  # noqa: E402
from shared.agent_lineage import vocabulary as V  # noqa: E402

TS = (REPO_ROOT / "packages" / "shared" / "agent-lineage.ts").read_text()

_VOCAB = {
    "actorRoles": V.ACTOR_ROLES,
    "controlModes": V.CONTROL_MODES,
    "authorityTypes": V.AUTHORITY_TYPES,
    "authorityResolutionStatuses": V.AUTHORITY_RESOLUTION_STATUSES,
    "agentHierarchyLevels": V.AGENT_HIERARCHY_LEVELS,
    "principalEvidenceClasses": V.PRINCIPAL_EVIDENCE_CLASSES,
    "principalResolutionStatuses": V.PRINCIPAL_RESOLUTION_STATUSES,
    "lineageRelationshipTypes": V.LINEAGE_RELATIONSHIP_TYPES,
    "relationshipStatuses": V.RELATIONSHIP_STATUSES,
    "confidenceFactors": V.CONFIDENCE_FACTORS,
    "lineageStatuses": V.LINEAGE_STATUSES,
    "completenessStates": V.COMPLETENESS_STATES,
    "clusterKinds": V.CLUSTER_KINDS,
    "clusterBases": V.CLUSTER_BASES,
    "attributionClasses": V.ATTRIBUTION_CLASSES,
    "queryModes": V.QUERY_MODES,
    "fanoutRiskSignals": V.FANOUT_RISK_SIGNALS,
    "riskAttributionKinds": V.RISK_ATTRIBUTION_KINDS,
    "riskPropagationKinds": V.RISK_PROPAGATION_KINDS,
    "executionVerificationStates": V.EXECUTION_VERIFICATION_STATES,
}

_INTERFACES = {
    "ConfidenceFactors": M.ConfidenceFactors,
    "Disclosure": M.Disclosure,
    "ActorContext": M.ActorContext,
    "AuthorityContext": M.AuthorityContext,
    "ExecutionContext": M.ExecutionContext,
    "ProtocolContext": M.ProtocolContext,
    "LineageRow": M.LineageRow,
    "LineageSummary": M.LineageSummary,
    "AgentLineageCounts": M.AgentLineageCounts,
    "ClusterBasis": M.ClusterBasis,
    "LineageCluster": M.LineageCluster,
    "TreeNode": M.TreeNode,
    "Page": M.Page,
}


def _ts_array(name: str) -> tuple[str, ...]:
    m = re.search(rf"export const {name} = \[(.*?)\] as const;", TS, re.S)
    assert m, f"missing TS array {name}"
    return tuple(re.findall(r"'([^']+)'", m.group(1)))


def _ts_interface_fields(name: str) -> set[str]:
    m = re.search(rf"export interface {name}(?:<T>)? \{{(.*?)\n\}}", TS, re.S)
    assert m, f"missing TS interface {name}"
    return set(re.findall(r"^\s{2}([a-z_]+)\??:", m.group(1), re.M))


def test_vocabularies_match():
    for ts_name, py in _VOCAB.items():
        assert _ts_array(ts_name) == tuple(py), ts_name


def test_proof_and_weak_subsets_match():
    proof = tuple(c for c in V.PRINCIPAL_EVIDENCE_CLASSES if c in V.PRINCIPAL_PROOF_EVIDENCE_CLASSES)
    assert _ts_array("principalProofEvidenceClasses") == proof
    weak = tuple(c for c in V.CLUSTER_BASES if c in V.WEAK_CLUSTER_BASES)
    assert _ts_array("weakClusterBases") == weak


def test_budget_constants_match():
    for ts_name, value in {
        "interactiveMaxNodes": V.INTERACTIVE_MAX_NODES,
        "interactiveMaxEdges": V.INTERACTIVE_MAX_EDGES,
        "minDurableDelegationDepth": V.MIN_DURABLE_DELEGATION_DEPTH,
        "defaultPageSize": V.DEFAULT_PAGE_SIZE,
        "maxPageSize": V.MAX_PAGE_SIZE,
    }.items():
        assert re.search(rf"export const {ts_name} = {value};", TS), ts_name


def test_interface_fields_match():
    for ts_name, model in _INTERFACES.items():
        assert _ts_interface_fields(ts_name) == set(model.model_fields), ts_name


def test_confidence_factors_cover_vocabulary():
    assert tuple(M.ConfidenceFactors.model_fields) == tuple(V.CONFIDENCE_FACTORS)


def test_weak_evidence_is_never_proof():
    weak = {"BEHAVIORALLY_INFERRED", "INFRASTRUCTURE_CORRELATED", "TEMPORALLY_CORRELATED", "UNKNOWN"}
    assert not (weak & V.PRINCIPAL_PROOF_EVIDENCE_CLASSES)
    assert V.PRINCIPAL_PROOF_EVIDENCE_CLASSES <= set(V.PRINCIPAL_EVIDENCE_CLASSES)
    assert V.WEAK_CLUSTER_BASES <= set(V.CLUSTER_BASES)


def test_unknown_aggregates_are_optional_not_zero():
    for field in ("direct_agents", "indirect_agents", "agent_runs", "active_agents"):
        assert M.LineageSummary.model_fields[field].default is None
    for field in ("direct_child_count", "recursive_descendant_count"):
        assert M.AgentLineageCounts.model_fields[field].default is None


def test_min_depth_envelope():
    assert V.MIN_DURABLE_DELEGATION_DEPTH >= 32
