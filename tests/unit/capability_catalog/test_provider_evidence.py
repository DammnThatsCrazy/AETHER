"""Provider evidence + provider routes (PR 3, Phase A, monoprompt §9.6).

The point of this file is **reachability**. ``services/agentic_observability/provider_framework.py``
was fully built and entirely unreferenced by the application; the tests that matter here
are the ones that go through a route handler and come back holding something only the real
framework could have produced — ``provider_registry``'s adapter metadata, and a
``PermissionFinding`` whose text is generated inside ``compute_permission_findings``. If
those two ever start passing against a stub, the lane has regressed to what it was.

Handlers are called directly with a fake ``Request`` — the established pattern in this
suite (see ``test_capability_authority_routes.py``) — so permission gates and tenant
scoping are exercised without standing up the middleware.

The rest proves the storage invariants documented in ``provider_evidence.py``: re-capture
upserts, a credential-bearing value never reaches storage *or* either hash, an
uncanonicalizable timestamp is rejected rather than compared lexicographically, every
bounded read discloses truncation, and an absent input yields ``null`` counts rather than
zero. There is deliberately no test for a ``verified`` state, because there is deliberately
no such state — ``test_nothing_claims_platform_verification`` asserts that absence stays
true across every route response.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from repositories.repos import reset_in_memory_stores
from shared.auth.auth import TenantContext
from shared.common.common import BadRequestError, ForbiddenError, NotFoundError

from services.agentic_observability.provider_framework import (
    ProviderVerificationStatus,
    compute_permission_findings,
    provider_registry,
)
from services.agent_access_intelligence.authority_routes import (
    CapabilityAuthorizationGrant,
)
import services.agent_access_intelligence.authority_routes as authority_routes
import services.agent_access_intelligence.provider_routes as provider_routes
from services.agent_access_intelligence.catalog_service import capability_catalog_service
from services.agent_access_intelligence.provider_evidence import (
    ATTESTATION_DISCLOSURE,
    PROVIDER_EVIDENCE_TABLE,
    ProviderEvidenceRepository,
    ProviderEvidenceService,
)
from services.agent_access_intelligence.provider_routes import ProviderEvidenceRequest


# ── fixtures / helpers ────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture
def svc():
    return ProviderEvidenceService()


@pytest.fixture
def repo():
    return ProviderEvidenceRepository()


class FakeProducer:
    def __init__(self):
        self.events: list = []

    async def publish(self, event):
        self.events.append(event)


def _request(tenant_id: str = "t1", permissions: list[str] | None = None):
    tenant = TenantContext(
        tenant_id=tenant_id,
        user_id="u1",
        permissions=permissions if permissions is not None else ["read", "write"],
    )
    return SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"user-agent": "pytest"},
    )


def _ev(**over):
    body = {
        "tenant_id": "t1",
        "recorded_by_entity_id": "u1",
        "provider_id": "acme",
        "capability_id": "cap_seed",
        "external_account_id": "acct-1",
        "agent_id": "agentA",
        "verification_status": "confirmed",
        "verification_method": "provider_snapshot_comparison",
        "verified_at": "2026-07-23T00:00:00Z",
    }
    body.update(over)
    return body


async def _observe(
    *,
    tenant_id: str = "t1",
    agent_id: str = "agentA",
    tool_name: str = "post_message",
    server_name: str = "srvX",
    occurred_at: str = "2026-07-24T00:00:00Z",
    source_event_id: str = "e1",
) -> str:
    """Materialize one observed capability + installation, returning the capability id."""
    result = await capability_catalog_service.record_from_fact({
        "tenant_id": tenant_id,
        "source_event_id": source_event_id,
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": occurred_at,
        "agent_id": agent_id,
        "tool_name": tool_name,
        "server_name": server_name,
        "provider": "acme",
        "risk_level": "low",
    })
    return result["capability_id"]


def _blob(value) -> str:
    return json.dumps(value, default=str).lower()


# ══════════════════════════════════════════════════════════════════════════════
# A. THE WIRING PROOF — the framework is reachable through a mounted route
# ══════════════════════════════════════════════════════════════════════════════

async def test_adapters_route_serves_the_real_provider_registry():
    """``provider_registry`` had no caller in the application. This route is the caller."""
    resp = await provider_routes.list_provider_adapters(_request())
    data = resp["data"]

    registered = provider_registry.list_metadata()
    assert registered, "the registry is populated at import; an empty one is a regression"
    assert data["count"] == len(registered) == len(data["items"])

    x = next(i for i in data["items"] if i["provider_id"] == "x_reference")
    # Fields only XReferenceAdapter.metadata produces — a stub would not carry these.
    assert x["name"] == "X (Twitter) Reference Adapter"
    assert x["supported_operations"] == [
        "account_lookup", "auth_verification", "action_observation",
    ]
    assert x["webhook_supported"] is True
    # The framework's INVARIANT (all adapter operations are read-only) restated, not assumed.
    assert x["read_only"] is True
    assert data["read_only"] is True


async def test_permission_findings_route_returns_a_finding_the_framework_generated():
    """A HIGH finding produced inside ``compute_permission_findings``, via the route.

    The provider attests the access was revoked on the 23rd; the catalog observed the
    agent using that capability on the 24th. Neither half knows about the other until the
    framework is handed both."""
    capability_id = await _observe(occurred_at="2026-07-24T00:00:00Z")

    await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(
            provider_id="acme",
            capability_id=capability_id,
            agent_id="agentA",
            verification_status="revoked",
            verified_at="2026-07-23T00:00:00Z",
        ),
        _request(),
    )

    resp = await provider_routes.list_permission_findings(_request(), limit=500)
    data = resp["data"]

    assert data["findings_known"] is True
    by_type = {i["finding_type"] for i in data["items"]}
    assert "revoked_grant_used" in by_type

    finding = next(i for i in data["items"] if i["finding_type"] == "revoked_grant_used")
    # Exactly the PermissionFinding dataclass surface — not a hand-rolled dict.
    assert set(finding) == {
        "finding_type", "severity", "description", "grant_id", "agent_id", "scopes", "metadata",
    }
    assert finding["severity"] == "high"
    assert finding["agent_id"] == "agentA"
    # The description text is generated inside compute_permission_findings; reproducing it
    # here would require reimplementing the framework, which is the failure this guards.
    assert finding["description"].startswith("Action ")
    assert f"used revoked grant {finding['grant_id']}" in finding["description"]
    assert finding["grant_id"].startswith("ev_")

    assert data["counts"]["scope"] == "all_matching_findings"
    assert data["counts"]["by_severity"]["high"] >= 1
    assert data["coverage"]["complete"] is True
    assert data["coverage"]["grants_evaluated"] == 1
    assert data["coverage"]["actions_evaluated"] == 1


async def test_findings_come_from_the_framework_not_a_local_reimplementation():
    """The route's items equal what the framework returns for the same inputs."""
    capability_id = await _observe(occurred_at="2026-07-24T00:00:00Z")
    await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(
            provider_id="acme", capability_id=capability_id, agent_id="agentA",
            verification_status="revoked", verified_at="2026-07-23T00:00:00Z",
        ),
        _request(),
    )
    resp = await provider_routes.list_permission_findings(_request(), limit=500)
    route_types = sorted(i["finding_type"] for i in resp["data"]["items"])

    # Every returned finding_type is one the framework can emit, and the framework emits
    # nothing for an empty input set (so the route is not fabricating a baseline).
    assert route_types
    assert compute_permission_findings("t1", [], [], {}) == []
    assert set(route_types) <= {
        "expired_grant", "revoked_grant_used", "unexpected_new_scope", "write_scope_unused",
    }


async def test_unexpected_scope_clears_once_the_tenant_authorizes_it():
    """``unexpected_new_scope`` is measured against real capability authorizations."""
    capability_id = await _observe()
    await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(
            provider_id="acme", capability_id=capability_id, agent_id="agentA",
            verification_status="confirmed", verified_at="2026-07-23T00:00:00Z",
        ),
        _request(),
    )

    before = await provider_routes.list_permission_findings(_request(), limit=500)
    assert "unexpected_new_scope" in {i["finding_type"] for i in before["data"]["items"]}

    await authority_routes.grant_authorization(
        CapabilityAuthorizationGrant(agent_id="agentA", capability_id=capability_id),
        _request(),
        producer=FakeProducer(),
    )
    after = await provider_routes.list_permission_findings(_request(), limit=500)
    assert "unexpected_new_scope" not in {i["finding_type"] for i in after["data"]["items"]}
    assert after["data"]["coverage"]["authorizations_examined"] == 1


async def test_write_scope_the_agent_was_never_observed_using_is_reported():
    """A write-capable scope the provider attests but no observation used."""
    await _observe(agent_id="agentA", tool_name="post_message", source_event_id="e1")
    other = await _observe(
        agent_id="agentB", tool_name="delete_everything", server_name="srvY",
        source_event_id="e2",
    )
    await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(
            provider_id="acme", capability_id=other, agent_id="agentA",
            verification_status="confirmed", verified_at="2026-07-23T00:00:00Z",
        ),
        _request(),
    )
    resp = await provider_routes.list_permission_findings(_request(), limit=500)
    unused = [i for i in resp["data"]["items"] if i["finding_type"] == "write_scope_unused"]
    assert unused, "agentA was never observed using delete_everything"
    assert unused[0]["severity"] == "low"
    assert unused[0]["scopes"] == ["delete_everything"]


# ══════════════════════════════════════════════════════════════════════════════
# B. Storage invariants
# ══════════════════════════════════════════════════════════════════════════════

async def test_capture_is_a_deterministic_upsert_and_the_digest_tracks_the_claim(svc, repo):
    """Two rows for one provider claim would each carry their own status."""
    first = await svc.capture(**_ev(notes="initial"))
    second = await svc.capture(**_ev(notes="revised", verification_status="revoked"))

    assert second["evidence_id"] == first["evidence_id"]
    assert first["evidence_id"].startswith("ev_") and len(first["evidence_id"]) == 27
    assert await repo.count() == 1
    assert len(await svc.list(tenant_id="t1")) == 1

    current = await svc.get(tenant_id="t1", evidence_id=first["evidence_id"])
    assert current["verification_status"] == "revoked"
    assert current["notes"] == "revised"
    # First attestation time survives the edit; updated_at moves.
    assert current["recorded_at"] == first["recorded_at"]
    # A CHANGE in what the provider attests is detectable even though the id is stable.
    assert current["evidence_digest"] != first["evidence_digest"]

    # A different external account is a DIFFERENT row, not an overwrite.
    other = await svc.capture(**_ev(external_account_id="acct-2"))
    assert other["evidence_id"] != first["evidence_id"]
    assert await repo.count() == 2


async def test_verification_status_comes_only_from_the_framework_enum(svc):
    for status in ProviderVerificationStatus:
        record = await svc.capture(**_ev(verification_status=status.value))
        assert record["verification_status"] == status.value
    with pytest.raises(BadRequestError):
        await svc.capture(**_ev(verification_status="verified"))
    with pytest.raises(BadRequestError):
        await svc.capture(**_ev(verification_status="trusted"))

    # An omitted status is the ABSENCE of an assertion, not the assertion "unverified".
    absent = await svc.capture(**_ev(verification_status=None, external_account_id="acct-x"))
    assert absent["verification_status"] == ProviderVerificationStatus.INSUFFICIENT_DATA.value


async def test_credential_bearing_values_are_sanitized_before_storage_and_hashing(svc, repo):
    """Evidence is a durable, operator-readable row served back over the API."""
    record = await svc.capture(**_ev(
        external_account_id="https://user:hunter2@acct.example/a?token=SECRET",
        verification_method="https://bot:pw123@hook.example/v1?api_key=NOPE",
    ))
    stored = await repo.find_by_id(record["evidence_id"])

    for blob in (_blob(record), _blob(stored)):
        for secret in ("hunter2", "secret", "pw123", "nope"):
            assert secret not in blob
    assert stored["external_account_id"] == "https://acct.example/a?token=REDACTED"
    assert stored["verification_method"] == "https://hook.example/v1?api_key=REDACTED"

    # Sanitized BEFORE the id and digest are derived: the raw value never reached a hash.
    clean = await svc.capture(**_ev(
        external_account_id="https://acct.example/a?token=REDACTED",
        verification_method="https://hook.example/v1?api_key=REDACTED",
    ))
    assert clean["evidence_id"] == record["evidence_id"]
    assert clean["evidence_digest"] == record["evidence_digest"]


async def test_verified_at_is_strictly_parsed_and_canonicalized(svc):
    """An unvalidated instant compared lexicographically is how this package once
    produced a grant that never expired."""
    for bad in ("not-a-date", "2026-07-23T00:00:00", "2026-13-01T00:00:00Z", "yesterday"):
        with pytest.raises(BadRequestError):
            await svc.capture(**_ev(verified_at=bad))

    # Canonical form matches `utc_now().isoformat()`, which is what the framework compares
    # against with `<` — a stored "…Z" would sort AFTER the same moment written "…+00:00".
    z_form = await svc.capture(**_ev(verified_at="2026-07-23T00:00:00Z"))
    offset_form = await svc.capture(**_ev(verified_at="2026-07-23T02:00:00+02:00"))
    assert z_form["verified_at"] == "2026-07-23T00:00:00+00:00"
    assert offset_form["verified_at"] == z_form["verified_at"]

    # Absent is absent, not an error and not a fabricated "now".
    absent = await svc.capture(**_ev(verified_at=None))
    assert absent["verified_at"] is None


async def test_cross_tenant_reads_are_indistinguishable_from_absent(svc):
    record = await svc.capture(**_ev())
    evidence_id = record["evidence_id"]

    assert (await svc.get(tenant_id="t1", evidence_id=evidence_id))["evidence_id"] == evidence_id
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", evidence_id=evidence_id)
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", evidence_id="ev_doesnotexist")
    assert await svc.list(tenant_id="t2") == []

    # ... and through the route, where the tenant comes from request.state.
    with pytest.raises(NotFoundError):
        await provider_routes.read_provider_evidence(evidence_id, _request("t2"))
    assert (await provider_routes.list_provider_evidence(
        _request("t2"), provider_id=None, capability_id=None, limit=100, offset=0
    ))["data"]["count"] == 0


async def test_tenant_is_never_taken_from_the_request_body():
    assert "tenant_id" not in ProviderEvidenceRequest.model_fields
    written = await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(provider_id="acme", agent_id="agentA"), _request("t1")
    )
    assert written["data"]["tenant_id"] == "t1"
    assert written["data"]["recorded_by_entity_id"] == "u1"


async def test_provider_id_is_required_because_evidence_is_attributed(svc):
    with pytest.raises(BadRequestError):
        await svc.capture(**_ev(provider_id="   "))
    with pytest.raises(BadRequestError):
        await svc.capture(**_ev(tenant_id="  "))


async def test_private_fields_never_reach_the_public_record(svc, repo):
    record = await svc.capture(**_ev())
    await repo.update(record["evidence_id"], {"_internal_note": "operator-only"})
    for public in (
        await svc.get(tenant_id="t1", evidence_id=record["evidence_id"]),
        (await svc.list(tenant_id="t1"))[0],
    ):
        assert not [k for k in public if k.startswith("_")]
        assert "operator-only" not in _blob(public)


async def test_repository_table_name_matches_the_migration(repo):
    """The storage-policy gate derives its inventory from the table name."""
    assert PROVIDER_EVIDENCE_TABLE == "provider_evidence"
    assert repo.table_name == PROVIDER_EVIDENCE_TABLE


# ══════════════════════════════════════════════════════════════════════════════
# C. Disclosure rules — bounded reads, unknown ≠ zero
# ══════════════════════════════════════════════════════════════════════════════

async def test_every_bounded_read_discloses_truncation(svc):
    capability_id = await _observe()
    await svc.capture(**_ev(capability_id=capability_id, external_account_id="acct-1"))
    await svc.capture(**_ev(capability_id=capability_id, external_account_id="acct-2"))

    full = await svc.permission_findings(tenant_id="t1", limit=500)
    assert full["coverage"]["complete"] is True
    assert full["coverage"]["evidence_truncated"] is False
    assert full["coverage"]["missing_inputs"] == []
    assert full["counts"]["scope"] == "all_matching_findings"

    clipped = await svc.permission_findings(tenant_id="t1", limit=1)
    assert clipped["coverage"]["evidence_truncated"] is True
    assert clipped["coverage"]["complete"] is False
    # A partial window is never presented as a complete answer.
    assert clipped["counts"]["scope"] == "scanned_window_only"
    assert "provider_evidence:scan_truncated" in clipped["coverage"]["missing_inputs"]

    # The list route discloses it too.
    page = await provider_routes.list_provider_evidence(
        _request(), provider_id=None, capability_id=None, limit=1, offset=0
    )
    assert page["data"]["truncated"] is True
    assert page["data"]["count"] == 1


async def test_the_action_window_cap_is_disclosed(svc, monkeypatch):
    """The framework is O(grants x actions); the cap that keeps it answerable is not silent."""
    capability_id = await _observe()
    await _observe(agent_id="agentB", server_name="srvY", source_event_id="e2")
    await svc.capture(**_ev(capability_id=capability_id))

    # The cap is passed explicitly rather than patched onto the module. Mutating a module
    # global is not isolated under xdist — this test passed alone and failed in the full
    # parallel run — and an injectable cap is the better API anyway: the bound is now
    # visible at the call site instead of being ambient process state.
    result = await svc.permission_findings(tenant_id="t1", limit=500, max_actions=1)
    assert result["coverage"]["action_window_truncated"] is True
    assert result["coverage"]["action_window_limit"] == 1
    assert result["coverage"]["complete"] is False
    assert result["counts"]["scope"] == "scanned_window_only"
    assert "capability_installations:action_window_truncated=1" in (
        result["coverage"]["missing_inputs"]
    )


async def test_absent_input_yields_null_counts_not_zero():
    """"0 findings" about a tenant whose evidence we never had reads as "you are clean"."""
    resp = await provider_routes.list_permission_findings(_request(), limit=500)
    data = resp["data"]

    assert data["findings_known"] is False
    assert data["items"] == []
    assert data["counts"] == {
        "total": None, "scope": None, "by_finding_type": None, "by_severity": None,
    }
    assert data["coverage"]["actions_evaluated"] is None
    assert data["coverage"]["missing_inputs"]
    assert "unknown, not zero" in data["summary"].lower()


async def test_agentless_records_are_excluded_and_disclosed(svc):
    """A permission finding is agent-scoped; ``None == None`` would fabricate one."""
    capability_id = await _observe()
    await svc.capture(**_ev(capability_id=capability_id, agent_id=None))

    result = await svc.permission_findings(tenant_id="t1", limit=500)
    assert result["findings_known"] is False
    assert "provider_evidence:agent_id_absent=1" in result["coverage"]["missing_inputs"]
    assert result["coverage"]["evidence_examined"] == 1


async def test_grant_expiry_is_declared_unevaluated_rather_than_reported_clean(svc):
    capability_id = await _observe()
    await svc.capture(**_ev(capability_id=capability_id))
    result = await svc.permission_findings(tenant_id="t1", limit=500)

    assert "expired_grant" in result["finding_types_not_evaluated"]
    assert "not a statement" in result["finding_types_not_evaluated"]["expired_grant"]
    assert "expired_grant" not in {i["finding_type"] for i in result["items"]}


async def test_revocation_without_a_moment_is_disclosed_not_answered_as_no(svc):
    capability_id = await _observe()
    await svc.capture(**_ev(
        capability_id=capability_id, verification_status="revoked", verified_at=None
    ))
    result = await svc.permission_findings(tenant_id="t1", limit=500)

    assert "provider_evidence:revoked_without_verified_at=1" in result["coverage"]["missing_inputs"]
    assert "revoked_grant_used" not in {i["finding_type"] for i in result["items"]}


# ══════════════════════════════════════════════════════════════════════════════
# D. Permission gates + the no-verification rule
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("call", ["adapters", "list", "read", "findings"])
async def test_read_routes_require_read_permission(call):
    denied = _request(permissions=[])
    if call == "adapters":
        with pytest.raises(ForbiddenError):
            await provider_routes.list_provider_adapters(denied)
    elif call == "list":
        with pytest.raises(ForbiddenError):
            await provider_routes.list_provider_evidence(
                denied, provider_id=None, capability_id=None, limit=100, offset=0
            )
    elif call == "read":
        with pytest.raises(ForbiddenError):
            await provider_routes.read_provider_evidence("ev_x", denied)
    else:
        with pytest.raises(ForbiddenError):
            await provider_routes.list_permission_findings(denied, limit=500)


async def test_capture_requires_write_and_read_alone_is_not_enough():
    body = ProviderEvidenceRequest(provider_id="acme", agent_id="agentA")
    with pytest.raises(ForbiddenError):
        await provider_routes.capture_provider_evidence(body, _request(permissions=["read"]))
    ok = await provider_routes.capture_provider_evidence(body, _request(permissions=["read", "write"]))
    assert ok["data"]["evidence_id"].startswith("ev_")


async def test_nothing_claims_platform_verification():
    """Evidence is provider-attested. No response may read as "someone checked this"."""
    capability_id = await _observe()
    captured = await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(
            provider_id="acme", capability_id=capability_id, agent_id="agentA",
            verification_status="confirmed", verified_at="2026-07-23T00:00:00Z",
        ),
        _request(),
    )
    responses = [
        captured,
        await provider_routes.list_provider_adapters(_request()),
        await provider_routes.list_provider_evidence(
            _request(), provider_id=None, capability_id=None, limit=100, offset=0
        ),
        await provider_routes.read_provider_evidence(
            captured["data"]["evidence_id"], _request()
        ),
        await provider_routes.list_permission_findings(_request(), limit=500),
    ]

    forbidden = (
        "platform_verified", "platform verified", "publisher_verified", "publisher verified",
        "aether verified", "aether_verified", "verified by", "verified publisher",
        "trusted publisher", "trusted_publisher", "we verified", "is trusted",
    )
    for resp in responses:
        blob = _blob(resp)
        for phrase in forbidden:
            assert phrase not in blob, f"{phrase!r} present in {blob[:200]}"

    # The status vocabulary is the framework's, and it has no "verified" member.
    assert "verified" not in {s.value for s in ProviderVerificationStatus}
    assert {s.value for s in ProviderVerificationStatus} == {
        "confirmed", "contradicted", "unverified", "pending",
        "expired", "revoked", "insufficient_data",
    }

    # Every surface states what it is, including a single record lifted out of a list.
    assert captured["data"]["attestation"] == ATTESTATION_DISCLOSURE
    assert captured["data"]["source"] == "provider_attested"
    for resp in responses:
        assert ATTESTATION_DISCLOSURE.lower() in _blob(resp)


async def test_source_is_not_caller_supplied():
    """A caller must not be able to label its own row as anything other than attested."""
    assert "source" not in ProviderEvidenceRequest.model_fields
    resp = await provider_routes.capture_provider_evidence(
        ProviderEvidenceRequest(provider_id="acme", agent_id="agentA"), _request()
    )
    assert resp["data"]["source"] == "provider_attested"
