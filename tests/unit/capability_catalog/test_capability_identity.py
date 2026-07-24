"""Artifact / publisher identity tests (PR 2, Phase B2).

Pins the honesty properties of ``services/agent_access_intelligence/identity.py``: there is
no ``verified`` state and none can be added by accident; a publisher ref groups by claimed
origin without asserting the origin is genuine; an artifact digest is stable against fields
that are not identity, so re-observation does not manufacture drift; and an unresolvable
comparison resolves toward ``drifted``, never toward the reassuring answer. No Postgres.
"""

from __future__ import annotations

import pytest

from services.agent_access_intelligence.catalog_service import CapabilityCatalogService
from services.agent_access_intelligence.identity import (
    IdentityState,
    artifact_digest_for,
    declaration_id_for,
    identity_state_for,
    publisher_label_for,
    publisher_ref_for,
)
from services.agent_access_intelligence.models import capability_id_for


def _fact(**over):
    row = {
        "tenant_id": "t1",
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "acme-mcp",
        "server_url": "https://mcp.acme.example/rpc",
        "provider": "acme",
        "protocol_version": "2026-03-01",
    }
    row.update(over)
    return row


# ── No verified state ──────────────────────────────────────────────────────────


def test_there_is_no_verified_identity_state():
    """Nothing in this backend can verify a third-party publisher. A `verified` member
    would be read by operators as "someone checked," and no one did."""
    values = {s.value for s in IdentityState}
    assert values == {"observed_only", "declared", "drifted"}
    assert not any("verif" in v for v in values)


# ── publisher ref / label ──────────────────────────────────────────────────────


def test_publisher_is_the_url_host():
    assert publisher_label_for("https://mcp.acme.example/rpc", "acme") == "mcp.acme.example"
    assert publisher_ref_for("https://mcp.acme.example/rpc", "acme").startswith("pub_")


def test_publisher_label_is_host_only_so_a_url_path_or_userinfo_cannot_leak():
    """The label is rendered to operators. Taking only the host means neither a path,
    a query, nor a stray `user:pass@` authority can ride along into the UI."""
    label = publisher_label_for("https://alice:s3cr3t@mcp.acme.example/rpc?token=abc", "acme")
    assert label == "mcp.acme.example"
    assert "s3cr3t" not in label and "alice" not in label and "abc" not in label


def test_opaque_server_name_is_its_own_origin():
    assert publisher_label_for("acme-mcp", None) == "acme-mcp"


def test_provider_is_the_fallback_origin():
    assert publisher_label_for(None, "Acme") == "acme"
    assert publisher_ref_for(None, "Acme") == publisher_ref_for(None, "acme")


def test_no_origin_yields_none_rather_than_a_placeholder():
    """A placeholder ref would silently merge every origin-less capability into one
    fake publisher."""
    assert publisher_label_for(None, None) is None
    assert publisher_ref_for(None, None) is None
    assert publisher_ref_for("", "  ") is None


def test_distinct_origins_get_distinct_refs():
    assert publisher_ref_for("https://a.example/x", None) != publisher_ref_for(
        "https://b.example/x", None
    )


# ── artifact digest ────────────────────────────────────────────────────────────


def test_digest_ignores_fields_that_are_not_identity():
    """observation_count/last_seen_at change on every single observation. If they fed the
    digest, the entire inventory would report as drifted continuously."""
    base = {"provider": "acme", "server_name": "acme-mcp", "tool_name": "search"}
    noisy = dict(base, observation_count=99, last_seen_at="2027-01-01T00:00:00Z", extra="x")
    assert artifact_digest_for(base) == artifact_digest_for(noisy)


def test_digest_changes_when_identity_changes():
    base = {"provider": "acme", "server_name": "acme-mcp", "tool_name": "search"}
    assert artifact_digest_for(base) != artifact_digest_for(
        dict(base, protocol_version="2026-03-01")
    )
    assert artifact_digest_for(base) != artifact_digest_for(dict(base, tool_name="delete"))


def test_digest_is_case_and_whitespace_normalized():
    assert artifact_digest_for({"provider": " ACME ", "tool_name": "Search"}) == (
        artifact_digest_for({"provider": "acme", "tool_name": "search"})
    )


def test_enum_members_digest_as_their_plain_value():
    """`str(CapabilityKind.MCP_TOOL)` is "CapabilityKind.MCP_TOOL", but the stored row and
    every declaration hold "mcp_tool". If the enum were stringified naively, the digest
    written at upsert would disagree with one recomputed from the row's own stored fields,
    and no declaration could ever match — Phase C would report the whole declared inventory
    as drifted."""
    from services.agent_access_intelligence.models import CapabilityKind

    assert artifact_digest_for({"capability_kind": CapabilityKind.MCP_TOOL}) == (
        artifact_digest_for({"capability_kind": "mcp_tool"})
    )


def test_digest_falls_back_to_server_url_when_there_is_no_server_name():
    with_name = artifact_digest_for({"server_name": "acme-mcp"})
    with_url = artifact_digest_for({"server_url": "acme-mcp"})
    assert with_name == with_url


# ── declaration id joins the observation exactly ───────────────────────────────


def test_declaration_and_capability_ids_key_on_the_same_tuple():
    """Same tuple in, one-to-one join out — no fuzzy matching between the declared and
    observed sides, and re-declaring updates one row instead of creating rivals."""
    args = ("t1", "acme", "acme-mcp", "search")
    assert declaration_id_for(*args) == declaration_id_for(*args)
    assert declaration_id_for(*args)[4:] == capability_id_for(*args)[4:]
    assert declaration_id_for(*args).startswith("dec_")
    assert capability_id_for(*args).startswith("cap_")


def test_declaration_ids_are_tenant_isolated():
    assert declaration_id_for("t1", "acme", "s", "x") != declaration_id_for("t2", "acme", "s", "x")


# ── state derivation ───────────────────────────────────────────────────────────


def test_state_derivation():
    assert identity_state_for("art_a", None) is IdentityState.OBSERVED_ONLY
    assert identity_state_for("art_a", "art_a") is IdentityState.DECLARED
    assert identity_state_for("art_a", "art_b") is IdentityState.DRIFTED


def test_uncomparable_declaration_is_drifted_not_declared():
    """"Declared but we cannot compare it" is unresolved. Resolving it toward the
    reassuring answer is the exact failure mode this module exists to avoid."""
    assert identity_state_for(None, "art_b") is IdentityState.DRIFTED


# ── observed side is actually wired ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_catalog_upsert_populates_identity_fields():
    svc = CapabilityCatalogService()
    await svc.record_from_fact(_fact())
    [cap] = await svc.list_capabilities("t1")
    assert cap["publisher_label"] == "mcp.acme.example"
    assert cap["publisher_ref"].startswith("pub_")
    assert cap["artifact_digest"].startswith("art_")


@pytest.mark.asyncio
async def test_reobservation_omitting_a_field_does_not_manufacture_drift():
    """A later fact that simply doesn't carry protocol_version must not change the digest —
    otherwise every partial observation would be reported as a drifted artifact."""
    svc = CapabilityCatalogService()
    await svc.record_from_fact(_fact())
    [first] = await svc.list_capabilities("t1")

    await svc.record_from_fact(_fact(source_event_id="e2", protocol_version=None))
    [second] = await svc.list_capabilities("t1")

    assert second["observation_count"] == 2
    assert second["artifact_digest"] == first["artifact_digest"]


@pytest.mark.asyncio
async def test_a_genuine_identity_change_does_change_the_digest():
    svc = CapabilityCatalogService()
    await svc.record_from_fact(_fact(tool_name="search"))
    await svc.record_from_fact(_fact(source_event_id="e2", tool_name="delete"))
    digests = {c["artifact_digest"] for c in await svc.list_capabilities("t1")}
    assert len(digests) == 2
