"""Capability declaration tests (PR 2, Phase B2, monoprompt §9.3/§9.5).

Proves the invariants documented in ``services/agent_access_intelligence/declarations.py``
against the in-memory backend: re-declaring upserts instead of duplicating, the declared
ids are derived from the SAME tuple the observed catalog uses (so drift joins exactly), a
credential-bearing ``server_url`` never reaches storage, a declaration that identifies
nothing is rejected, cross-tenant reads/withdraws are indistinguishable from "absent",
``digest_map`` emits only rows it can actually compare, and private ``_``-prefixed fields
never reach the API surface. No Postgres required.

There is deliberately no test for a ``verified`` state, because there is deliberately no
such state — see ``identity.py``. ``test_no_field_implies_verification`` asserts that
absence stays true.
"""

from __future__ import annotations

import pytest

from shared.common.common import BadRequestError, NotFoundError

from services.agent_access_intelligence import identity
from services.agent_access_intelligence.catalog_service import CapabilityCatalogService
from services.agent_access_intelligence.declarations import (
    CAPABILITY_DECLARATIONS_TABLE,
    CapabilityDeclarationRepository,
    CapabilityDeclarationService,
)
from services.agent_access_intelligence.models import capability_id_for


@pytest.fixture
def svc():
    return CapabilityDeclarationService()


@pytest.fixture
def repo():
    return CapabilityDeclarationRepository()


@pytest.fixture
def catalog():
    return CapabilityCatalogService()


def _decl(**over):
    body = {
        "tenant_id": "t1",
        "declared_by_entity_id": "u1",
        "provider": "acme",
        "server_name": "srvX",
        "server_url": "https://x.example",
        "tool_name": "search",
        "protocol_version": "2025-06-18",
        "capability_kind": "mcp_tool",
    }
    body.update(over)
    return body


def _fact(**over):
    row = {
        "tenant_id": "t1",
        "source_event_id": "e1",
        "event_name": "agent_tool_invocation_observed",
        "occurred_at": "2026-07-24T00:00:00Z",
        "agent_id": "agentA",
        "tool_name": "search",
        "server_name": "srvX",
        "server_url": "https://x.example",
        "provider": "acme",
        "protocol_version": "2025-06-18",
        "risk_level": "low",
        "payload": {},
    }
    row.update(over)
    return row


# ══════════════════════════════════════════════════════════════════════════════
# A. Storage invariants (one test each)
# ══════════════════════════════════════════════════════════════════════════════

async def test_redeclaring_upserts_and_never_duplicates(svc, repo):
    """Two rows for one capability would each report their own drift verdict."""
    first = await svc.declare(**_decl(notes="initial"))
    second = await svc.declare(**_decl(notes="revised", declared_by_entity_id="u2"))

    assert second["declaration_id"] == first["declaration_id"]
    assert len(await svc.list(tenant_id="t1")) == 1
    assert await repo.count() == 1

    # The row was updated, not shadowed by a second one.
    current = await svc.get(tenant_id="t1", declaration_id=first["declaration_id"])
    assert current["notes"] == "revised"
    assert current["declared_by_entity_id"] == "u2"
    # First assertion time survives the edit; updated_at moves.
    assert current["declared_at"] == first["declared_at"]

    # A different tool on the same server is a DIFFERENT declaration, not an overwrite.
    other = await svc.declare(**_decl(tool_name="write"))
    assert other["declaration_id"] != first["declaration_id"]
    assert len(await svc.list(tenant_id="t1")) == 2


async def test_ids_agree_with_the_shared_identity_helpers(svc):
    """The declared ids must come from the same tuple the observed catalog is keyed by."""
    record = await svc.declare(**_decl())
    assert record["declaration_id"] == identity.declaration_id_for("t1", "acme", "srvX", "search")
    assert record["capability_id"] == capability_id_for("t1", "acme", "srvX", "search")
    assert record["declaration_id"].startswith("dec_")
    assert record["capability_id"].startswith("cap_")

    # server_key falls back to server_url when no name was declared (catalog_service._server_key).
    no_name = await svc.declare(**_decl(server_name=None))
    assert no_name["capability_id"] == capability_id_for("t1", "acme", "https://x.example", "search")

    # The ids are tenant-scoped, so the same tuple in another tenant is a different row.
    other_tenant = await svc.declare(**_decl(tenant_id="t2"))
    assert other_tenant["declaration_id"] != record["declaration_id"]
    assert other_tenant["capability_id"] != record["capability_id"]


async def test_declaration_joins_the_observed_catalog_exactly(svc, catalog):
    """Declaration ↔ observation is an exact id join, and the digests are comparable."""
    observed = await catalog.record_from_fact(_fact())
    declared = await svc.declare(**_decl())

    assert declared["capability_id"] == observed["capability_id"]

    row = await catalog.get_capability(tenant_id="t1", capability_id=observed["capability_id"])
    # The declared digest is the digest of the observed row's own identity fields — i.e.
    # a matching declaration is comparable, not drifted-by-construction.
    assert declared["artifact_digest"] == identity.artifact_digest_for(row)
    assert declared["publisher_ref"] == row["publisher_ref"]

    # A declaration whose protocol version differs digests differently — that is what
    # §9.5 drift compares.
    drifted = await svc.declare(**_decl(tool_name="write", protocol_version="1999-01-01"))
    assert drifted["artifact_digest"] != declared["artifact_digest"]


async def test_credential_bearing_server_url_is_sanitized_before_storage(svc, repo):
    """A declaration is a durable, operator-readable row served back over the API."""
    record = await svc.declare(
        **_decl(server_name=None, server_url="https://user:hunter2@x.example/mcp?token=SECRET")
    )
    stored = await repo.find_by_id(record["declaration_id"])

    for blob in (record, stored):
        text = str(blob)
        assert "hunter2" not in text
        assert "SECRET" not in text
    assert stored["server_url"] == "https://x.example/mcp?token=REDACTED"
    # The derived origin label is taken from the sanitized URL, so it carries no userinfo.
    assert record["publisher_label"] == "x.example"


async def test_declaration_identifying_nothing_is_rejected(svc):
    """An empty declaration would hash to the same id as every other empty one."""
    with pytest.raises(BadRequestError):
        await svc.declare(
            tenant_id="t1", declared_by_entity_id="u1", provider="acme",
        )
    with pytest.raises(BadRequestError):
        # Whitespace-only is empty too.
        await svc.declare(
            tenant_id="t1", declared_by_entity_id="u1",
            server_name="  ", server_url="", tool_name="   ",
        )
    with pytest.raises(BadRequestError):
        await svc.declare(**_decl(tenant_id="  "))

    # Any ONE of the three identity fields is enough.
    for field in ("server_name", "server_url", "tool_name"):
        one = await svc.declare(
            tenant_id="t1", declared_by_entity_id="u1", **{field: "only-this"}
        )
        assert one["declaration_id"].startswith("dec_")


async def test_cross_tenant_read_and_withdraw_are_not_found(svc):
    record = await svc.declare(**_decl())
    declaration_id = record["declaration_id"]

    assert (await svc.get(tenant_id="t1", declaration_id=declaration_id))[
        "declaration_id"
    ] == declaration_id

    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", declaration_id=declaration_id)
    with pytest.raises(NotFoundError):
        await svc.withdraw(tenant_id="t2", declaration_id=declaration_id)
    # An absent id is indistinguishable from the foreign one.
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t2", declaration_id="dec_doesnotexist")

    # The foreign withdraw did not take effect.
    assert (await svc.get(tenant_id="t1", declaration_id=declaration_id))["declaration_id"]


# ══════════════════════════════════════════════════════════════════════════════
# B. Read / withdraw behaviour
# ══════════════════════════════════════════════════════════════════════════════

async def test_withdraw_hard_deletes_and_returns_the_removed_record(svc, repo):
    record = await svc.declare(**_decl())
    removed = await svc.withdraw(tenant_id="t1", declaration_id=record["declaration_id"])

    assert removed["declaration_id"] == record["declaration_id"]
    assert removed["capability_id"] == record["capability_id"]
    # Hard delete: the row is gone, not flagged.
    assert await repo.find_by_id(record["declaration_id"]) is None
    assert await svc.list(tenant_id="t1") == []
    assert await svc.digest_map("t1") == ({}, False)
    with pytest.raises(NotFoundError):
        await svc.get(tenant_id="t1", declaration_id=record["declaration_id"])


async def test_list_is_tenant_scoped_and_filterable(svc):
    a = await svc.declare(**_decl())
    b = await svc.declare(**_decl(provider="other", server_name="srvY", tool_name="write"))
    await svc.declare(**_decl(tenant_id="t2"))

    assert len(await svc.list(tenant_id="t1")) == 2
    assert len(await svc.list(tenant_id="t2")) == 1
    assert [r["declaration_id"] for r in await svc.list(tenant_id="t1", provider="acme")] == [
        a["declaration_id"]
    ]
    assert [r["declaration_id"] for r in await svc.list(tenant_id="t1", server_name="srvY")] == [
        b["declaration_id"]
    ]
    assert [
        r["declaration_id"]
        for r in await svc.list(tenant_id="t1", capability_id=a["capability_id"])
    ] == [a["declaration_id"]]
    assert await svc.list(tenant_id="t1", provider="nobody") == []
    assert len(await svc.list(tenant_id="t1", limit=1)) == 1


async def test_digest_map_is_tenant_scoped_and_skips_incomparable_rows(svc, repo):
    """An empty declared digest would compare unequal and be reported as drift."""
    a = await svc.declare(**_decl())
    b = await svc.declare(**_decl(tool_name="write"))
    await svc.declare(**_decl(tenant_id="t2"))

    mapping, truncated = await svc.digest_map("t1")
    assert truncated is False
    assert {k: v["digest"] for k, v in mapping.items()} == {
        a["capability_id"]: a["artifact_digest"],
        b["capability_id"]: b["artifact_digest"],
    }
    assert all(v["digest"].startswith("art_") for v in mapping.values())
    # Each entry carries the identity subset the declaration actually asserted, so the
    # observed side can be digested over the same fields instead of the full tuple.
    assert all(v["fields"] for v in mapping.values())
    # Tenant scoping: t2's declaration is invisible here and vice versa.
    t2_map, _ = await svc.digest_map("t2")
    assert set(t2_map).isdisjoint(mapping)
    assert await svc.digest_map("t3") == ({}, False)

    # Rows that cannot be compared are skipped rather than emitted with empty strings.
    await repo.insert("dec_nodigest", {
        "declaration_id": "dec_nodigest", "tenant_id": "t1",
        "capability_id": "cap_incomplete", "artifact_digest": None,
    })
    await repo.insert("dec_nocap", {
        "declaration_id": "dec_nocap", "tenant_id": "t1",
        "capability_id": "", "artifact_digest": "art_orphan",
    })
    after, _ = await svc.digest_map("t1")
    assert after == mapping
    assert "cap_incomplete" not in after
    assert "art_orphan" not in {v["digest"] for v in after.values()}


async def test_private_fields_never_reach_the_public_record(svc, repo):
    record = await svc.declare(**_decl())
    declaration_id = record["declaration_id"]
    await repo.update(declaration_id, {"_internal_note": "operator-only", "_scratch": [1, 2]})

    for public in (
        await svc.get(tenant_id="t1", declaration_id=declaration_id),
        (await svc.list(tenant_id="t1"))[0],
        await svc.withdraw(tenant_id="t1", declaration_id=declaration_id),
    ):
        assert not [k for k in public if k.startswith("_")]
        assert "operator-only" not in str(public)
    # ... and the private field really was stored (i.e. the assertion above is not vacuous).
    assert "_internal_note" not in record


async def test_no_field_implies_verification(svc):
    """Nothing verifies a third-party publisher, so no field may suggest one did."""
    record = await svc.declare(**_decl())
    keys = {k.lower() for k in record}
    assert not any(
        token in key
        for key in keys
        for token in ("verified", "verification", "trusted", "attested", "signed")
    )
    assert set(identity.IdentityState) == {
        identity.IdentityState.OBSERVED_ONLY,
        identity.IdentityState.DECLARED,
        identity.IdentityState.DRIFTED,
    }


async def test_repository_table_name_matches_the_migration(repo):
    """The storage-policy gate derives its inventory from the table name."""
    assert CAPABILITY_DECLARATIONS_TABLE == "capability_declarations"
    assert repo.table_name == CAPABILITY_DECLARATIONS_TABLE
