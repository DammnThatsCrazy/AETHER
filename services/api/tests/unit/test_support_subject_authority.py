"""Exact producer/store/reader scope and real-registry Support360 boundaries."""

from __future__ import annotations

import os
import sys
import asyncio
import importlib.util
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.support360.cases import (  # noqa: E402
    SupportCaseAuthorityError, SupportCaseEventInput, SupportCaseEventType,
    SupportCaseRepository, reset_local_support_case_store,
)
from journeys.support360.provider import SUPPORT_SLOT_SECTIONS, Support360Provider  # noqa: E402
from journeys.support360.subjects import (  # noqa: E402
    SupportSubjectIngestionService, SupportSubjectInput, SupportSubjectRead,
    SupportSubjectRepository, reset_local_support_subject_store,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest, Experience360PolicyDisposition, Experience360PolicyEvaluation,
    ProjectionContext, ProjectionRequest, ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import build_experience360_frame  # noqa: E402
from tests.unit.test_support360_slot_dispatch import Dependencies  # noqa: E402

TENANT = "subject-tenant"
CONNECTION = "subject-connection"
OBSERVED = datetime.now(timezone.utc) - timedelta(minutes=5)


@pytest.fixture(autouse=True)
def clear_stores():
    reset_local_support_case_store()
    reset_local_support_subject_store()
    yield
    reset_local_support_case_store()
    reset_local_support_subject_store()


class Connections:
    def __init__(self, **changes):
        self.connection = SimpleNamespace(**{
            "tenant_id": TENANT, "connection_id": CONNECTION, "provider_identity": "helpdesk",
            "state": "verified", "selected_accounts": ["account"],
            "last_verified_at": OBSERVED.isoformat(), **changes,
        })

    async def find(self, connection_id):
        return self.connection


async def make_binding(kind="ticket", *, cases=None, connections=None, **changes):
    cases = cases if cases is not None else SupportCaseRepository()
    case = await cases.ingest_event(
        tenant_id=TENANT, connection_id=CONNECTION, provider_identity="helpdesk",
        connection_verified_at=OBSERVED.isoformat(),
        event=SupportCaseEventInput(
            source_case_id="source-case", source_event_id="created",
            event_type=SupportCaseEventType.CREATED, occurred_at=OBSERVED,
        ),
    )
    subjects = SupportSubjectRepository(cases=cases)
    event = SupportSubjectInput(**{
        "kind": kind, "case_id": case["case_id"], "source_case_id": "source-case",
        "source_subject_id": "same-source-id", "source_account_id": "account",
        "source_event_id": f"binding-{kind}", "occurred_at": OBSERVED, **changes,
    })
    service = SupportSubjectIngestionService(
        subjects=subjects, connections=connections if connections is not None else Connections(),
    )
    record = await service.ingest(
        TENANT, CONNECTION, event, actor_id="authenticated-operator", actor_type="tenant_user",
    )
    return cases, subjects, service, event, record


def context():
    return ProjectionContext(
        projectionId="support360", tenantId=TENANT, registryState="in_flight",
        dependencyState=[], warnings=[],
    )


def request_for(record, slot="resolution"):
    return ProjectionRequest(
        projectionId="support360", tenantId=TENANT,
        subject=ProjectionSubject(kind=record["subject_kind"], id=record["subject_id"]),
        includeSections=[SUPPORT_SLOT_SECTIONS[slot]],
    )


def provider(cases, subjects, dependencies):
    return Support360Provider(
        dependencies, case_repository=cases, subject_repository=subjects,
        callback_repository=dependencies, agent_assignment_repository=dependencies,
        case_context_repository=dependencies, sla_measurement_repository=dependencies,
        risk_projection_registry=dependencies,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_authenticated_mapping_is_canonical_immutable_and_replay_safe(kind):
    cases, subjects, service, event, record = await make_binding(kind)
    replay = await service.ingest(
        TENANT, CONNECTION, event, actor_id="another-operator", actor_type="tenant_user",
    )
    assert replay == record
    assert record["subject_id"] not in {event.case_id, event.source_subject_id, event.source_case_id}
    assert record["actor_id"] == "authenticated-operator"
    assert (await subjects.read(TENANT, kind, record["subject_id"])).record == record
    assert (await subjects.read("other-tenant", kind, record["subject_id"])).record is None
    assert (await subjects.read(TENANT, kind, event.source_subject_id)).record is None
    conflicting = event.model_copy(update={"occurred_at": OBSERVED - timedelta(seconds=1)})
    with pytest.raises(SupportCaseAuthorityError):
        await service.ingest(TENANT, CONNECTION, conflicting, actor_id="operator", actor_type="tenant_user")


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"tenant_id": "other-tenant"}, {"connection_id": "wrong-connection"},
    {"state": "disconnected"}, {"provider_identity": "other-provider"},
    {"selected_accounts": ["other-account"]}, {"selected_accounts": "account"},
    {"last_verified_at": None}, {"last_verified_at": "not-a-date"},
    {"last_verified_at": (OBSERVED + timedelta(days=1)).isoformat()},
])
async def test_mapping_ingress_rejects_unverified_or_mismatched_provider_scope(changes):
    with pytest.raises(SupportCaseAuthorityError):
        await make_binding(connections=Connections(**changes))


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"source_case_id": "wrong-source-case"}, {"case_id": str(uuid4())},
    {"source_account_id": "other-account"}, {"occurred_at": OBSERVED + timedelta(days=1)},
])
async def test_mapping_ingress_rejects_wrong_case_account_and_future_assertions(changes):
    with pytest.raises(SupportCaseAuthorityError):
        await make_binding(**changes)


@pytest.mark.parametrize("field", [
    "case_id", "source_case_id", "source_subject_id", "source_account_id", "source_event_id",
])
@pytest.mark.parametrize("value", [" padded", "padded ", "bad\x00id", "bad\x7fid"])
def test_exact_source_identifiers_are_not_normalized(field, value):
    values = {
        "kind": "ticket", "case_id": str(uuid4()), "source_case_id": "case",
        "source_subject_id": "ticket", "source_account_id": "account",
        "source_event_id": "event", "occurred_at": OBSERVED, field: value,
    }
    with pytest.raises(ValidationError):
        SupportSubjectInput(**values)


@pytest.mark.asyncio
async def test_subjects_and_accounts_never_join_on_shared_ids():
    _, subjects, _, _, ticket = await make_binding("ticket")
    _, _, _, _, conversation = await make_binding("conversation")
    assert ticket["subject_id"] != conversation["subject_id"]
    assert (await subjects.read(TENANT, "ticket", conversation["subject_id"])).record is None
    _, _, _, _, other_account = await make_binding(
        connections=Connections(selected_accounts=["account", "second-account"]),
        source_account_id="second-account", source_event_id="second-binding",
    )
    assert other_account["subject_id"] not in {ticket["subject_id"], conversation["subject_id"]}


@pytest.mark.asyncio
async def test_existing_source_subject_cannot_be_remapped_to_another_case():
    cases, _, service, event, _ = await make_binding()
    case = await cases.ingest_event(
        tenant_id=TENANT, connection_id=CONNECTION, provider_identity="helpdesk",
        connection_verified_at=OBSERVED.isoformat(),
        event=SupportCaseEventInput(
            source_case_id="second-case", source_event_id="second-create",
            event_type=SupportCaseEventType.CREATED, occurred_at=OBSERVED,
        ),
    )
    conflicting = event.model_copy(update={
        "case_id": case["case_id"], "source_case_id": "second-case", "source_event_id": "new-event",
    })
    with pytest.raises(SupportCaseAuthorityError):
        await service.ingest(TENANT, CONNECTION, conflicting, actor_id="operator", actor_type="tenant_user")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
@pytest.mark.parametrize(("slot", "reads"), [
    ("case_summary", []), ("resolution", []), ("evidence_trace", []),
    ("conversation_history", ["conversation_history"]), ("callbacks", ["callbacks"]),
    ("agents", ["agents"]), ("sla", ["sla", "sla_contract"]),
    ("journey_links", ["journey_links"]), ("participants", ["participants"]),
])
async def test_mapped_case_slots_preserve_exact_policy_isolation(kind, slot, reads):
    cases, subjects, _, _, record = await make_binding(kind)
    dependencies = Dependencies()
    request = request_for(record, slot)
    result = await provider(cases, subjects, dependencies).project(request, context())
    assert dependencies.calls == reads
    assert len(result.sections) == 1
    assert result.sections[0].id == SUPPORT_SLOT_SECTIONS[slot]
    if slot in {"resolution", "case_summary", "evidence_trace", "conversation_history"}:
        assert result.sections[0].state == "available"
        join = result.sections[0].content["subjectCaseJoin"]
        assert join["canonicalCaseId"] == record["case_id"]
        assert join["canonicalSubjectId"] == record["subject_id"]
        assert join["sourceAccountId"] == "account"
        assert join["sourceAuthenticity"] == "unverified"
        assert join["businessOutcomeState"] == "unknown"
    assert all(claim.subject == request.subject for claim in result.claims)
    assert "private-message-must-not-leak" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "value"), [
    ("tenant_id", "other-tenant"), ("subject_kind", "conversation"),
    ("subject_id", "c013c99a-4947-445a-b1ae-da48cb33e70e"), ("source_connection_id", "other-connection"),
    ("source_provider_identity", "other-provider"), ("source_case_id", "wrong-source-case"),
    ("case_id", "5a1c7d2e-58c4-4f0b-9f3d-2f1f2c8e6b11"), ("source_account_id", None), ("actor_id", ""),
    ("source_event_id", None), ("source_occurred_at", "invalid"),
    ("source_occurred_at", OBSERVED.replace(tzinfo=None)),
    ("connection_verified_at", None), ("connection_verified_at", "invalid"),
    ("connection_verified_at", "2999-01-01T00:00:00+00:00"),
    ("evidence_refs", []), ("evidence_refs", [{"id": "forged"}]),
    ("received_at", "2999-01-01T00:00:00+00:00"),
])
async def test_reader_rechecks_mapping_before_any_sibling_read(field, value):
    cases, _, _, _, record = await make_binding()
    contaminated = {**record, field: value}

    class ContaminatedSubjects:
        async def read(self, *args):
            return SupportSubjectRead(contaminated, True, True)

    dependencies = Dependencies()
    result = await provider(cases, ContaminatedSubjects(), dependencies).project(
        request_for(record, "conversation_history"), context(),
    )
    assert result.sections[0].state == "unknown"
    assert result.sections[0].content is None
    assert not result.claims
    assert not dependencies.calls


@pytest.mark.asyncio
@pytest.mark.parametrize(("available", "complete"), [(True, False), (False, True)])
async def test_incomplete_or_unavailable_binding_reads_suppress_all_evidence(available, complete):
    cases, _, _, _, record = await make_binding()

    class IncompleteSubjects:
        async def read(self, *args):
            return SupportSubjectRead(record, available, complete)

    dependencies = Dependencies()
    result = await provider(cases, IncompleteSubjects(), dependencies).project(request_for(record), context())
    assert result.sections[0].content is None
    assert not result.claims
    assert not dependencies.calls


@pytest.mark.asyncio
async def test_cross_tenant_and_historical_requests_do_not_resolve_subjects():
    cases, subjects, _, _, record = await make_binding()

    class UnreadableSubjects:
        async def read(self, *args):
            raise AssertionError("subject authority must not be read")

    dependencies = Dependencies()
    projection = provider(cases, UnreadableSubjects(), dependencies)
    request = request_for(record)
    for update in ({"tenantId": "wrong-tenant"}, {"asOf": OBSERVED.isoformat()}, {"temporalMode": "as_of"}):
        result = await projection.project(request.model_copy(update=update), context())
        assert result.sections[0].content is None
        assert result.degradedReasons != ["support_subject_binding_unavailable"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_real_registry_alias_dispatch_follows_only_declared_subject_bindings(kind):
    from shared.intelligence_projections.generated_registry import PRODUCT_360_SURFACE_DEFINITIONS

    cases, subjects, _, _, record = await make_binding(kind)
    support = provider(cases, subjects, Dependencies())
    expected_sections = sorted({
        section for slot in PRODUCT_360_SURFACE_DEFINITIONS["support360"]["domainSlots"]
        if slot["id"] in SUPPORT_SLOT_SECTIONS
        for binding in slot["projectionBindings"]
        if binding["projectionId"] == "support360" and kind in binding["subjectKinds"]
        for section in binding["sectionIds"]
    })
    dispatched = []

    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="support360", tenantId=TENANT, evaluatedAt=OBSERVED.isoformat(),
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={slot: Experience360PolicyDisposition(state="allowed") for slot in SUPPORT_SLOT_SECTIONS},
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            assert request.projectionId == "support360"
            dispatched.append(request.includeSections)
            return await support.project(request, context())

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="support360", tenantId=TENANT,
            subject=ProjectionSubject(kind=kind, id=record["subject_id"]),
            requestedSlotIds=list(SUPPORT_SLOT_SECTIONS), includeEvidence=True,
        ), policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    assert dispatched == ([expected_sections] if expected_sections else [])
    if not expected_sections:
        assert all(slot.content is None and not slot.claims for slot in frame.slots)
    else:
        for slot in frame.slots:
            if slot.content is not None:
                content = slot.content["sections"][0]["content"]
                assert content["subjectCaseJoin"]["canonicalCaseId"] == record["case_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_subject_route_authenticates_producer_then_reads_exact_subject(kind, monkeypatch):
    from journeys.support360 import routes
    from shared.common.common import ForbiddenError

    cases, subjects, service, event, _ = await make_binding(kind)
    monkeypatch.setattr(routes, "SupportSubjectIngestionService", lambda: service)
    monkeypatch.setattr(routes, "tenant_actor", lambda request: SimpleNamespace(
        tenant_id=TENANT, actor_id="authenticated-operator", actor_type="tenant_user",
    ))
    permissions = set()

    def require_permission(permission):
        if permission not in permissions:
            raise ForbiddenError("write required")

    server_request = SimpleNamespace(state=SimpleNamespace(tenant=SimpleNamespace(
        tenant_id=TENANT, require_permission=require_permission,
    )))
    body = routes.SupportSubjectIngestBody(connection_id=CONNECTION, binding=event)
    with pytest.raises(ForbiddenError):
        await routes.ingest_support_subject(server_request, body)
    permissions.add("write")
    response = await routes.ingest_support_subject(server_request, body)
    result = await provider(cases, subjects, Dependencies()).project(
        request_for({**response["data"], "subject_kind": kind}), context(),
    )
    assert result.sections[0].state == "available"
    assert result.sections[0].content["subjectCaseJoin"]["canonicalCaseId"] == event.case_id
    for extra in ({"tenant_id": "forged"}, {"actor_id": "forged"}):
        with pytest.raises(ValidationError):
            routes.SupportSubjectIngestBody.model_validate({**body.model_dump(), **extra})
        with pytest.raises(ValidationError):
            SupportSubjectInput.model_validate({**event.model_dump(), **extra})


@pytest.mark.asyncio
async def test_nested_provenance_is_not_mutable_through_local_reads():
    _, subjects, _, _, record = await make_binding()
    read = await subjects.read(TENANT, "ticket", record["subject_id"])
    read.record["evidence_refs"][0]["source"] = "forged"
    assert (await subjects.read(TENANT, "ticket", record["subject_id"])).record == record


@pytest.mark.asyncio
async def test_same_external_event_in_distinct_provider_accounts_is_not_aliased():
    cases, subjects, service, event, first = await make_binding()
    service.connections.connection.selected_accounts.append("second-account")
    second = await service.ingest(
        TENANT, CONNECTION, event.model_copy(update={"source_account_id": "second-account"}),
        actor_id="operator", actor_type="tenant_user",
    )
    assert first["subject_id"] != second["subject_id"]
    assert (await subjects.read(TENANT, "ticket", first["subject_id"])).record == first
    assert (await subjects.read(TENANT, "ticket", second["subject_id"])).record == second


@pytest.mark.asyncio
async def test_new_source_event_cannot_rewrite_immutable_mapping_provenance():
    _, _, service, event, _ = await make_binding()
    with pytest.raises(SupportCaseAuthorityError):
        await service.ingest(
            TENANT, CONNECTION, event.model_copy(update={"source_event_id": "different-event"}),
            actor_id="operator", actor_type="tenant_user",
        )


def test_subject_ingress_is_mounted_in_application():
    from main import create_app

    assert set(create_app().openapi()["paths"]["/v1/support/cases/subjects/ingest"]) == {"post"}


@pytest.mark.parametrize("case_id", ["not-a-uuid", "DF3B1CC3-14E3-4230-9076-6C3E1056E4DD"])
def test_subject_ingress_rejects_noncanonical_case_ids(case_id):
    with pytest.raises(ValidationError):
        SupportSubjectInput(
            kind="ticket", case_id=case_id, source_case_id="case", source_subject_id="ticket",
            source_account_id="account", source_event_id="event", occurred_at=OBSERVED,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
@pytest.mark.parametrize(("slot_id", "reads"), [
    ("case_summary", []), ("resolution", []), ("evidence_trace", []),
    ("conversation_history", ["conversation_history"]), ("callbacks", ["callbacks"]),
    ("agents", ["agents"]), ("sla", ["sla", "sla_contract"]),
    ("journey_links", ["journey_links"]), ("participants", ["participants"]),
])
async def test_production_alias_bindings_compose_through_real_frame(
    kind, slot_id, reads,
):
    cases, subjects, _, _, record = await make_binding(kind)
    dependencies = Dependencies()
    support = provider(cases, subjects, dependencies)

    class Policy:
        async def evaluate(self, request):
            return Experience360PolicyEvaluation(
                surfaceId="support360", tenantId=TENANT, evaluatedAt=OBSERVED.isoformat(),
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    slot: Experience360PolicyDisposition(
                        state="allowed" if slot == slot_id else "denied",
                    ) for slot in [*SUPPORT_SLOT_SECTIONS, "risk"]
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            assert request.projectionId == "support360"
            assert request.includeSections == [SUPPORT_SLOT_SECTIONS[slot_id]]
            return await support.project(request, context())

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="support360", tenantId=TENANT,
            subject=ProjectionSubject(kind=kind, id=record["subject_id"]),
            requestedSlotIds=[*SUPPORT_SLOT_SECTIONS, "risk"], includeEvidence=True,
        ), policy_evaluator=Policy(), projection_runtime=Runtime(),
    )
    assert dependencies.calls == reads
    for slot in frame.slots:
        if slot.id != slot_id:
            assert slot.content is None and not slot.claims and not slot.evidenceRefs
        elif slot_id in {"resolution", "case_summary", "evidence_trace", "conversation_history"}:
            assert slot.state in {"available", "degraded"}
            assert slot.content["sections"][0]["content"]["subjectCaseJoin"]["canonicalCaseId"] == record["case_id"]
            assert slot.claims and slot.evidenceRefs
            assert all(claim.subject.kind == kind and claim.subject.id == record["subject_id"] for claim in slot.claims)


@pytest.fixture(scope="module")
def postgres_address():
    initdb = shutil.which("initdb")
    pg_ctl = shutil.which("pg_ctl")
    if initdb is None or pg_ctl is None:
        pytest.skip("local PostgreSQL binaries are required for durable store tests")
    with tempfile.TemporaryDirectory(prefix="support-subject-", dir="/tmp") as directory:
        database = str(Path(directory) / "database")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        subprocess.run(
            [initdb, "-D", database, "-A", "trust", "--no-locale", "--no-sync"],
            check=True, capture_output=True, text=True,
        )
        subprocess.run(
            [pg_ctl, "-D", database, "-l", str(Path(directory) / "postgres.log"),
             "-o", f"-F -k {directory} -p {port} -h ''", "-w", "start"],
            check=True, capture_output=True, text=True,
        )
        try:
            yield {"host": directory, "port": port, "database": "postgres", "user": os.environ.get("USER")}
        finally:
            subprocess.run(
                [pg_ctl, "-D", database, "-m", "immediate", "-w", "stop"],
                check=True, capture_output=True, text=True,
            )


def migration_statements(name, operation="upgrade"):
    path = BACKEND_ROOT / "alembic" / "versions" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements = []
    module.op = SimpleNamespace(execute=statements.append)
    getattr(module, operation)()
    return statements


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["ticket", "conversation"])
async def test_postgres_migrations_durable_replay_composition_and_cascade(postgres_address, kind):
    import asyncpg

    pool = await asyncpg.create_pool(**postgres_address, min_size=1, max_size=4)
    try:
        await pool.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        for name in (
            "20261022_support_case_authority", "20261023_support_callback_authority",
            "20261105_support_case_subjects",
        ):
            for statement in migration_statements(name):
                await pool.execute(statement)
        cases = SupportCaseRepository(pool=pool)
        _, subjects, service, event, record = await make_binding(kind, cases=cases)
        replays = await asyncio.gather(*[
            service.ingest(TENANT, CONNECTION, event, actor_id="operator", actor_type="tenant_user")
            for _ in range(4)
        ])
        assert all(replay == record for replay in replays)
        assert await pool.fetchval("SELECT count(*) FROM support_case_subjects") == 1
        dependencies = Dependencies()
        result = await provider(cases, subjects, dependencies).project(request_for(record), context())
        assert result.sections[0].state == "available"
        assert result.sections[0].content["subjectCaseJoin"]["canonicalCaseId"] == event.case_id
        assert dependencies.calls == []
        await pool.close()
        pool = await asyncpg.create_pool(**postgres_address, min_size=1, max_size=2)
        recovered = SupportSubjectRepository(cases=SupportCaseRepository(pool=pool))
        assert (await recovered.read(TENANT, kind, record["subject_id"])).record == record
        assert (await recovered.read("other-tenant", kind, record["subject_id"])).record is None
        conflicting = event.model_copy(update={"source_subject_id": "another-subject"})
        with pytest.raises(SupportCaseAuthorityError):
            await SupportSubjectIngestionService(subjects=recovered, connections=Connections()).ingest(
                TENANT, CONNECTION, conflicting, actor_id="operator", actor_type="tenant_user",
            )
        assert await pool.fetchval("SELECT count(*) FROM support_case_subjects") == 1
        await pool.execute("DELETE FROM support_cases WHERE tenant_id=$1 AND case_id=$2", TENANT, event.case_id)
        assert (await recovered.read(TENANT, kind, record["subject_id"])).record is None
        assert await pool.fetchval("SELECT count(*) FROM support_case_subjects") == 0
        for statement in migration_statements("20261105_support_case_subjects", "downgrade"):
            await pool.execute(statement)
        assert await pool.fetchval("SELECT to_regclass('support_case_subjects')") is None
    finally:
        await pool.close()
