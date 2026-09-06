"""DB-free tests for the Data Exchange Plane M3 import control envelope.

Exercises ``services/data_exchange/routes_import.py`` handlers directly (no
ASGI, no Postgres): the envelope's ``data_artifacts`` marker rows live in the
M1 repo's module-local in-memory store (``repos.get_pool`` pinned to None, per
the ``test_storage_migration.py`` DB-free pattern), while the canonical engine
seams the envelope proxies — ``services/imports/service`` FSM calls, the
identity/graph preview read-side seams, the durable-jobs enqueue, and the
canonical commit rollback — are monkeypatched at their module binding sites.
Each test still exercises the real envelope code path (id translation,
permission gates, marker status vocabulary, filter/translate logic).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.data_exchange.graph_preview as graph_preview_mod  # noqa: E402
import services.data_exchange.identity_preview as identity_preview_mod  # noqa: E402
import services.imports.service as imports_svc_mod  # noqa: E402
import services.imports.commit as imports_commit_mod  # noqa: E402
import services.jobs.service as jobs_svc_mod  # noqa: E402
import services.data_exchange.routes_import as routes_mod  # noqa: E402
from repositories.data_artifacts import (  # noqa: E402
    get_data_artifact_repository,
    reset_data_artifact_in_memory_store,
)
from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.data_exchange.contracts import (  # noqa: E402
    ImportMappingContract,
    ImportSourceContract,
)
from services.data_exchange.identity_preview import (  # noqa: E402
    IdentityFieldProbe,
    IdentityPreviewBody,
)
from shared.common.common import (  # noqa: E402
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)

TENANT = "tnt_env_a"
ARTIFACT_REPO = get_data_artifact_repository()


@pytest.fixture(autouse=True)
def _db_free(monkeypatch: pytest.MonkeyPatch):
    async def _no_pool() -> Any:  # noqa: ANN401 - matches get_pool's Any return
        return None

    monkeypatch.setattr("repositories.repos.get_pool", _no_pool)
    monkeypatch.setattr("repositories.data_artifacts.get_pool", _no_pool)
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()
    yield
    reset_data_artifact_in_memory_store()
    reset_in_memory_stores()


class _Tenant:
    def __init__(self, tenant_id: str = TENANT) -> None:
        self.tenant_id = tenant_id
        self.user_id = f"user-{tenant_id}"
        self.plan_tier: Optional[str] = None

    def require_permission(self, permission: str) -> None:
        return None  # grant matrix is exercised by real TenantContext in CI

    def require_any_permission(self, *perms: str) -> None:
        return None  # grant matrix is exercised by real TenantContext in CI


class _Request:
    def __init__(self, tenant: Optional[_Tenant] = None) -> None:
        self.state = SimpleNamespace(
            tenant=tenant or _Tenant(), request_id="req_env_1"
        )
        self.headers: dict[str, str] = {}


def _source(import_id: str, artifact_id: str) -> ImportSourceContract:
    return ImportSourceContract(
        import_id=import_id,
        tenant_id=TENANT,
        source_type="file",
        artifact_id=artifact_id,
        format="csv",
        ownership="tenant_owned",
        terms_status="accepted",
        provenance={"created_via": "envelope_test"},
    )


def _canonical_session(canonical_id: str, status: str = "created") -> dict:
    return {
        "id": canonical_id,
        "tenant_id": TENANT,
        "status": status,
        "source_kind": "file_upload",
        "file_count": 0,
        "row_count": None,
        "created_by": f"user-{TENANT}",
        "created_at": "2026-09-05T00:00:00+00:00",
    }


async def _seed_envelope_import(monkeypatch: pytest.MonkeyPatch, import_id: str) -> dict:
    """Create one envelope import through the real route (fake canonical svc)."""
    canonical_id = f"canonical_{import_id}"

    async def _fake_create(tenant_id: str, *, created_by: Optional[str] = None) -> dict:
        return _canonical_session(canonical_id, status="created")

    monkeypatch.setattr(imports_svc_mod, "create_import", _fake_create)
    artifact_id = f"de_art_{import_id}"
    body = _source(import_id=import_id, artifact_id=artifact_id)
    result = await routes_mod.create_import(request=_Request(), body=body)
    assert result["canonical_id"] == canonical_id
    return result


# ── POST /imports (create) ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_import_registers_envelope_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _seed_envelope_import(monkeypatch, "imp_env_1")
    assert result["import_id"] == "imp_env_1"
    assert result["status"] == "created"
    assert result["canonical_id"] == "canonical_imp_env_1"
    assert result["artifact_id"] == "de_art_imp_env_1"

    marker = await ARTIFACT_REPO.get(TENANT, "de_art_imp_env_1")
    assert marker["canonical_id"] == "canonical_imp_env_1"
    assert marker["direction"] == "ingress"
    assert marker["artifact_type"] == "import_source"
    src = marker["source_or_destination"]
    assert src["envelope"] == "import_source"
    assert src["import_id"] == "imp_env_1"
    assert marker["status"] == "created"


@pytest.mark.asyncio
async def test_create_import_duplicate_import_id_is_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_dup")
    with pytest.raises(ConflictError):
        await routes_mod.create_import(request=_Request(), body=_source("imp_dup", "de_art_imp_dup"))


@pytest.mark.asyncio
async def test_create_import_rejects_cross_tenant_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = _Request(_Tenant(TENANT))
    other = _source("imp_other", "de_art_other")
    other = other.model_copy(update={"tenant_id": "tnt_other"})
    with pytest.raises(ForbiddenError):
        await routes_mod.create_import(request=req, body=other)


# ── GET /imports (feed) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_imports_renders_feed_with_markers_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await _seed_envelope_import(monkeypatch, "imp_feed_1")
    committed = await _seed_envelope_import(monkeypatch, "imp_feed_2")

    canonical_created = created["canonical_id"]
    canonical_committed = committed["canonical_id"]

    async def _fake_list(tenant_id: str, *, limit: int = 50, offset: int = 0) -> list[dict]:
        return [
            _canonical_session(canonical_committed, status="committed"),
            _canonical_session(canonical_created, status="created"),
            _canonical_session("canonical_legacy_only", status="created"),
        ]

    monkeypatch.setattr(imports_svc_mod, "list_imports", _fake_list)

    # Query-parameter defaults are injected explicitly: the tests call the
    # route handlers directly (not through FastAPI's dependency injection), so
    # an omitted ``Query(default=...)`` parameter arrives as the sentinel Query
    # object rather than its default value.
    base = {"direction_filter": None, "status_filter": None, "format_filter": None, "limit": 50, "offset": 0}
    listing = await routes_mod.list_imports(request=_Request(), **base)
    assert listing["count"] == 3
    by_id = {e["import_id"]: e for e in listing["imports"]}
    assert set(by_id) == {"imp_feed_1", "imp_feed_2", "canonical_legacy_only"}
    # Canonical terminal status wins over the envelope marker's coarse status.
    assert by_id["imp_feed_2"]["status"] == "committed"
    assert by_id["imp_feed_1"]["status"] == "created"
    assert by_id["canonical_legacy_only"]["artifact_id"] is None

    filtered = await routes_mod.list_imports(
        request=_Request(), **{**base, "status_filter": "committed"}
    )
    assert filtered["count"] == 1
    assert filtered["imports"][0]["import_id"] == "imp_feed_2"

    with pytest.raises(BadRequestError):
        await routes_mod.list_imports(
            request=_Request(), **{**base, "status_filter": "bogus"}
        )
    with pytest.raises(BadRequestError):
        await routes_mod.list_imports(
            request=_Request(), **{**base, "direction_filter": "sideways"}
        )
    with pytest.raises(BadRequestError):
        await routes_mod.list_imports(
            request=_Request(), **{**base, "format_filter": "xlsx"}
        )
    # egress direction is not an import feed — deterministic empty.
    egress = await routes_mod.list_imports(
        request=_Request(), **{**base, "direction_filter": "egress"}
    )
    assert egress == {"imports": [], "count": 0}


# ── GET /imports/{import_id} (detail) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_get_import_returns_envelope_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_get_1")

    async def _fake_get(tenant_id: str, import_id: str) -> dict:
        return {
            "session": _canonical_session("canonical_imp_get_1", status="created"),
            "files": [],
            "schemas": [],
            "mapping": None,
            "validation": None,
        }

    monkeypatch.setattr(imports_svc_mod, "get_import", _fake_get)
    detail = await routes_mod.get_import("imp_get_1", request=_Request())
    assert detail["import_id"] == "imp_get_1"
    assert detail["canonical_id"] == "canonical_imp_get_1"
    assert detail["artifact"]["status"] == "created"
    assert detail["source"]["source_type"] == "file"
    assert detail["source"]["artifact_id"] == "de_art_imp_get_1"
    assert detail["canonical"]["status"] == "created"


@pytest.mark.asyncio
async def test_get_import_missing_raises_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # canonical-only fallback also validates the session exists before serving
    class _FakeRepo:
        async def get_session(self, tenant_id: str, import_id: str) -> dict:
            raise NotFoundError("import session")

    monkeypatch.setattr(routes_mod, "get_imports_repository", lambda: _FakeRepo())
    with pytest.raises(NotFoundError):
        await routes_mod.get_import("does_not_exist", request=_Request())


# ── PUT /imports/{import_id}/mapping ────────────────────────────────────────


def _mapping_body(import_id: str, *, tenant_id: str = TENANT) -> ImportMappingContract:
    return ImportMappingContract(
        import_id=import_id,
        tenant_id=tenant_id,
        version=1,
        fields=[
            {
                "source_column": "email",
                "primitive": "identifier",
                "target_field": "value",
                "transform": "none",
            }
        ],
        identity_policy={"match_keys": ["email"]},
        temporal_policy={},
        currency_policy={},
        geographic_policy={},
        consent_policy={},
        unknown_field_policy="error",
        created_by=None,
        created_at="2026-09-05T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_set_mapping_translates_envelope_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_map_1")
    captured: dict[str, Any] = {}

    async def _fake_set_mapping(tenant_id: str, import_id: str, fields: list[dict]) -> dict:
        captured["fields"] = fields
        return {"import_id": import_id, "version": 2, "fields": fields}

    monkeypatch.setattr(imports_svc_mod, "set_mapping", _fake_set_mapping)
    result = await routes_mod.set_mapping(
        "imp_map_1", body=_mapping_body("imp_map_1"), request=_Request()
    )
    assert result["mapping_version"] == 2
    # Envelope sub-route translated the envelope id to the canonical session id.
    assert captured["fields"][0]["source_column"] == "email"
    assert captured["fields"][0]["required"] is False


@pytest.mark.asyncio
async def test_set_mapping_rejects_id_and_tenant_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_map_2")
    with pytest.raises(BadRequestError):
        await routes_mod.set_mapping(
            "imp_map_2", body=_mapping_body("some_other_import"), request=_Request()
        )
    with pytest.raises(ForbiddenError):
        await routes_mod.set_mapping(
            "imp_map_2",
            body=_mapping_body("imp_map_2", tenant_id="tnt_other"),
            request=_Request(),
        )


# ── preview adapters ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_identity_decisions_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_idp_1")
    canonical_id = "canonical_imp_idp_1"

    async def _session(tenant_id: str, import_id: str) -> dict:
        return _canonical_session(canonical_id, status="mapped")

    async def _mapping(tenant_id: str, import_id: str) -> dict:
        return {"version": 1, "fields": [{"source_column": "customer_id", "primitive": "identifier"}]}

    async def _alias(tenant_id: str, signal_type: str, value_hash: str) -> list[str]:
        return ["subject_1"]

    async def _suppressed(tenant_id: str, signal_type: str, value_hash: str) -> bool:
        return False

    monkeypatch.setattr(identity_preview_mod, "_session_seam", _session)
    monkeypatch.setattr(identity_preview_mod, "_mapping_seam", _mapping)
    monkeypatch.setattr(identity_preview_mod, "_alias_seam", _alias)
    monkeypatch.setattr(identity_preview_mod, "_suppression_seam", _suppressed)

    body = IdentityPreviewBody(
        identity_fields=[
            IdentityFieldProbe(field="customer_id", value="CUST-123", index=0),
            IdentityFieldProbe(field="first_name", value="Ada", index=1),
        ]
    )
    result = await routes_mod.preview_identity("imp_idp_1", body=body, request=_Request())
    assert result["import_id"] == "imp_idp_1"
    assert result["summary"]["total"] == 2
    by_field = {d["field"]: d for d in result["decisions"]}
    # customer_id is mapped as an identifier and matched once -> deterministic link
    assert by_field["customer_id"]["decision"] == "link"
    assert by_field["customer_id"]["tier"] == "deterministic"
    # first_name is not mapped as an identifier -> noop, never classified
    assert by_field["first_name"]["decision"] == "noop"
    assert by_field["first_name"]["confidence"] == 0.0
    # decisions are the frozen {field,index,value,decision,confidence[,tier]} rows —
    # the internal per-probe ``reason`` is deliberately not serialized.


@pytest.mark.asyncio
async def test_identity_preview_external_id_hash_matches_canonical() -> None:
    """The preview hashes ``external_id`` exactly as canonical extraction does.

    Canonical ingestion (``services/identity/signals.py``) hashes the
    *tenant-scoped* key ``"{tenant_id}:{raw}"`` for EXTERNAL_ID.  The preview
    must hash the same input, or its ``find_subjects_by_alias`` lookup can never
    match an alias the resolver actually stored (it would report a false
    ``create`` for every existing external_id).
    """
    from services.identity.hashing import hash_external_id
    from services.identity.models import IdentitySignalType
    from services.identity.normalization import normalize_external_id

    raw, tenant = "CUST-123", "tnt_hash_a"
    preview_hash = identity_preview_mod._hash_probe(
        IdentitySignalType.EXTERNAL_ID, raw, tenant
    )
    canonical_hash = hash_external_id(normalize_external_id(raw, tenant), tenant)
    assert preview_hash == canonical_hash
    # Regression guard: hashing the raw (un-prefixed) value is the old bug and
    # would diverge from the canonical stored alias.
    assert preview_hash != hash_external_id(raw, tenant)
    assert preview_hash


@pytest.mark.asyncio
async def test_preview_graph_pins_mapping_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_gr_1")

    async def _canonical_preview(tenant_id: str, import_id: str) -> dict:
        return {"vertices": [], "edges": [], "stats": {"vertices": 0}}

    async def _latest_mapping(tenant_id: str, import_id: str) -> dict:
        return {"version": 3}

    monkeypatch.setattr(graph_preview_mod, "_canonical_graph_preview", _canonical_preview)
    monkeypatch.setattr(graph_preview_mod, "_latest_mapping_seam", _latest_mapping)

    ok = await routes_mod.preview_graph(
        "imp_gr_1",
        request=_Request(),
        body=routes_mod.MappingVersionBody(mapping_version=3),
    )
    assert ok["import_id"] == "imp_gr_1"
    assert ok["mapping_version"] == 3
    assert ok["stats"] == {"vertices": 0}

    # Pinning a stale version is refused (ConflictError), never served quietly.
    with pytest.raises(ConflictError):
        await routes_mod.preview_graph(
            "imp_gr_1",
            request=_Request(),
            body=routes_mod.MappingVersionBody(mapping_version=2),
        )


# ── POST /imports/{import_id}/commit ────────────────────────────────────────


class _FakeImportsRepo:
    def __init__(self, status: str) -> None:
        self._status = status

    async def get_session(self, tenant_id: str, import_id: str) -> dict:
        return _canonical_session(import_id, status=self._status)


class _FakeJobsService:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str, dict]] = []

    async def enqueue(
        self,
        tenant_id: str,
        job_type: str,
        payload: dict,
        *,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> dict:
        self.enqueued.append((tenant_id, job_type, payload))
        return {"id": "job_de_1", "type": job_type}


@pytest.mark.asyncio
async def test_commit_requires_approval_then_enqueues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await _seed_envelope_import(monkeypatch, "imp_commit_1")
    canonical_id = created["canonical_id"]
    artifact_id = created["artifact_id"]

    monkeypatch.setattr(
        routes_mod, "get_imports_repository", lambda: _FakeImportsRepo(status="approved")
    )
    jobs = _FakeJobsService()
    monkeypatch.setattr(jobs_svc_mod, "get_jobs_service", lambda: jobs)

    result = await routes_mod.commit_import("imp_commit_1", request=_Request())
    assert result == {
        "import_id": "imp_commit_1",
        "job_id": "job_de_1",
        "status": "processing",
    }
    assert jobs.enqueued == [(TENANT, "import.commit", {"import_id": canonical_id})]
    marker = await ARTIFACT_REPO.get(TENANT, artifact_id)
    assert marker["status"] == "processing"


@pytest.mark.asyncio
async def test_commit_refuses_unapproved_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _seed_envelope_import(monkeypatch, "imp_commit_2")
    monkeypatch.setattr(
        routes_mod, "get_imports_repository", lambda: _FakeImportsRepo(status="mapped")
    )
    with pytest.raises(ConflictError):
        await routes_mod.commit_import("imp_commit_2", request=_Request())


# ── POST /imports/{import_id}/analyze ───────────────────────────────────────


@pytest.mark.asyncio
async def test_analyze_updates_marker_on_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await _seed_envelope_import(monkeypatch, "imp_an_1")
    artifact_id = created["artifact_id"]

    async def _fake_analyze(tenant_id: str, import_id: str) -> dict:
        return {"import_id": import_id, "schemas": [{"columns": []}], "row_count": 0}

    monkeypatch.setattr(imports_svc_mod, "analyze_import", _fake_analyze)
    result = await routes_mod.analyze_import("imp_an_1", request=_Request())
    # payload is translated into the envelope namespace
    assert result["import_id"] == "imp_an_1"
    assert (await ARTIFACT_REPO.get(TENANT, artifact_id))["status"] == "ready"

    async def _boom(tenant_id: str, import_id: str) -> dict:
        raise RuntimeError("analyze exploded")

    monkeypatch.setattr(imports_svc_mod, "analyze_import", _boom)
    with pytest.raises(RuntimeError):
        await routes_mod.analyze_import("imp_an_1", request=_Request())
    # marker was backed off to uploaded so it never pins in 'analyzing'
    assert (await ARTIFACT_REPO.get(TENANT, artifact_id))["status"] == "uploaded"


# ── POST /imports/{import_id}/rollback ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_proxies_and_tombstones_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await _seed_envelope_import(monkeypatch, "imp_rb_1")
    artifact_id = created["artifact_id"]

    async def _fake_rollback(
        tenant_id: str,
        import_id: str,
        *,
        commit_id: Optional[str] = None,
        reason: str = "operator rollback",
    ) -> dict:
        return {"import_id": import_id, "commit_id": "impc_rolled_back_1"}

    monkeypatch.setattr(imports_commit_mod, "rollback_import", _fake_rollback)
    result = await routes_mod.rollback_import(
        "imp_rb_1",
        body=routes_mod.RollbackBody(reason="bad data"),
        request=_Request(),
    )
    assert result == {"import_id": "imp_rb_1", "rolled_back_commit_id": "impc_rolled_back_1"}
    marker = await ARTIFACT_REPO.get(TENANT, artifact_id)
    assert marker["status"] == "revoked"


# ── status vocabulary helpers ───────────────────────────────────────────────


def test_envelope_status_from_canonical_mapping() -> None:
    assert routes_mod._envelope_status_from_canonical("created") == "created"
    assert routes_mod._envelope_status_from_canonical("committing") == "processing"
    assert routes_mod._envelope_status_from_canonical("committed") == "committed"
    assert routes_mod._envelope_status_from_canonical("cancelled") == "deleted"
    assert routes_mod._envelope_status_from_canonical("rolled_back") == "revoked"
    assert routes_mod._envelope_status_from_canonical("mapped") == "ready"
    # unknown canonical statuses degrade to the coarse envelope default
    assert routes_mod._envelope_status_from_canonical("weird_future_state") == "created"
