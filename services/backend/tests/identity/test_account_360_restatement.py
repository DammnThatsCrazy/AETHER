"""Account 360 identity restatement uses canonical account authorities."""

from __future__ import annotations

import os
import sys

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import BaseRepository, reset_in_memory_stores  # noqa: E402
from repositories.repos import AdminRepository  # noqa: E402
from repositories.jobs_repo import reset_jobs_memory  # noqa: E402
from services.account_organization.repository import (  # noqa: E402
    MEMBERS_TABLE,
    ORGANIZATIONS_TABLE,
    OrganizationRepository,
)
from services.projections.projection_restatement_orchestrator import (  # noqa: E402
    Account360ProjectionComposer,
    PROJECTION_RESTATEMENT_JOB_TYPE,
    ProjectionRestatementOrchestrator,
    register_projection_restatement_handler,
)
from services.identity.models import (  # noqa: E402
    ConfidenceBand,
    DecisionType,
    EntityType,
    IdentitySignalType,
    IdentityDecisionRecord,
    ProjectionType,
)
from services.identity.hashing import hash_value  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.jobs.handlers import unregister_handler  # noqa: E402
from services.jobs.service import get_jobs_service  # noqa: E402
from services.jobs.worker import JobWorker  # noqa: E402


class _Lifecycle:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.calls: list[str] = []

    async def get_projection_state(self, tenant_id: str) -> dict:
        self.calls.append(tenant_id)
        if tenant_id != self.tenant_id:
            raise AssertionError("foreign tenant lifecycle read")
        return {
            "tenant_id": tenant_id,
            "tenant_status": "active",
            "deletion_status": "none",
            "recovery_until": None,
            "lifecycle_updated_at": "2026-09-27T00:00:00+00:00",
        }


@pytest.fixture(autouse=True)
def _reset_repositories():
    reset_in_memory_stores()
    reset_jobs_memory()
    import services.jobs.service as jobs_service_module

    jobs_service_module._service = None
    unregister_handler(PROJECTION_RESTATEMENT_JOB_TYPE)
    yield
    unregister_handler(PROJECTION_RESTATEMENT_JOB_TYPE)
    jobs_service_module._service = None


def _repository() -> OrganizationRepository:
    return OrganizationRepository(
        organizations=BaseRepository(ORGANIZATIONS_TABLE),
        members=BaseRepository(MEMBERS_TABLE),
    )


async def _seed_org(repository: OrganizationRepository, tenant_id: str) -> None:
    await repository.organizations.insert(
        f"org-{tenant_id}",
        {
            "organization_id": f"org-{tenant_id}",
            "tenant_id": tenant_id,
            "name": f"Organization {tenant_id}",
            "owner_user_id": "person-owner",
            "status": "active",
        },
    )
    await repository.members.insert(
        f"member-{tenant_id}",
        {
            "member_id": f"member-{tenant_id}",
            "tenant_id": tenant_id,
            "user_id": "person-member",
            "role": "member",
            "status": "active",
        },
    )
    identities = IdentityResolutionRepository()
    for principal_id in ("person-owner", "person-member", "person-new"):
        canonical_entity_id = f"canonical-{principal_id}"
        await identities.create_subject(
            tenant_id, canonical_entity_id, entity_type=EntityType.HUMAN
        )
        await identities.upsert_alias(
            tenant_id,
            canonical_entity_id,
            IdentitySignalType.USER_ID,
            alias_value_hash=hash_value(principal_id, scope=f"user:{tenant_id}"),
        )


@pytest.mark.asyncio
async def test_account_360_recomposes_current_owner_and_relationship_changes_idempotently():
    tenant_id = "tenant-account-360"
    repository = _repository()
    lifecycle = _Lifecycle(tenant_id)
    await _seed_org(repository, tenant_id)
    composer = Account360ProjectionComposer(repository, lifecycle)

    first_view, first_evidence = await composer.compose(
        tenant_id, ["canonical-person-owner", "canonical-person-member"]
    )
    replay_view, replay_evidence = await composer.compose(
        tenant_id, ["canonical-person-owner", "canonical-person-member"]
    )
    assert replay_view == first_view
    assert replay_evidence == first_evidence
    assert first_evidence["status"] == "recomposed"
    assert first_evidence["mode"] == "canonical_read"
    assert first_evidence["person_relationship_count"] == 2

    await repository.update_profile(tenant_id, {"owner_user_id": "person-member"})
    await repository.add_member(
        tenant_id,
        user_id="person-new",
        role="admin",
    )
    changed_view, changed_evidence = await composer.compose(
        tenant_id, ["canonical-person-member", "canonical-person-new"]
    )

    assert changed_view["owner_canonical_entity_id"] == "canonical-person-member"
    assert [person["canonical_entity_id"] for person in changed_view["people"]] == [
        "canonical-person-member", "canonical-person-new"
    ]
    assert all("user_id" not in person for person in changed_view["people"])
    assert changed_view != first_view
    assert changed_evidence["person_relationship_count"] == 2
    assert changed_evidence["affected_people_matched"] == 2
    assert lifecycle.calls == [tenant_id, tenant_id, tenant_id]


@pytest.mark.asyncio
async def test_account_360_fails_closed_without_canonical_person_relationships():
    tenant_id = "tenant-no-account-people"
    repository = _repository()
    await repository.organizations.insert(
        "org-empty",
        {
            "organization_id": "org-empty",
            "tenant_id": tenant_id,
            "name": "No people",
            "owner_user_id": None,
            "status": "active",
        },
    )
    composer = Account360ProjectionComposer(repository, _Lifecycle(tenant_id))

    with pytest.raises(RuntimeError, match="no canonical account/person relationships"):
        await composer.compose(tenant_id, ["unrelated-profile"])


@pytest.mark.asyncio
async def test_account_360_fails_closed_when_affected_people_are_not_linked():
    tenant_id = "tenant-unrelated-account-people"
    repository = _repository()
    await _seed_org(repository, tenant_id)
    composer = Account360ProjectionComposer(repository, _Lifecycle(tenant_id))

    with pytest.raises(RuntimeError, match="no affected canonical people linked"):
        await composer.compose(tenant_id, ["profile-without-account-link"])


@pytest.mark.asyncio
async def test_account_360_rejects_ambiguous_auth_principal_aliases():
    tenant_id = "tenant-account-ambiguous"
    repository = _repository()
    await _seed_org(repository, tenant_id)
    identities = IdentityResolutionRepository()
    duplicate_id = "canonical-duplicate-owner"
    await identities.create_subject(tenant_id, duplicate_id, entity_type=EntityType.HUMAN)
    await identities.upsert_alias(
        tenant_id,
        duplicate_id,
        IdentitySignalType.USER_ID,
        alias_value_hash=hash_value("person-owner", scope=f"user:{tenant_id}"),
    )
    with pytest.raises(RuntimeError, match="multiple canonical people"):
        await Account360ProjectionComposer(repository, _Lifecycle(tenant_id)).compose(
            tenant_id, ["canonical-person-owner"]
        )


@pytest.mark.asyncio
async def test_account_360_is_tenant_scoped_and_rejects_foreign_source_rows():
    tenant_a = "tenant-account-a"
    tenant_b = "tenant-account-b"
    repository = _repository()
    await _seed_org(repository, tenant_a)
    await _seed_org(repository, tenant_b)
    lifecycle = _Lifecycle(tenant_a)
    composer = Account360ProjectionComposer(repository, lifecycle)

    view, evidence = await composer.compose(tenant_a, ["canonical-person-owner"])

    assert view["tenant_id"] == tenant_a
    assert view["organization_id"] == f"org-{tenant_a}"
    assert evidence["person_relationship_count"] == 2
    assert lifecycle.calls == [tenant_a]
    assert "tenant-account-b" not in str(view)
    assert all("user_id" not in person for person in view["people"])

    class _ForeignOrganizationRepository:
        async def get_profile(self, tenant_id: str) -> dict:
            return {
                "organization_id": "foreign-org",
                "tenant_id": tenant_b,
                "owner_user_id": "person-owner",
                "status": "active",
            }

    with pytest.raises(RuntimeError, match="foreign tenant"):
        await Account360ProjectionComposer(
            _ForeignOrganizationRepository(), lifecycle
        ).compose(tenant_a, ["canonical-person-owner"])


@pytest.mark.asyncio
async def test_lifecycle_projection_state_uses_tenant_scoped_workflow_without_actor_evidence(monkeypatch):
    from services.account_lifecycle.service import AccountLifecycleService

    tenant_id = "tenant-lifecycle-view"

    class _WorkflowRepository:
        async def find_by_tenant(self, requested_tenant: str) -> list[dict]:
            assert requested_tenant == tenant_id
            return [{
                "tenant_id": tenant_id,
                "status": "recovery",
                "requested_at": "2026-09-26T00:00:00+00:00",
                "recovery_until": "2026-10-26T00:00:00+00:00",
                "actor_id": "private-actor",
                "reauth_evidence": {"evidence_id": "private-evidence"},
            }]

    async def find_tenant(self, requested_tenant: str) -> dict:
        assert requested_tenant == tenant_id
        return {"id": tenant_id, "status": "suspended"}

    monkeypatch.setattr(
        "services.account_lifecycle.service.AdminRepository.find_by_id",
        find_tenant,
    )
    state = await AccountLifecycleService(workflow_repo=_WorkflowRepository()).get_projection_state(tenant_id)

    assert state == {
        "tenant_id": tenant_id,
        "tenant_status": "suspended",
        "deletion_status": "recovery",
        "recovery_until": "2026-10-26T00:00:00+00:00",
        "lifecycle_updated_at": "2026-09-26T00:00:00+00:00",
    }
    assert "actor_id" not in state
    assert "reauth_evidence" not in state


@pytest.mark.asyncio
async def test_worker_records_completed_account_360_with_canonical_source_evidence(monkeypatch):
    tenant_id = "tenant-account-worker"
    await AdminRepository().insert(tenant_id, {"tenant_id": tenant_id, "status": "active"})
    repository = _repository()
    await _seed_org(repository, tenant_id)
    decision = IdentityDecisionRecord(
        id="account-360-restatement-decision",
        tenant_id=tenant_id,
        decision_type=DecisionType.AUTO_MERGE,
        candidate_source_identity_ids=[],
        candidate_canonical_entity_ids=["canonical-person-member"],
        selected_canonical_entity_id="canonical-person-owner",
        confidence=0.99,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[],
        negative_evidence=[],
        vetoes=[],
        policy_version="test-policy",
        graph_version_before="g1",
        graph_version_after="g2",
        explanation="Account 360 worker recomposition test",
        decided_by="test",
        decided_at="2026-09-27T00:00:00+00:00",
    )
    monkeypatch.setattr(
        ProjectionRestatementOrchestrator,
        "_determine_projections",
        lambda self, _decision: [ProjectionType.ACCOUNT_360],
    )
    job = await ProjectionRestatementOrchestrator().queue_restatement(decision)
    register_projection_restatement_handler()

    assert await JobWorker(job_types=[PROJECTION_RESTATEMENT_JOB_TYPE]).run_once()

    stored = await get_jobs_service().get_job(tenant_id, job.id)
    restatement = stored["payload"]["restatement"]
    evidence = restatement["projection_evidence"][ProjectionType.ACCOUNT_360.value]
    assert restatement["projection_status"][ProjectionType.ACCOUNT_360.value] == "completed"
    assert evidence["status"] == "recomposed"
    assert evidence["authority"] == "account_organization+account_lifecycle"
    assert evidence["organization_id"] == f"org-{tenant_id}"
    assert evidence["person_relationship_count"] == 2
    assert evidence["affected_people_matched"] == 2
    assert restatement["status"] == "completed"
