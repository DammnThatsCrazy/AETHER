"""Regressions for the second-pass adversarial review of PR 2.

Each test here corresponds to a defect an adversarial reviewer found in code that was
already merged and already had a passing test suite. They are kept in one file, named for
the defect rather than the function, so a future reader can see what actually went wrong
rather than inferring it from a green run.

The common shape of all of them: **a surface that answered confidently from a partial or
incomparable input.** None was a crash; every one produced a plausible number or verdict
that a reader would have believed.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from shared.common.common import BadRequestError

from services.agent_access_intelligence.authority import (
    CapabilityAuthorityService,
    authorization_state,
)
from services.agent_access_intelligence.catalog_service import CapabilityCatalogService
from services.agent_access_intelligence.declarations import CapabilityDeclarationService
from services.agent_access_intelligence.identity import (
    IDENTITY_FIELDS,
    IdentityState,
    artifact_digest_for,
    asserted_identity_fields,
    identity_state_for,
)



@pytest.fixture(autouse=True)
def _stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


async def _observe(cat, **over):
    fact = {
        "tenant_id": "t1",
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "provider": "acme",
        "server_name": "stripe-mcp",
        "server_url": "https://mcp.stripe.com",
        "tool_name": "search",
        "protocol_version": "2025-06-18",
    }
    fact.update(over)
    return await cat.record_from_fact(fact)


# ══════════════════════════════════════════════════════════════════════════════
# 1. A correct declaration reported permanent HIGH drift
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_declaring_the_identity_you_know_does_not_report_drift():
    """The normal operator flow produced a permanent HIGH "no longer matches" finding.

    `capability_kind` is derived internally by this service and never named in the
    declaration API; `protocol_version` comes from telemetry. Digesting the full tuple on
    both sides meant an operator who declared exactly what the catalog showed them —
    provider, server, tool — compared unequal forever. Nothing had drifted.
    """
    cat, decl = CapabilityCatalogService(), CapabilityDeclarationService()
    observed = await _observe(cat)
    [cap] = await cat.list_capabilities("t1")

    await decl.declare(
        tenant_id="t1", declared_by_entity_id="u1",
        provider="acme", server_name="stripe-mcp", tool_name="search",
    )
    mapping, _ = await decl.digest_map("t1")
    entry = mapping[observed["capability_id"]]

    assert entry["fields"] == ["provider", "server", "tool_name"]
    state = identity_state_for(artifact_digest_for(cap, entry["fields"]), entry["digest"])
    assert state is IdentityState.DECLARED


@pytest.mark.asyncio
async def test_drift_still_fires_when_an_asserted_field_actually_changes():
    """The fix must not disarm the feature: a field the operator DID assert, changing,
    is exactly what drift is for."""
    decl = CapabilityDeclarationService()
    await decl.declare(
        tenant_id="t1", declared_by_entity_id="u1",
        provider="acme", server_name="srvZ", tool_name="t", protocol_version="1.0",
    )
    mapping, _ = await decl.digest_map("t1")
    entry = next(iter(mapping.values()))
    assert "protocol_version" in entry["fields"]

    moved = {"provider": "acme", "server_name": "srvZ", "tool_name": "t",
             "protocol_version": "2.0"}
    assert identity_state_for(
        artifact_digest_for(moved, entry["fields"]), entry["digest"]
    ) is IdentityState.DRIFTED


def test_digests_over_different_subsets_cannot_collide():
    """Subset digests are name-prefixed; without that, {provider: "x"} and
    {tool_name: "x"} would hash identically and one declaration would silently satisfy
    a different capability's comparison."""
    record = {"provider": "x", "tool_name": "x"}
    assert artifact_digest_for(record, ["provider"]) != artifact_digest_for(
        record, ["tool_name"]
    )


def test_absent_fields_are_not_assertions():
    assert asserted_identity_fields({"provider": "acme", "tool_name": "  "}) == ["provider"]
    assert asserted_identity_fields({}) == []
    # `server` is synthetic — it reads server_name/server_url, never a literal "server"
    # key — so a record has to supply the real field for it to count as asserted.
    full = {
        "provider": "p", "server_name": "s", "tool_name": "t",
        "protocol_version": "v", "capability_kind": "mcp_tool",
    }
    assert asserted_identity_fields(full) == list(IDENTITY_FIELDS)
    assert asserted_identity_fields({"server": "ignored"}) == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. Server-scoped grants were silently inert
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("granted_key", ["stripe-mcp", "https://mcp.stripe.com"])
@pytest.mark.asyncio
async def test_server_grant_authorizes_whichever_form_the_operator_names(granted_key):
    """`grant` hashed the raw operator input; `resolve` hashed the catalog's stored key.

    The API invites either the observed name or the URL. Granting by URL against a server
    the catalog knows by name returned 200 with a `server_ref` and then authorized
    nothing — every invocation denied, with no surface showing the grant was inert.
    """
    cat, auth = CapabilityCatalogService(), CapabilityAuthorityService()
    observed = await _observe(cat)

    await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        server_key=granted_key,
    )
    facts = await auth.resolve(
        tenant_id="t1", agent_id="agentA", capability_id=observed["capability_id"]
    )
    assert facts["authorized"] is True


@pytest.mark.asyncio
async def test_unobserved_server_grant_is_allowed_but_flagged_not_silently_inert():
    """Pre-authorizing a server nobody has observed is legitimate — but the operator must
    be able to see that it currently matches nothing."""
    auth = CapabilityAuthorityService()
    granted = await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        server_key="not-observed-yet",
    )
    assert granted["capability_observed"] is False


@pytest.mark.asyncio
async def test_grant_does_not_store_a_credential_bearing_server_key():
    """`catalog_service` and `declarations` both scrub credentials from a server URL
    before persisting. The grant path — the security-relevant one — did not, and the
    value is echoed on every list/read of the authorization."""
    auth = CapabilityAuthorityService()
    granted = await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        server_key="https://svc:S3cret@mcp.internal/v1",
    )
    blob = str(granted)
    assert "S3cret" not in blob
    assert "svc:" not in blob


# ══════════════════════════════════════════════════════════════════════════════
# 3. An unparseable expiry produced a permanent grant
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "bad",
    [
        "in 30 days", "next tuesday", "soon", "31/08/2026",
        # Timezone-naive values are rejected too: "2026-08-01" names a different moment
        # in every timezone, and `shared.temporal` documents assuming UTC as a policy
        # decision the caller must make explicitly rather than one this layer invents.
        "2026-08-01", "2026-08-01T00:00:00",
    ],
)
@pytest.mark.asyncio
async def test_unparseable_boundaries_are_rejected(bad):
    """`authorization_state` and `active_for` compare these as STRINGS.
    `"in 30 days" > "2026-07-24T..."` is always true, so a grant the operator believed
    expired in a month never expired — and the API echoed their intended date back."""
    auth = CapabilityAuthorityService()
    with pytest.raises(BadRequestError):
        await auth.grant(
            tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
            capability_id="cap_x", ends_at=bad,
        )


@pytest.mark.asyncio
async def test_offsets_are_normalized_so_string_order_matches_time_order():
    """`authorization_state` compares these lexicographically against
    `utc_now().isoformat()`, so a `+02:00` boundary has to be converted, not stored as
    written — otherwise ordering is by punctuation rather than by moment."""
    auth = CapabilityAuthorityService()
    granted = await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        capability_id="cap_x", ends_at="2020-01-01T02:00:00+02:00",
    )
    assert granted["ends_at"] == "2020-01-01T00:00:00+00:00"
    assert authorization_state(granted) == "expired"


@pytest.mark.asyncio
async def test_a_valid_future_expiry_is_accepted_and_active():
    auth = CapabilityAuthorityService()
    granted = await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        capability_id="cap_x", ends_at="2999-01-01T00:00:00Z",
    )
    assert authorization_state(granted) == "active"


@pytest.mark.asyncio
async def test_ends_at_before_starts_at_is_rejected():
    auth = CapabilityAuthorityService()
    with pytest.raises(BadRequestError):
        await auth.grant(
            tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
            capability_id="cap_x",
            starts_at="2026-08-01T00:00:00Z", ends_at="2026-07-01T00:00:00Z",
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. `?state=` filtered one page, so a real tenant looked empty
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_state_filter_finds_active_rows_behind_a_page_of_revoked_ones():
    """`state` is derived, so it cannot be a query filter — but filtering a single
    `limit`-sized page made a tenant with many revoked and a few active authorizations
    return `{"items": [], "count": 0}`, indistinguishable from "nothing is authorized".
    """
    auth = CapabilityAuthorityService()
    for i in range(25):
        granted = await auth.grant(
            tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
            capability_id=f"cap_dead{i}",
        )
        await auth.revoke(
            tenant_id="t1", authorization_id=granted["authorization_id"],
            revoked_by_entity_id="u1",
        )
    live = await auth.grant(
        tenant_id="t1", granted_by_entity_id="u1", agent_id="agentA",
        capability_id="cap_live",
    )

    active = await auth.list(tenant_id="t1", state="active", limit=10)
    assert [r["authorization_id"] for r in active] == [live["authorization_id"]]

    histogram = await auth.count_by_state(tenant_id="t1")
    assert histogram["counts"]["active"] == 1
    assert histogram["counts"]["revoked"] == 25
    assert histogram["truncated"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 5. Truncated reads answered as if complete
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_digest_map_reports_truncation():
    """A declaration outside the read window makes its capability look `observed_only`,
    which is deliberately NOT a finding — so real drift vanished into a clean report."""
    decl = CapabilityDeclarationService()
    for i in range(6):
        await decl.declare(
            tenant_id="t1", declared_by_entity_id="u1",
            provider="acme", server_name=f"srv{i}", tool_name="t",
        )
    _, truncated = await decl.digest_map("t1", limit=3)
    assert truncated is True

    full, not_truncated = await decl.digest_map("t1", limit=100)
    assert not_truncated is False
    assert len(full) == 6


# ══════════════════════════════════════════════════════════════════════════════
# 6. Scanning false positives and false negatives
# ══════════════════════════════════════════════════════════════════════════════


def _scan_codes(**over):
    from services.agent_access_intelligence.scanning import scan_capability

    record = {"capability_id": "cap_x", "tool_name": "search"}
    record.update(over)
    return [f.code.value for f in scan_capability(record)]


@pytest.mark.parametrize("tool_name", ["act_as_user", "actAsUser", "new_instructions_v2"])
def test_ordinary_delegation_tool_names_are_not_injection_shaped(tool_name):
    """`INJECTION_PATTERNS` contains the ordinary English phrases "act as" and
    "new instructions". On an agent platform `act_as_*` is a routine delegation tool;
    reporting it as injection-shaped trains operators to ignore the finding — the exact
    false-positive class the single-word rule already guards against."""
    assert "injection_shaped_tool_name" not in _scan_codes(tool_name=tool_name)


@pytest.mark.parametrize(
    "tool_name",
    ["ignore_previous_instructions", "tool.developer.mode", "dump_system_prompt", "jailbreak"],
)
def test_genuinely_injection_shaped_names_still_fire(tool_name):
    """The exclusion must not disarm detection for phrases that name nothing legitimate."""
    assert "injection_shaped_tool_name" in _scan_codes(tool_name=tool_name)


@pytest.mark.parametrize(
    "host",
    ["2130706433", "0177.0.0.1", "0x7f000001"],
)
def test_obfuscated_ip_literals_are_still_private_network_origins(host):
    """`ipaddress.ip_address` accepts only dotted-quad and IPv6 text, so the integer forms
    of 127.0.0.1 slipped past the private-network check entirely — which is precisely how
    such a URL would be written by someone trying to slip past it."""
    codes = _scan_codes(server_url=f"https://{host}/rpc")
    assert "private_network_origin" in codes


def test_public_ip_literals_are_not_flagged():
    assert "private_network_origin" not in _scan_codes(server_url="https://8.8.8.8/rpc")
    assert "private_network_origin" not in _scan_codes(
        server_url="https://[2001:4860:4860::8888]/rpc"
    )


def test_scanning_is_still_pure_and_deterministic():
    """No DNS, and an unresolvable name yields no origin finding — reusing
    `_is_unsafe_destination` here would have made output depend on our DNS view."""
    first = _scan_codes(server_url="https://nonexistent.invalid/rpc")
    second = _scan_codes(server_url="https://nonexistent.invalid/rpc")
    assert first == second
    assert "private_network_origin" not in first
    assert "blocked_host_origin" not in first
