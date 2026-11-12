"""DSR removes tenant-scoped social assertions in every subject role."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

from governance.consent.erasure_planes import (  # noqa: E402
    ErasureSubject,
    SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT,
    erase_social_relationship_evidence_plane,
)
from governance.dsr_propagation.models import DSR_COMPONENTS  # noqa: E402
from services.social360.evidence_authority import RepositorySocialEvidenceStore  # noqa: E402
from shared.storage.lifecycle import StorageLifecycle  # noqa: E402


def _row(tenant: str, record_id: str, **changes: object) -> dict[str, object]:
    return {
        "tenant_id": tenant,
        "record_id": record_id,
        "subject_entity_id": "other-target",
        "source_entity_id": "other-source",
        "target_entity_id": "other-target",
        "actor_id": "other-actor",
        "path_entity_ids": ["other-source", "other-middle", "other-target"],
        **changes,
    }


@pytest.mark.asyncio
async def test_social_evidence_erasure_reaches_endpoint_path_and_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repositories import repos

    monkeypatch.setattr(repos, "get_pool", AsyncMock(return_value=None))
    monkeypatch.setattr(StorageLifecycle, "active_hold", AsyncMock(return_value=None))
    monkeypatch.setattr(RepositorySocialEvidenceStore, "_local_rows", {})
    store = RepositorySocialEvidenceStore()
    tenant = "social-dsr-tenant-1"
    other_tenant = "social-dsr-tenant-2"
    for record in (
        _row(tenant, "subject", subject_entity_id="entity-delete"),
        _row(tenant, "source", source_entity_id="entity-delete"),
        _row(tenant, "target", target_entity_id="entity-delete"),
        _row(tenant, "middle", path_entity_ids=["other-source", "entity-delete", "other-target"]),
        _row(tenant, "actor", actor_id="user-delete"),
        _row(tenant, "keep"),
        _row(other_tenant, "foreign", source_entity_id="entity-delete"),
    ):
        await store.append(record)

    subject = ErasureSubject(
        tenant_id=tenant,
        user_id="user-delete",
        entity_ids=frozenset({"entity-delete"}),
    )
    assert SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT in DSR_COMPONENTS
    receipt = (await erase_social_relationship_evidence_plane(subject))[
        SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT
    ]
    assert receipt.status == "completed"
    assert receipt.records_impacted == 5
    assert (tenant, "keep") in store._local_rows
    assert (other_tenant, "foreign") in store._local_rows
    assert all((tenant, record_id) not in store._local_rows for record_id in (
        "subject", "source", "target", "middle", "actor"
    ))
    repeated = (await erase_social_relationship_evidence_plane(subject))[
        SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT
    ]
    assert repeated.records_impacted == 0


@pytest.mark.asyncio
async def test_social_evidence_erasure_respects_legal_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from repositories import repos

    monkeypatch.setattr(repos, "get_pool", AsyncMock(return_value=None))
    hold = {"hold_id": "hold-social-1", "reason": "active preservation order"}
    active_hold = AsyncMock(return_value=hold)
    monkeypatch.setattr(StorageLifecycle, "active_hold", active_hold)
    monkeypatch.setattr(RepositorySocialEvidenceStore, "_local_rows", {})
    store = RepositorySocialEvidenceStore()
    tenant = "social-dsr-hold-tenant"
    await store.append(_row(tenant, "held", source_entity_id="entity-held"))

    receipt = (await erase_social_relationship_evidence_plane(
        ErasureSubject(tenant_id=tenant, user_id="user-held", entity_ids=frozenset({"entity-held"}))
    ))[SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT]
    assert receipt.status == "skipped_legal_hold"
    assert receipt.policy_decision_id == "storage_legal_hold:hold-social-1"
    assert (tenant, "held") in store._local_rows
    assert active_hold.await_count >= 1

    active_hold.return_value = None
    released = (await erase_social_relationship_evidence_plane(
        ErasureSubject(tenant_id=tenant, user_id="user-held", entity_ids=frozenset({"entity-held"}))
    ))[SOCIAL_RELATIONSHIP_EVIDENCE_COMPONENT]
    assert released.status == "completed"
    assert released.records_impacted == 1
    assert (tenant, "held") not in store._local_rows
