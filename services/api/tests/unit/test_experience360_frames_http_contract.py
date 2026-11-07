"""HTTP-boundary contract for ``POST /v1/experience360/frames`` (Access Kit W2 slice).

The sibling route tests invoke the handler function directly. These tests mount
the real router in a FastAPI app and drive it over HTTP so the wire contract an
external adapter depends on is pinned: request validation (``extra="forbid"``,
no caller-selected tenant), the ``read`` permission gate, per-slot policy denial
through the real ``RequestAccessPolicyEvaluator`` + ``AccessControlService``,
tenant-bound provider reads, and preservation of partial / unknown slot states
(no promotion to a stronger state, no fabricated content).

Scope: the first Access Kit slice, ``profile360`` / subject kind ``entity``.
Provider data is simulated at the projection-runtime seam; this proves the
route/frame/policy contract, not live provider data (that is a higher evidence
tier than these fixtures).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.auth.auth import Role, TenantContext  # noqa: E402
from shared.common.common import AetherError  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.routes import router  # noqa: E402

SUBJECT_ID = "entity-shared-id"
GENERATED_AT = "2026-10-30T12:00:00Z"
FIRST_SLICE_SLOTS = ["identity_spine", "known_unknown_resolution", "evidence_trace"]


class _FakeProfileRuntime:
    """Tenant-keyed stand-in for the projection runtime (the provider seam)."""

    def __init__(self, records: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.records = records
        self.calls: list[tuple[str, str, str]] = []

    async def execute_projection(self, request, **_kwargs) -> ProjectionResult:
        self.calls.append((request.tenantId, request.projectionId, request.subject.id))
        sections = tuple(sorted(request.includeSections or []))
        record = self.records.get((request.tenantId, request.subject.id))
        if record is None:
            # No tenant-owned record: typed unknown, never empty/known-absent.
            return ProjectionResult(
                projectionId=request.projectionId,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[ProjectionSection(id=s, state="unknown") for s in sections],
                claims=[],
                dependencyState=[],
                generatedAt=GENERATED_AT,
                degradedReasons=["profile_record_not_found"],
            )
        evidence = EvidenceRef(
            id=f"identity-{request.tenantId}",
            type="entity",
            source="identity_profiles",
            observedAt=GENERATED_AT,
        )
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[
                ProjectionSection(
                    id=section_id,
                    state="available" if section_id in record["available"] else "unknown",
                    content=(
                        {"displayName": record["name"]}
                        if section_id in record["available"]
                        else None
                    ),
                    canonicalAuthorityRefs=(
                        ["evidence"]
                        if section_id in {"evidence", "findings"}
                        else ["entity_registry", "identity"]
                    ),
                )
                for section_id in sections
            ],
            claims=[
                ClaimEnvelope(
                    id="profile360.identity_record_present",
                    kind="identity",
                    subject=ProjectionSubject(kind="entity", id=request.subject.id),
                    evidenceRefs=[evidence],
                    claims=["identity record present"],
                    claimState="observed",
                    domainSlotIds=["identity_spine", "known_unknown_resolution", "evidence_trace"],
                )
            ],
            dependencyState=[],
            generatedAt=GENERATED_AT,
            degradedReasons=[],
        )


def _app(runtime: _FakeProfileRuntime) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.experience360_projection_runtime = runtime

    # Mirrors middleware.register_middleware's AetherError handler.
    @app.exception_handler(AetherError)
    async def _aether_error(_request: Request, exc: AetherError) -> JSONResponse:
        return JSONResponse(status_code=exc.code.value, content=exc.to_dict())

    # Stand-in for the auth middleware: tenant/role/permissions come from the
    # test credential headers and are the ONLY source of tenant identity.
    @app.middleware("http")
    async def _auth(request: Request, call_next):
        tenant_id = request.headers.get("x-test-tenant")
        if not tenant_id:
            return JSONResponse(status_code=401, content={"detail": "unauthenticated"})
        permissions = [p for p in request.headers.get("x-test-permissions", "").split(",") if p]
        request.state.tenant = TenantContext(
            tenant_id=tenant_id,
            user_id=f"user-of-{tenant_id}",
            role=Role(request.headers.get("x-test-role", "viewer")),
            permissions=permissions,
        )
        return await call_next(request)

    return app


def _headers(tenant: str, *, role: str = "viewer", permissions: str = "read") -> dict[str, str]:
    return {"x-test-tenant": tenant, "x-test-role": role, "x-test-permissions": permissions}


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "surfaceId": "profile360",
        "subject": {"kind": "entity", "id": SUBJECT_ID},
        "requestedSlotIds": list(FIRST_SLICE_SLOTS),
        "includeEvidence": True,
    }
    body.update(overrides)
    return body


def _slots(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {slot["id"]: slot for slot in payload["slots"]}


@pytest.fixture
def runtime() -> _FakeProfileRuntime:
    return _FakeProfileRuntime(
        {
            ("tenant-a", SUBJECT_ID): {
                "name": "Tenant A Private Name",
                "available": {"state", "summary", "evidence", "findings"},
            },
        }
    )


@pytest.fixture
def client(runtime: _FakeProfileRuntime) -> TestClient:
    return TestClient(_app(runtime))


def test_same_tenant_read_returns_bare_governed_frame(client, runtime) -> None:
    response = client.post(
        "/v1/experience360/frames", json=_body(), headers=_headers("tenant-a")
    )

    assert response.status_code == 200
    payload = response.json()
    # Wire contract: the frame is the top-level body (no ``data`` envelope).
    assert "data" not in payload
    assert payload["surfaceId"] == "profile360"
    assert payload["tenantId"] == "tenant-a"
    assert payload["subject"] == {"kind": "entity", "id": SUBJECT_ID}
    assert payload["ownsCanonicalTruth"] is False
    slots = _slots(payload)
    assert set(slots) == set(FIRST_SLICE_SLOTS)
    identity = slots["identity_spine"]
    assert identity["state"] in {"available", "degraded"}
    assert identity["policyDisposition"]["state"] == "allowed"
    assert identity["evidenceRefs"] or any(item["evidenceRefs"] for item in identity["provenance"])
    assert {call[0] for call in runtime.calls} == {"tenant-a"}


def test_same_subject_id_in_other_tenant_discloses_nothing(client, runtime) -> None:
    response = client.post(
        "/v1/experience360/frames", json=_body(), headers=_headers("tenant-b")
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenantId"] == "tenant-b"
    assert "Tenant A Private Name" not in response.text
    assert "identity-tenant-a" not in response.text
    assert {call[0] for call in runtime.calls} == {"tenant-b"}
    for slot in payload["slots"]:
        # The foreign tenant's request finds no tenant-owned record: every slot
        # is typed degraded/unknown and carries no content, claims, or evidence.
        assert slot.get("content") is None
        assert slot["state"] != "available"
        assert not slot.get("claims")
        assert not slot.get("evidenceRefs")
    assert payload["state"] != "ready"
    assert payload["degradation"]["level"] == "full"


def test_caller_cannot_select_a_tenant(client, runtime) -> None:
    for field in ("tenantId", "tenant_id", "requestedBy"):
        response = client.post(
            "/v1/experience360/frames",
            json=_body(**{field: "tenant-a"}),
            headers=_headers("tenant-b"),
        )
        assert response.status_code == 422
    assert runtime.calls == []


def test_missing_read_permission_is_forbidden_before_any_read(client, runtime) -> None:
    response = client.post(
        "/v1/experience360/frames",
        json=_body(),
        headers=_headers("tenant-a", permissions="write"),
    )

    assert response.status_code == 403
    assert runtime.calls == []
    assert "Tenant A Private Name" not in response.text


def test_unauthenticated_request_is_rejected_before_any_read(client, runtime) -> None:
    response = client.post("/v1/experience360/frames", json=_body())

    assert response.status_code == 401
    assert runtime.calls == []


def test_slot_denied_by_central_policy_is_suppressed_without_content_or_read(
    client, runtime
) -> None:
    # EDITOR maps to ``tenant_operator`` which holds no ``data_exchange`` read
    # grant; ``evidence_trace`` is governed by ``data_exchange`` while
    # ``identity_spine`` is governed by ``profile``.
    response = client.post(
        "/v1/experience360/frames",
        json=_body(),
        headers=_headers("tenant-a", role="editor"),
    )

    assert response.status_code == 200
    slots = _slots(response.json())
    denied = slots["evidence_trace"]
    assert denied["state"] == "suppressed"
    assert denied["policyDisposition"]["state"] == "denied"
    assert denied.get("content") is None
    assert not denied.get("claims")
    assert slots["identity_spine"]["policyDisposition"]["state"] == "allowed"
    assert "Tenant A Private Name" not in str(denied)


def test_unknown_provider_evidence_is_preserved_not_promoted(client, runtime) -> None:
    runtime.records[("tenant-a", SUBJECT_ID)] = {
        "name": "Tenant A Private Name",
        # Only ``summary`` is known; ``state`` stays unknown, so slots that need
        # ``state`` must not be promoted to a stronger state.
        "available": {"summary"},
    }

    response = client.post(
        "/v1/experience360/frames", json=_body(), headers=_headers("tenant-a")
    )

    assert response.status_code == 200
    payload = response.json()
    slots = _slots(payload)
    assert payload["state"] != "ready"
    for slot in slots.values():
        if slot["state"] in {"missing", "unknown", "suppressed", "unavailable"}:
            assert slot.get("content") is None
        if slot["requirement"] == "required" and slot["state"] == "available":
            assert slot["provenance"] and (
                slot["evidenceRefs"] or any(p["evidenceRefs"] for p in slot["provenance"])
            )
    # profile360 identity slots are flagged partial/limited in the catalog and
    # the frame must keep that explicit rather than declaring completeness.
    assert any(
        slot["state"] != "available" or slot.get("limitations") or slot.get("reasonCodes")
        for slot in slots.values()
    )


@pytest.mark.parametrize(
    "override",
    [
        {"surfaceId": "not-a-surface"},
        {"surfaceId": "Profile360"},  # surface ids are lowercase
        {"subject": {"kind": "wallet_cluster_zzz", "id": SUBJECT_ID}},
        {"subject": {"kind": "campaign", "id": SUBJECT_ID}},  # not a profile360 subject kind
        {"requestedSlotIds": ["not_a_slot"]},
        {"requestedSlotIds": []},
        {"requestedSlotIds": ["identity_spine", "identity_spine"]},
        {"subject": {"kind": "entity", "id": "   "}},
        {"asOf": "2026-10-30T12:00:00"},  # timezone required
        {"asOf": "not-a-date"},
        {"unexpectedField": True},
        # Server-side bounds hold for any client, not only the Access Kit adapter.
        {"subject": {"kind": "entity", "id": "e" * 257}},
        {"requestedSlotIds": ["identity_spine"] * 65},
        {"requestedSlotIds": ["s" * 129]},
        {"lensIds": ["l"] * 17},
        {"purpose": "p" * 257},
        {"authorizationContextRef": "a" * 257},
        {"asOf": "2026-10-30T12:00:00+00:00" + " " * 64},
    ],
)
def test_invalid_requests_are_rejected_before_any_read(client, runtime, override) -> None:
    response = client.post(
        "/v1/experience360/frames", json=_body(**override), headers=_headers("tenant-a")
    )

    assert response.status_code == 422, response.text
    assert runtime.calls == []


def test_frame_route_is_post_only(client) -> None:
    response = client.get("/v1/experience360/frames", headers=_headers("tenant-a"))

    assert response.status_code == 405
