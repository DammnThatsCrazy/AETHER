"""Wave 3b read-helper tests — reads.py canonical read surfaces.

Envelopes are thin over the substrate and honest:
* no persisted run => None / ``no_persisted_fidelity_run`` degraded (never 0);
* materialized dimensions carried, unmaterialized stay None;
* the explain basis degrades motif matching and unassessed incentive honestly;
* influence with no evidence-backed path is an empty decomposition, never a
  synthesized figure.
"""

from __future__ import annotations

import asyncio

from services.relationship_intelligence.coordinator import (
    RelationshipSpineCoordinator,
    materialize_observations,
    relationship_ref_for,
)
from services.relationship_intelligence.reads import (
    fidelity_run_id_for,
    read_influence,
    read_latest_fidelity,
    read_relationship_basis,
)
from services.relationship_fidelity.engine import FIDELITY_MODE_ENV


def _set_mode(monkeypatch, mode: str) -> None:
    monkeypatch.setenv(FIDELITY_MODE_ENV, mode)


def _records() -> list[dict]:
    return [
        {
            "id": "r1",
            "predicate": "FOLLOWS",
            "direction": "outgoing",
            "source_key": "src-a",
            "observed_at": "2026-08-01T00:00:00Z",
        },
        {
            "id": "r2",
            "predicate": "FOLLOWS",
            "direction": "incoming",
            "source_key": "src-b",
            "observed_at": "2026-08-20T00:00:00Z",
        },
        {
            "id": "r3",
            "predicate": "FOLLOWS",
            "direction": "outgoing",
            "source_key": "src-b",
            "observed_at": "2026-08-21T00:00:00Z",
        },
    ]


def _persist_via_coordinator(monkeypatch, tenant_id: str, source: str, target: str, *, mode: str = "enforce"):
    _set_mode(monkeypatch, mode)

    async def _seed():
        coord = RelationshipSpineCoordinator()
        ref = relationship_ref_for(source, target)
        return await coord.run_for_relationship(
            tenant_id=tenant_id,
            relationship_ref=ref,
            source_entity_id=source,
            target_entity_id=target,
            observations=materialize_observations(_records()),
            enrich_incentives=False,
        )

    return asyncio.run(_seed())


def test_read_latest_fidelity_none_when_nothing_persisted(monkeypatch):
    _set_mode(monkeypatch, "enforce")

    async def _read():
        return await read_latest_fidelity("t-no-read", relationship_ref_for("s", "t"))

    assert asyncio.run(_read()) is None  # no data => None, never a zero vector


def test_read_latest_fidelity_returns_persisted_surface(monkeypatch):
    tenant = "t-read-1"
    seed = _persist_via_coordinator(monkeypatch, tenant, "s", "t", mode="enforce")
    assert seed.persisted is True

    async def _read():
        return await read_latest_fidelity(tenant, seed.relationship_ref)

    latest = asyncio.run(_read())
    assert latest is not None
    assert latest["available"] is True
    assert latest["degraded"] is False
    assert latest["kind"] == "fidelity_vector_surface"
    assert latest["run_id"] == seed.run_id
    assert latest["relationship_ref"] == seed.relationship_ref
    assert latest["mode"] == "enforce"
    vector = latest["vector"]
    assert vector["status"] == "current"
    assert vector["observation_count"] == 3
    assert vector["independent_evidence_count"] == 2
    # unknown is never 0: unmaterialized dims stay None in the wire contract
    assert vector.get("outcome_support") is None
    assert vector.get("economic_significance") is None


def test_read_relationship_basis_degraded_before_any_run(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-basis-empty"

    async def _read():
        return await read_relationship_basis(tenant, "s", "t")

    basis = asyncio.run(_read())
    assert basis["available"] is True  # the basis itself is a valid read
    assert basis["sections"]["fidelity"]["available"] is False
    assert basis["sections"]["fidelity"]["reason_code"] == "no_persisted_fidelity_run"
    assert "no_persisted_fidelity_run" in basis["degraded"]
    # motif matching is honestly degraded, not a fabricated no-match
    assert basis["sections"]["motifs"]["state"] == "insufficient_data"
    assert basis["sections"]["motifs"]["available"] is False
    # social360 registry row is in_flight / provider-less — reported honestly
    assert basis["surface"]["provider_registered"] is False
    assert basis["surface"]["registry_state"] == "in_flight"


def test_read_relationship_basis_enriched_after_persist(monkeypatch):
    tenant = "t-basis-full"
    seed = _persist_via_coordinator(monkeypatch, tenant, "s", "t", mode="enforce")

    async def _read():
        return await read_relationship_basis(tenant, "s", "t")

    basis = asyncio.run(_read())
    assert seed.persisted is True
    fidelity = basis["sections"]["fidelity"]
    assert fidelity["available"] is True
    assert fidelity["run_id"] == seed.run_id
    assert fidelity["observation_count"] == 3
    assert "reciprocity" in fidelity["materialized_dimensions"]
    assert fidelity["quality_overall"] == "ready"
    # incentive section: run was NOT incentive-assessed => honest insufficient_data
    incentive = basis["sections"]["incentive"]
    assert incentive["available"] is False
    assert incentive["state"] == "insufficient_data"
    assert incentive["reason_code"] == "incentive_not_assessed_on_run"
    # registered predicate semantics are static + available
    predicates = basis["sections"]["registered_predicates"]
    assert predicates["available"] is True
    assert predicates["registered_predicate_count"] >= 1


def test_read_influence_empty_path_is_never_a_figure(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-inf-empty"

    async def _read():
        return await read_influence(tenant, "s", "t")

    envelope = asyncio.run(_read())
    assert envelope["available"] is False
    assert envelope["degraded"] is True
    assert envelope["degraded_reason"] == "no_evidence_backed_path"
    decomp = envelope["decomposition"]
    assert decomp["decision"] == "empty"
    assert decomp["propagation_certified"] is False
    assert decomp["hop_count"] == 0
    assert len(decomp["components"]) == 9
    # every component value is None — never a 0 and never synthesized
    for component in decomp["components"]:
        assert component["value"] is None
        assert component["state"] == "insufficient_data"
    assert envelope["insufficient_data"] == []


def test_read_influence_certified_hop_with_no_measurements(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-inf-cert"
    hop = {"type": "FOLLOWS", "from": "s", "to": "t", "properties": {}}

    async def _read():
        return await read_influence(
            tenant, "s", "t", path_edges=[hop], fidelity_by_hop=None
        )

    envelope = asyncio.run(_read())
    # a governed single hop certifies propagation but with no measurements every
    # component is degraded — never fabricated upward.
    assert envelope["available"] is True
    assert envelope["degraded"] is True
    decomp = envelope["decomposition"]
    assert decomp["decision"] == "pass"
    assert decomp["propagation_certified"] is True
    assert decomp["hop_count"] == 1
    assert decomp["min_epistemic_ceiling"] is not None
    assert len(decomp["components"]) == 9
    for component in decomp["components"]:
        assert component["value"] is None
    # earned downstream is not_applicable on a single hop; the other 8 are
    # insufficient_data -> reported by id in the envelope.
    assert len(envelope["insufficient_data"]) == 8
    assert "earned_downstream_amplification" not in envelope["insufficient_data"]


def test_read_influence_measurements_certify_components(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    tenant = "t-inf-meas"
    hop = {"type": "FOLLOWS", "from": "s", "to": "t", "properties": {}}
    measurements = {
        0: {
            "interaction_frequency": 0.8,
            "interaction_depth": 0.7,
            "persistence": 0.5,
            "reciprocity": 0.6,
        }
    }

    async def _read():
        return await read_influence(
            tenant, "s", "t", path_edges=[hop], fidelity_by_hop=measurements
        )

    envelope = asyncio.run(_read())
    decomp = envelope["decomposition"]
    assert decomp["decision"] == "pass"
    by_id = {c["component_id"]: c for c in decomp["components"]}
    # measured components carry values; unmeasured stay None
    assert by_id["raw_attention"]["value"] is not None
    assert by_id["relationship_weighted_attention"]["value"] is not None
    assert by_id["novel_attention"]["value"] is None
    assert by_id["earned_downstream_amplification"]["state"] == "not_applicable"


def test_fidelity_run_id_derivation_is_deterministic(monkeypatch):
    _set_mode(monkeypatch, "enforce")
    assert fidelity_run_id_for("x::y") == fidelity_run_id_for("x::y")
    assert fidelity_run_id_for("x::y") != fidelity_run_id_for("x::z")
    assert fidelity_run_id_for("x::y").startswith("run_fidelity_fid_")
