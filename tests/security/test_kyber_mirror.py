"""The Kyber Tenant Mirror invariant, one claim per test.

The invariant: the tenant-visible result Aether returns for a tenant, query and
contract version is the same result the Tenant Mirror returns. Kyber may add
operator diagnostics; it may never recompute a tenant-visible value differently.

Each test below proves one property that invariant depends on, and each is
written so that breaking the property breaks the test:

* representation differences (key order, timestamp spelling) are not divergence,
  but a real value change is;
* diagnostics are additive — attaching them leaves the digest byte-identical;
* a contract bump changes the digest even when the bytes do not, so a stale
  mirror cannot read as parity;
* a divergence is *located* — path and both values — because "the digests
  differ" is not actionable during an incident;
* an unknown surface and a parity-exempt surface are refused, never answered
  with an empty payload;
* the service reaches a tenant only through the scoped gateway, proven by
  tripwiring every other read path in the graph plane.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from shared.common.common import BadRequestError, NotFoundError  # noqa: E402

from services.kyber.mirror import (  # noqa: E402
    DIAGNOSTIC_SECTIONS,
    PRESENTATION_KEYS,
    SURFACE_VERTEX_TYPES,
    TenantMirrorService,
    canonical_payload,
    compare,
    digest_tenant_visible,
    empty_diagnostics,
    get_gateway,
    reset_gateway,
    set_gateway,
)
from services.kyber.mirror.parity import MAX_REPORTED_DIVERGENCES  # noqa: E402

TENANT = "tenant-mirror-alpha"
CONTRACT = "1.0.0"


# ── Fakes ────────────────────────────────────────────────────────────────────


class RecordingGateway:
    """A scoped-gateway stand-in that records every read it was asked for.

    The recording is the point: the mirror is supposed to have exactly one way
    to reach a tenant, so a test can assert both that this object was used and
    that nothing else was.
    """

    def __init__(self, vertices: Optional[dict[str, list[dict[str, Any]]]] = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.vertices = vertices or {}

    async def query(
        self,
        request: Any,
        *,
        tenant_id: str,
        vertex_type: Optional[str] = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        self.calls.append(
            {"tenant_id": tenant_id, "vertex_type": vertex_type, "limit": limit}
        )
        rows = list(self.vertices.get(vertex_type or "", []))
        return {
            "tenantVisible": {
                "tenant_id": tenant_id,
                "vertex_type": vertex_type,
                "vertices": rows,
                "vertex_count": len(rows),
                "truncated": False,
            },
            "operatorDiagnostics": {
                "surface": "query",
                "capability": "kyber.graph.tenant.read",
                "granted_disclosure": "D3",
                "identifiers_masked": False,
                "scope_id": "scope-1",
                "purpose": "incident_investigation",
                "result_count": len(rows),
                "budget": limit,
                "truncated": False,
                "evidence_reference_count": 0,
                "evidence_disclosure_gated": True,
                "missing_inputs": [],
                "exposure_known": True,
                "computed_at": "2026-01-01T00:00:00+00:00",
            },
        }


class MaskingGateway(RecordingGateway):
    """The same gateway rendering at D2, where identifiers are redacted."""

    async def query(self, request: Any, **kwargs: Any) -> dict[str, Any]:
        result = await super().query(request, **kwargs)
        result["operatorDiagnostics"]["granted_disclosure"] = "D2"
        result["operatorDiagnostics"]["identifiers_masked"] = True
        return result


@pytest.fixture
def gateway():
    recorder = RecordingGateway(
        {
            "User": [
                {"vertex_id": "u1", "vertex_type": "User", "properties": {"email": "a@x.io"}},
                {"vertex_id": "u2", "vertex_type": "User", "properties": {"email": "b@x.io"}},
            ]
        }
    )
    set_gateway(recorder)
    try:
        yield recorder
    finally:
        reset_gateway()


@pytest.fixture
def service():
    return TenantMirrorService()


def _request() -> Any:
    return SimpleNamespace(state=SimpleNamespace(), path_params={"tenant_id": TENANT})


# ── Digest: identity, additivity, representation ─────────────────────────────


def test_identical_input_through_both_paths_digests_identically():
    """The same tenant-visible result, built twice, is one digest."""
    aether = {"vertices": [{"id": "u1", "score": 3}], "total": 1}
    mirror = {"vertices": [{"id": "u1", "score": 3}], "total": 1}

    assert (
        digest_tenant_visible(aether, contract_version=CONTRACT).digest
        == digest_tenant_visible(mirror, contract_version=CONTRACT).digest
    )
    assert compare(aether, mirror, contract_version=CONTRACT).matched is True


def test_attaching_operator_diagnostics_leaves_the_digest_byte_identical():
    """Diagnostics are additive: they sit beside tenantVisible, never inside it."""
    tenant_visible = {"vertices": [{"id": "u1"}], "total": 1}
    before = digest_tenant_visible(tenant_visible, contract_version=CONTRACT)

    envelope = {
        "tenantVisible": tenant_visible,
        "operatorDiagnostics": empty_diagnostics().model_dump(),
    }
    after = digest_tenant_visible(envelope["tenantVisible"], contract_version=CONTRACT)

    assert after.digest == before.digest
    assert after.canonical_bytes == before.canonical_bytes
    # And every declared augmentation section really is outside the digest.
    assert set(DIAGNOSTIC_SECTIONS) == set(envelope["operatorDiagnostics"])


def test_key_order_and_timestamp_spelling_do_not_change_the_digest():
    """Representation is not value. Two spellings of one moment are one moment."""
    aether = {
        "total": 2,
        "updated_at": "2026-03-04T05:06:07+00:00",
        "vertices": [{"id": "u1", "score": 1.0}],
    }
    mirror = {
        "vertices": [{"score": 1, "id": "u1"}],
        "updated_at": "2026-03-04T05:06:07Z",
        "total": 2,
    }

    assert canonical_payload(aether) == canonical_payload(mirror)
    assert (
        digest_tenant_visible(aether, contract_version=CONTRACT).digest
        == digest_tenant_visible(mirror, contract_version=CONTRACT).digest
    )


def test_a_real_value_change_does_change_the_digest():
    """The other half of the previous claim: value differences are not collapsed."""
    aether = {"vertices": [{"id": "u1", "score": 1}], "total": 2}
    mirror = {"vertices": [{"id": "u1", "score": 2}], "total": 2}

    assert (
        digest_tenant_visible(aether, contract_version=CONTRACT).digest
        != digest_tenant_visible(mirror, contract_version=CONTRACT).digest
    )


def test_a_different_contract_version_produces_a_different_digest():
    """A contract bump can never silently read as parity."""
    payload = {"vertices": [{"id": "u1"}], "total": 1}

    first = digest_tenant_visible(payload, contract_version="1.0.0")
    second = digest_tenant_visible(payload, contract_version="1.1.0")

    assert first.canonical_bytes == second.canonical_bytes  # same bytes …
    assert first.digest != second.digest  # … different meaning


def test_presentation_keys_are_stripped_but_values_are_not():
    """Only keys that differ while the result is the same may be stripped."""
    assert "request_id" in PRESENTATION_KEYS
    assert "timestamp" not in PRESENTATION_KEYS  # very often the tenant's own event time

    aether = {"request_id": "abc", "generated_at": "2026-01-01T00:00:00Z", "total": 5}
    mirror = {"request_id": "zzz", "generated_at": "2026-06-06T06:06:06Z", "total": 5}
    assert compare(aether, mirror, contract_version=CONTRACT).matched is True

    aether_ts = {"timestamp": "2026-01-01T00:00:00Z", "total": 5}
    mirror_ts = {"timestamp": "2026-01-02T00:00:00Z", "total": 5}
    assert compare(aether_ts, mirror_ts, contract_version=CONTRACT).matched is False


# ── Located divergence ───────────────────────────────────────────────────────


def test_a_single_divergent_value_reports_the_exact_json_path_and_both_values():
    """"The digests differ" is not actionable. The path and both values are."""
    aether = {
        "entities": {"User": [{"id": "u1", "properties": {"score": 41}}]},
        "total": 1,
    }
    mirror = {
        "entities": {"User": [{"id": "u1", "properties": {"score": 42}}]},
        "total": 1,
    }

    result = compare(aether, mirror, contract_version=CONTRACT)

    assert result.matched is False
    assert result.divergence_count == 1
    divergence = result.divergences[0]
    assert divergence.path == "$.entities.User[0].properties.score"
    assert divergence.aether == 41
    assert divergence.mirror == 42
    assert divergence.reason == "value_differs"


def test_missing_and_extra_fields_are_located_and_classified():
    aether = {"a": 1, "b": 2}
    mirror = {"a": 1, "c": 3}

    result = compare(aether, mirror, contract_version=CONTRACT)
    by_path = {d.path: d for d in result.divergences}

    assert by_path["$.b"].reason == "missing_in_mirror"
    assert by_path["$.b"].aether == 2
    assert by_path["$.c"].reason == "missing_in_aether"
    assert by_path["$.c"].mirror == 3


def test_a_list_length_difference_is_reported_as_such():
    result = compare({"rows": [1, 2, 3]}, {"rows": [1, 2]}, contract_version=CONTRACT)
    lengths = [d for d in result.divergences if d.reason == "length_differs"]
    assert lengths and lengths[0].path == "$.rows"
    assert lengths[0].aether == 3 and lengths[0].mirror == 2


def test_the_divergence_list_is_capped_and_says_when_it_truncated():
    """A capped list that did not admit it would understate the blast radius."""
    size = MAX_REPORTED_DIVERGENCES + 10
    aether = {"rows": [{"n": i} for i in range(size)]}
    mirror = {"rows": [{"n": i + 1} for i in range(size)]}

    result = compare(aether, mirror, contract_version=CONTRACT)

    assert result.matched is False
    assert len(result.divergences) == MAX_REPORTED_DIVERGENCES
    assert result.divergence_count == size
    assert result.truncated is True


# ── Manifest resolution and refusals ─────────────────────────────────────────


def test_an_unknown_surface_is_refused(service):
    with pytest.raises(NotFoundError):
        service.resolve("not-a-real-surface")


def test_a_parity_exempt_surface_is_refused_with_its_manifest_reason(service):
    """Opting out is allowed; opting out silently, or forgetting why, is not."""
    with pytest.raises(BadRequestError) as caught:
        service.resolve("billing")

    details = getattr(caught.value, "details", {}) or {}
    assert details.get("aether_route") == "/billing"
    reason = details.get("parity_exception_reason") or ""
    assert "revops" in reason  # the manifest's own words, repeated at the refusal


def test_every_parity_required_manifest_surface_has_a_resolver(service):
    """Coverage that silently stops covering a surface is worse than none."""
    required = set(service.parity_required_ids())
    assert required, "the manifest declares no parity-required surfaces"
    assert required == set(SURFACE_VERTEX_TYPES)
    assert all(SURFACE_VERTEX_TYPES[feature_id] for feature_id in required)


def test_a_surface_without_a_resolver_refuses_rather_than_rendering_empty(service):
    """A coverage hole must not look like a tenant with no data."""
    with pytest.raises(NotFoundError):
        service.vertex_types("campaign-intelligence-registry-typo")


def test_an_aether_route_resolves_to_the_same_entry_as_its_feature_id(service):
    assert service.resolve("/users") == service.resolve("users")


# ── Rendering: the gateway is the only way in ────────────────────────────────


async def test_render_returns_a_two_keyed_envelope_bound_to_the_contract(gateway, service):
    envelope = await service.render(_request(), tenant_id=TENANT, surface="users")

    assert envelope.surface_id == "users"
    assert envelope.tenant_id == TENANT
    assert envelope.contract_version == service.contract_version
    assert envelope.parity_comparable is True
    assert envelope.tenantVisible["entity_counts"] == {"User": 2}
    assert set(envelope.operatorDiagnostics.sections()) == set(DIAGNOSTIC_SECTIONS)
    assert envelope.operatorDiagnostics.health["state"] == "healthy"
    assert envelope.operatorDiagnostics.lineage["source"].endswith("scoped_gateway")


async def test_the_service_reads_a_tenant_only_through_the_gateway(gateway, service, monkeypatch):
    """Every other read path in the graph plane is tripwired; none may fire."""
    from services.kyber.graph import scoped_gateway as real_gateway

    def _tripwire(*args: Any, **kwargs: Any):
        raise AssertionError("the mirror reached a tenant outside the scoped gateway")

    monkeypatch.setattr(real_gateway, "get_store", _tripwire)
    monkeypatch.setattr(real_gateway, "get_tenant_graph", _tripwire)
    monkeypatch.setattr(real_gateway.ScopedTenantGraphGateway, "query", _tripwire)
    monkeypatch.setattr(real_gateway.ScopedTenantGraphGateway, "neighborhood", _tripwire)

    envelope = await service.render(_request(), tenant_id=TENANT, surface="graph")

    assert [call["vertex_type"] for call in gateway.calls] == list(
        SURFACE_VERTEX_TYPES["graph"]
    )
    assert {call["tenant_id"] for call in gateway.calls} == {TENANT}
    assert envelope.tenantVisible["vertex_types"] == list(SURFACE_VERTEX_TYPES["graph"])


async def test_check_parity_matches_when_aether_returns_the_mirrors_payload(gateway, service):
    envelope = await service.render(_request(), tenant_id=TENANT, surface="users")

    result = await service.check_parity(
        _request(),
        tenant_id=TENANT,
        surface="users",
        aether_payload=envelope.tenantVisible,
    )

    assert result.matched is True
    assert result.contract_version == service.contract_version


async def test_check_parity_locates_a_divergence_in_a_rendered_surface(gateway, service):
    envelope = await service.render(_request(), tenant_id=TENANT, surface="users")
    drifted = envelope.model_dump()["tenantVisible"]
    drifted["entities"]["User"][0]["properties"]["email"] = "attacker@x.io"

    result = await service.check_parity(
        _request(), tenant_id=TENANT, surface="users", aether_payload=drifted
    )

    assert result.matched is False
    paths = {d.path for d in result.divergences}
    assert "$.entities.User[0].properties.email" in paths


async def test_a_masked_rendering_is_not_offered_as_parity(service):
    """Redacted identifiers are supposed to differ; digesting them manufactures divergence."""
    set_gateway(MaskingGateway({"User": [{"vertex_id": "masked:abc", "properties": {}}]}))
    try:
        envelope = await service.render(_request(), tenant_id=TENANT, surface="users")
        assert envelope.parity_comparable is False
        assert envelope.disclosure == "D2"

        with pytest.raises(BadRequestError):
            await service.check_parity(
                _request(), tenant_id=TENANT, surface="users", aether_payload={}
            )
    finally:
        reset_gateway()


def test_get_gateway_resolves_the_real_scoped_gateway_when_nothing_is_injected():
    reset_gateway()
    from services.kyber.graph.scoped_gateway import scoped_tenant_graph_gateway

    assert get_gateway() is scoped_tenant_graph_gateway


# ── The CI gate itself ───────────────────────────────────────────────────────


def test_the_parity_gate_passes_on_this_tree():
    """The structural proof that the package owns no calculations."""
    spec = importlib.util.spec_from_file_location(
        "_tenant_mirror_gate", REPO_ROOT / "scripts" / "validate_tenant_mirror_parity.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.main() == 0, module.FAILURES
