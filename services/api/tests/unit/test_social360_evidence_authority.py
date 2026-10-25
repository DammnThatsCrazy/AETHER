"""Focused tests for exact Social360 trust and contagion evidence authority."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "social360-evidence-test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from services.social360.evidence_authority import (  # noqa: E402
    RepositorySocialEvidenceStore,
    SocialContagionEvidenceInput,
    SocialEvidenceAuthority,
    SocialEvidenceAuthorityError,
    SocialTrustEdgeInput,
)


TENANT = "tenant-social-evidence"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


class EntityReader:
    async def find_many_for_tenant_entity_ids(self, tenant_id: str, ids: set[str]):
        return ([{"tenant_id": tenant_id, "entity_id": entity_id} for entity_id in sorted(ids)], False)


class SourceReader:
    async def source_provenance_observations(self, *, tenant_id: str, source_id: str):
        return (
            [
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "observation_id": "observation-1",
                    "source_trust": "unverified_ingress",
                    "evidence_ref": {
                        "id": "source-event-1",
                        "type": "event",
                        "source": "bronze_observation",
                        "observedAt": NOW.isoformat(),
                    },
                }
            ],
            False,
        )


class RiskReader:
    async def get_scoped(self, tenant_id: str, signal_id: str):
        return {
            "tenant_id": tenant_id,
            "signal_id": signal_id,
            "subject_kind": "entity",
            "subject_id": "entity-target",
            "observed_at": NOW.isoformat(),
            "source": "risk-model",
            "evidence_refs": [],
        }


class GraphPathReader:
    async def read_paths(self, tenant_id: str, start_entity_id: str):
        return SimpleNamespace(
            tenant_id=tenant_id,
            start_entity_id=start_entity_id,
            available=True,
            paths=(
                SimpleNamespace(
                    entity_ids=("entity-source", "entity-middle", "entity-target"),
                    edge_evidence_refs=(
                        (EvidenceRef(id="edge-1", type="relationship", source="relationship_facts"),),
                        (EvidenceRef(id="edge-2", type="relationship", source="relationship_facts"),),
                    ),
                    edge_observed_at=(
                        "2026-10-24T10:00:00+00:00",
                        "2026-10-24T11:00:00+00:00",
                    ),
                ),
            ),
        )


class InMemoryStore:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    async def append(self, record: dict):
        key = (record["tenant_id"], record["record_id"])
        existing = self.rows.get(key)
        if existing is not None:
            return dict(existing)
        self.rows[key] = dict(record)
        return dict(record)

    async def list_for_subject(self, tenant_id, subject_entity_id, *, assertion_kind, limit, as_of=None):
        rows = [
            dict(row)
            for (row_tenant, _), row in self.rows.items()
            if row_tenant == tenant_id
            and row.get("subject_entity_id") == subject_entity_id
            and row.get("assertion_kind") == assertion_kind
            and (as_of is None or datetime.fromisoformat(row["effective_at"]) <= as_of)
        ]
        return rows[:limit], len(rows) > limit


def _authority(store=None):
    return SocialEvidenceAuthority(
        store=store or InMemoryStore(),
        entity_reader=EntityReader(),
        source_reader=SourceReader(),
        risk_signal_reader=RiskReader(),
        graph_path_reader=GraphPathReader(),
    )


def _contagion_event():
    return SocialContagionEvidenceInput(
        source_id="connector:network-a",
        source_observation_id="observation-1",
        source_revision_id="revision-4",
        source_event_id="source-event-1",
        source_entity_id="entity-source",
        target_entity_id="entity-target",
        path_entity_ids=["entity-source", "entity-middle", "entity-target"],
        observed_at=NOW,
        effective_at=NOW,
        risk_signal_ids=["risk-target-1"],
    )


@pytest.mark.asyncio
async def test_social_contagion_requires_exact_source_path_risk_and_preserves_correlation():
    authority = _authority()
    row = await authority.record_social_contagion_evidence(
        TENANT,
        _contagion_event(),
        actor_id="operator-1",
        actor_type="tenant_user",
    )

    assert row["tenant_id"] == TENANT
    assert row["subject_entity_id"] == "entity-target"
    assert row["path_entity_ids"] == ["entity-source", "entity-middle", "entity-target"]
    assert row["source_trust_classification"] == "unverified_ingress"
    assert row["claim_state"] == "correlated"
    assert row["causal_status"] == "unverified"
    assert row["policy_state"] == "unknown"
    assert {ref["id"] for ref in row["path_evidence_refs"]} == {"edge-1", "edge-2"}
    read = await authority.read_social_contagion_evidence(TENANT, "entity-target", limit=10)
    assert read.available is True
    assert len(read.records) == 1
    assert read.records[0]["record_id"] == row["record_id"]


@pytest.mark.asyncio
async def test_social_contagion_rejects_risk_signal_bound_to_another_subject():
    class ForeignRiskReader(RiskReader):
        async def get_scoped(self, tenant_id: str, signal_id: str):
            row = await super().get_scoped(tenant_id, signal_id)
            row["subject_id"] = "entity-not-on-path"
            return row

    authority = SocialEvidenceAuthority(
        store=InMemoryStore(),
        entity_reader=EntityReader(),
        source_reader=SourceReader(),
        risk_signal_reader=ForeignRiskReader(),
        graph_path_reader=GraphPathReader(),
    )
    with pytest.raises(SocialEvidenceAuthorityError, match="exact path entity"):
        await authority.record_social_contagion_evidence(
            TENANT,
            _contagion_event(),
            actor_id="operator-1",
            actor_type="tenant_user",
        )


@pytest.mark.asyncio
async def test_trust_edge_requires_operator_namespace_and_does_not_infer_score():
    authority = _authority()
    event = SocialTrustEdgeInput(
        source_id="aether.operator:operator-1",
        source_observation_id="manual-observation-1",
        source_revision_id="manual-revision-1",
        source_event_id="manual-event-1",
        source_entity_id="entity-source",
        target_entity_id="entity-target",
        observed_at=NOW,
        effective_at=NOW,
        assertion_note="Operator supplied a trusted relationship attestation.",
    )
    row = await authority.record_trust_edge(
        TENANT,
        event,
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    assert row["assertion_state"] == "operator_asserted"
    assert row["causal_status"] == "not_applicable"
    assert row["actor_id"] == "operator-1"
    read = await authority.read_trust_edge_evidence(TENANT, "entity-target")
    assert len(read.records) == 1
    assert read.records[0]["assertion_note"].startswith("Operator supplied")


@pytest.mark.asyncio
async def test_store_retries_same_source_event_idempotently(monkeypatch):
    import repositories.repos

    async def no_database_pool():
        return None

    monkeypatch.setattr(repositories.repos, "get_pool", no_database_pool)
    store = RepositorySocialEvidenceStore()
    store._local_rows.clear()
    authority = _authority(store)
    first = await authority.record_social_contagion_evidence(
        TENANT,
        _contagion_event(),
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    second = await authority.record_social_contagion_evidence(
        TENANT,
        _contagion_event(),
        actor_id="operator-1",
        actor_type="tenant_user",
    )
    assert first["record_id"] == second["record_id"]
    assert first["recorded_at"] == second["recorded_at"]
