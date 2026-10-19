"""Focused tests for the Account360 product-frame provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from identity.account360_provider import (  # noqa: E402
    Account360Provider,
    AccountIdentityRead,
    RepositoryAccount360Source,
)
from shared.intelligence_projections.composition import (  # noqa: E402
    PRODUCT_360_SURFACE_DEFINITIONS,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.errors import ProjectionError  # noqa: E402
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


TENANT_ID = "tenant-account360-test"
SUBJECT = ProjectionSubject(kind="entity", id="organization-1")
EVIDENCE = EvidenceRef(
    id="account360-evidence-1",
    type="entity",
    source="account360/test-fixture",
    observedAt="2026-10-17T10:00:00Z",
)
IDENTITY_EVIDENCE = EvidenceRef(
    id=SUBJECT.id,
    type="entity",
    source="entity_registry",
    observedAt="2026-10-17T09:59:00Z",
)


class _Source:
    def __init__(self, response: AccountIdentityRead) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def canonical_entity(
        self, tenant_id: str, entity_id: str
    ) -> AccountIdentityRead:
        self.calls.append((tenant_id, entity_id))
        return self.response


def _request(
    *, as_of: str | None = None, include_evidence: bool = True
) -> Experience360FrameRequest:
    return Experience360FrameRequest(
        surfaceId="account360",
        tenantId=TENANT_ID,
        subject=SUBJECT,
        asOf=as_of,
        includeEvidence=include_evidence,
    )


def _section(section_id: str, *, state: str = "available") -> ProjectionSection:
    return ProjectionSection(
        id=section_id,
        state=state,
        content=(
            {
                "observed": True,
                "evidenceRefs": [EVIDENCE.model_dump(mode="json", by_alias=True)],
            }
            if state == "available"
            else None
        ),
        warnings=["outcome_projection_unavailable"] if state == "degraded" else None,
    )


def _projection(
    projection_id: str,
    section_ids: list[str],
    *,
    tenant_id: str = TENANT_ID,
) -> ProjectionResult:
    return ProjectionResult(
        projectionId=projection_id,
        tenantId=tenant_id,
        contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
        sections=[
            _section(section_id, state="degraded" if section_id == "outcomes" else "available")
            for section_id in section_ids
        ],
        claims=[],
        dependencyState=[],
        generatedAt="2026-10-17T10:01:00Z",
        asOf="2026-10-17T10:00:00Z",
        degradedReasons=[],
    )


def _results(*, tenant_id: str = TENANT_ID) -> list[ProjectionResult]:
    return [
        _projection(
            "profile360",
            ["summary", "state", "evidence", "findings"],
            tenant_id=tenant_id,
        ),
        _projection(
            "relationship360",
            ["summary", "interactions", "evidence"],
            tenant_id=tenant_id,
        ),
        _projection(
            "economic360",
            ["summary", "evidence", "outcomes"],
            tenant_id=tenant_id,
        ),
    ]


def _allowed_slots() -> dict[str, Experience360PolicyDisposition]:
    slots = PRODUCT_360_SURFACE_DEFINITIONS["account360"]["domainSlots"]
    return {
        slot["id"]: Experience360PolicyDisposition(state="allowed")
        for slot in slots
    }


@pytest.mark.asyncio
async def test_account360_composes_only_canonical_tenant_scoped_projection_results():
    source = _Source(AccountIdentityRead("resolved", evidence_refs=(IDENTITY_EVIDENCE,)))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
        generated_at="2026-10-17T10:02:00Z",
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert frame.surfaceId == "account360"
    assert frame.tenantId == TENANT_ID
    assert frame.subject == SUBJECT
    assert frame.ownsCanonicalTruth is False
    slots = {slot.id: slot for slot in frame.slots}
    assert slots["account_identity_and_state"].state == "available"
    assert EVIDENCE in slots["account_identity_and_state"].evidenceRefs
    assert IDENTITY_EVIDENCE in slots["account_identity_and_state"].evidenceRefs
    assert any(
        provenance.sourceKind == "authority"
        and provenance.canonicalAuthorityRefs == ["entity_registry"]
        and IDENTITY_EVIDENCE in provenance.evidenceRefs
        for provenance in slots["account_identity_and_state"].provenance
    )
    assert slots["account_relationships"].state == "available"
    assert EVIDENCE in slots["account_relationships"].evidenceRefs
    assert IDENTITY_EVIDENCE not in slots["account_relationships"].evidenceRefs
    assert slots["economic_context"].state == "degraded"
    assert slots["economic_context"].content is not None
    assert slots["evidence_and_limitations"].state == "available"
    assert all(slot.provenance for slot in frame.slots if slot.content is not None)
    assert all(slot.evidenceRefs for slot in frame.slots if slot.content is not None)
    assert frame.freshness.state == "unknown"
    assert "surface_contract_pending_source_alignment" in frame.warnings


@pytest.mark.asyncio
async def test_missing_policy_defaults_to_unknown_and_does_not_read_or_expose_results():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot={
            "account_identity_and_state": Experience360PolicyDisposition(
                state="allowed"
            )
        },
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    slots = {slot.id: slot for slot in frame.slots}
    assert slots["account_identity_and_state"].state == "available"
    for slot_id in ("account_relationships", "economic_context", "evidence_and_limitations"):
        assert slots[slot_id].state == "suppressed"
        assert slots[slot_id].content is None
        assert "policy_not_evaluated" in slots[slot_id].reasonCodes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_evidence", "identity_policy"),
    [(True, "denied"), (False, "allowed")],
)
async def test_account_identity_evidence_respects_slot_policy_and_evidence_request(
    include_evidence: bool, identity_policy: str
):
    source = _Source(AccountIdentityRead("resolved", evidence_refs=(IDENTITY_EVIDENCE,)))
    policy = _allowed_slots()
    policy["account_identity_and_state"] = Experience360PolicyDisposition(state=identity_policy)

    frame = await Account360Provider(source).compose(
        _request(include_evidence=include_evidence),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=policy,
    )

    identity_slot = next(slot for slot in frame.slots if slot.id == "account_identity_and_state")
    assert IDENTITY_EVIDENCE not in identity_slot.evidenceRefs


@pytest.mark.asyncio
async def test_frame_policy_unknown_skips_entity_read_and_suppresses_all_content():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(
            state="unknown", reasonCodes=["policy_not_evaluated"]
        ),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == []
    assert all(slot.state == "suppressed" for slot in frame.slots)
    assert all(slot.content is None for slot in frame.slots)


@pytest.mark.asyncio
async def test_unresolved_canonical_subject_discards_projection_results():
    source = _Source(AccountIdentityRead("unknown", "account_entity_scope_mismatch"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == [(TENANT_ID, SUBJECT.id)]
    assert "account_entity_scope_mismatch" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)
    assert all(slot.state in {"missing", "unknown"} for slot in frame.slots)


@pytest.mark.asyncio
async def test_current_entity_identity_is_not_reused_for_historical_account_frame():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    frame = await provider.compose(
        _request(as_of="2026-10-01T00:00:00Z"),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert source.calls == []
    assert "account_entity_temporal_identity_unavailable" in frame.warnings
    assert all(slot.content is None for slot in frame.slots)


@pytest.mark.asyncio
async def test_projection_from_another_tenant_is_rejected_after_subject_validation():
    source = _Source(AccountIdentityRead("resolved"))
    provider = Account360Provider(source)

    with pytest.raises(ProjectionError, match="projection result tenant"):
        await provider.compose(
            _request(),
            _results(tenant_id="tenant-foreign"),
            frame_policy=Experience360PolicyDisposition(state="allowed"),
            policy_by_slot=_allowed_slots(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("entity_type", ["account", "organization"])
async def test_repository_source_resolves_canonical_organization_account_and_discards_raw_fields(
    monkeypatch: pytest.MonkeyPatch, entity_type: str
):
    from repositories.repos import EntityRepository

    calls: list[tuple[dict[str, str], int]] = []

    async def find_many(self, *, filters, limit=50, **_kwargs):
        calls.append((filters, limit))
        return [
            {
                "tenant_id": TENANT_ID,
                "entity_id": SUBJECT.id,
                "entity_type": entity_type,
                "updated_at": "2026-10-17T09:59:00Z",
                "email": "private@example.test",
                "metadata": {"secret": "must-not-project"},
            }
        ]

    monkeypatch.setattr(EntityRepository, "find_many", find_many)
    identity = await RepositoryAccount360Source().canonical_entity(TENANT_ID, SUBJECT.id)

    assert calls == [({"tenant_id": TENANT_ID, "entity_id": SUBJECT.id}, 2)]
    assert identity.state == "resolved"
    assert identity.reason_code is None
    assert identity.evidence_refs == (IDENTITY_EVIDENCE,)
    assert "private@example.test" not in str(identity)
    assert "must-not-project" not in str(identity)


@pytest.mark.asyncio
async def test_same_tenant_non_account_entity_cannot_expose_account_projection_data(
    monkeypatch: pytest.MonkeyPatch,
):
    from repositories.repos import EntityRepository

    calls: list[tuple[dict[str, str], int]] = []

    async def find_many(self, *, filters, limit=50, **_kwargs):
        calls.append((filters, limit))
        return [
            {
                "tenant_id": TENANT_ID,
                "entity_id": SUBJECT.id,
                "entity_type": "agent",
                "display_name": "Private agent profile",
            }
        ]

    monkeypatch.setattr(EntityRepository, "find_many", find_many)
    provider = Account360Provider(RepositoryAccount360Source())
    frame = await provider.compose(
        _request(),
        _results(),
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        policy_by_slot=_allowed_slots(),
    )

    assert calls == [({"tenant_id": TENANT_ID, "entity_id": SUBJECT.id}, 2)]
    assert "account_entity_type_mismatch" in frame.warnings
    assert all(slot.state in {"missing", "unknown"} for slot in frame.slots)
    assert all(slot.content is None for slot in frame.slots)
    assert all(slot.evidenceRefs == [] for slot in frame.slots)
    assert "Private agent profile" not in str(frame.model_dump(mode="json"))
