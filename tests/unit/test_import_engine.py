"""Tenant Import Engine — end-to-end through service + repos + route handlers.

Proves the ingest → analyze → map → validate → approve lifecycle is durable and
evidence-backed: uploaded bytes carry a checksum, a schema profile is stored per
file, a validation result is persisted, a governance-sensitive mapping forces a
review before approval, and every read is tenant-scoped.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from contextlib import contextmanager  # noqa: E402

from services.imports import service as svc  # noqa: E402


@contextmanager
def raises_named(*names: str):
    """Assert an exception whose class NAME is one of ``names`` is raised.

    Matching by name (not identity) makes these tests immune to the suite's
    ``sys.modules`` churn: another test file can pop/re-import
    ``shared.common.common``, giving the exception raised inside a lazily
    imported module a different class object than one imported at the top of
    this file — a class-identity check would then spuriously fail.
    """
    with pytest.raises(Exception) as excinfo:  # noqa: PT011
        yield excinfo
    got = type(excinfo.value).__name__
    assert got in names, f"expected one of {names}, got {got}: {excinfo.value}"


TENANT = "tenant-imports"
OTHER = "tenant-other"

CSV = (
    b"email,amount,event\n"
    b"Alice@Example.com,10.5,purchase\n"
    b"bob@example.com,20,purchase\n"
    b"carol@example.com,5,refund\n"
)

# A mapping over the sample: email -> identifier.value (governance-sensitive),
# amount -> metric.value, event -> action.action_type.
MAPPING = [
    {"source_column": "email", "primitive": "identifier", "target_field": "value",
     "transform": "lowercase", "required": True},
    {"source_column": "amount", "primitive": "metric", "target_field": "value",
     "transform": "to_number", "required": True},
    {"source_column": "event", "primitive": "action", "target_field": "action_type",
     "transform": "trim", "required": True},
]


@pytest.fixture()
def clean():
    """Clear the in-memory stores the singletons share, per test."""
    from repositories.import_files import get_import_file_repository
    from repositories.imports_repo import get_imports_repository

    r = get_imports_repository()
    for attr in ("sessions", "schemas", "mappings", "templates", "validations", "row_errors"):
        getattr(r, attr)._store.clear()
    get_import_file_repository()._store.clear()
    return r


async def _seed_analyzed(import_id: str | None = None) -> str:
    session = await svc.create_import(TENANT, created_by="u1")
    import_id = session["id"]
    await svc.store_file(
        TENANT, import_id, filename="data.csv", content=CSV, content_type="text/csv"
    )
    await svc.analyze_import(TENANT, import_id)
    return import_id


# ── lifecycle ────────────────────────────────────────────────────────────────


async def test_create_and_get(clean):
    session = await svc.create_import(TENANT, created_by="u1")
    assert session["status"] == "created"
    detail = await svc.get_import(TENANT, session["id"])
    assert detail["session"]["id"] == session["id"]
    assert detail["files"] == []


async def test_upload_stores_checksum_and_advances(clean):
    session = await svc.create_import(TENANT)
    stored = await svc.store_file(
        TENANT, session["id"], filename="data.csv", content=CSV, content_type="text/csv"
    )
    assert stored["sha256"] and stored["size_bytes"] == len(CSV)
    assert stored["format"] == "csv"
    detail = await svc.get_import(TENANT, session["id"])
    assert detail["session"]["status"] == "uploaded"
    assert detail["session"]["file_count"] == 1


async def test_upload_rejects_unsupported_format(clean):
    session = await svc.create_import(TENANT)
    xlsx = b"PK\x03\x04" + b"\x00" * 64  # zip/xlsx magic
    with raises_named("BadRequestError"):
        await svc.store_file(
            TENANT, session["id"], filename="book.xlsx",
            content=xlsx, content_type="application/vnd.ms-excel",
        )


async def test_upload_rejects_oversize(clean):
    session = await svc.create_import(TENANT)
    with raises_named("BadRequestError"):
        await svc.store_file(
            TENANT, session["id"], filename="big.csv", content=b"x" * 32,
            content_type="text/csv", max_bytes=16,
        )


async def test_analyze_profiles_columns(clean):
    import_id = await _seed_analyzed()
    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "analyzed"
    profile = detail["schemas"][0]
    names = {c["name"] for c in profile["columns"]}
    assert {"email", "amount", "event"} <= names
    email_col = next(c for c in profile["columns"] if c["name"] == "email")
    assert email_col["sensitivity"] in {"identifier", "pii"}


async def test_map_validate_governs_and_approves(clean):
    import_id = await _seed_analyzed()
    await svc.set_mapping(TENANT, import_id, MAPPING)
    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "mapped"

    outcome = await svc.validate_import(TENANT, import_id)
    # The mapping touches the identifier primitive → governance review required.
    assert outcome["status"] == "review_required"
    assert outcome["validation"]["ok"] is True
    assert outcome["validation"]["rows_valid"] == 3
    assert outcome["review_reasons"]

    approved = await svc.approve_import(TENANT, import_id, approver="admin1")
    assert approved["status"] == "approved"


async def test_validate_requires_mapping(clean):
    import_id = await _seed_analyzed()
    with raises_named("BadRequestError"):
        await svc.validate_import(TENANT, import_id)


async def test_approve_requires_passing_validation(clean):
    import_id = await _seed_analyzed()
    # A required mapping that fails on a bad transform target so validation !ok.
    bad = [
        {"source_column": "event", "primitive": "metric", "target_field": "value",
         "transform": "to_number", "required": True},
    ]
    await svc.set_mapping(TENANT, import_id, bad)
    outcome = await svc.validate_import(TENANT, import_id)
    assert outcome["validation"]["ok"] is False
    with raises_named("ConflictError"):
        await svc.approve_import(TENANT, import_id)


async def test_cancel_is_terminal(clean):
    session = await svc.create_import(TENANT)
    await svc.cancel_import(TENANT, session["id"])
    detail = await svc.get_import(TENANT, session["id"])
    assert detail["session"]["status"] == "cancelled"
    # No further transitions once terminal.
    with raises_named("ConflictError"):
        await svc.analyze_import(TENANT, session["id"])


# ── tenant isolation ─────────────────────────────────────────────────────────


async def test_tenant_isolation(clean):
    session = await svc.create_import(TENANT)
    with raises_named("NotFoundError"):
        await svc.get_import(OTHER, session["id"])
    with raises_named("NotFoundError"):
        await svc.analyze_import(OTHER, session["id"])


# ── templates ────────────────────────────────────────────────────────────────


async def test_template_create_apply_suggest(clean):
    import_id = await _seed_analyzed()
    tmpl = await svc.create_template(
        TENANT, name="orders", fields=MAPPING, column_names=["email", "amount", "event"]
    )
    assert tmpl["header_signature"]

    suggest = await svc.suggest_templates(TENANT, import_id)
    assert suggest["matched"] == tmpl["id"]

    await svc.apply_template(TENANT, import_id, tmpl["id"])
    detail = await svc.get_import(TENANT, import_id)
    assert detail["session"]["status"] == "mapped"
    assert len(detail["mapping"]["fields"]) == 3


async def test_templates_are_tenant_scoped(clean):
    await svc.create_template(
        TENANT, name="orders", fields=MAPPING, column_names=["email", "amount", "event"]
    )
    assert await svc.list_templates(OTHER) == []


# ── route handlers (tenant scoping surface) ──────────────────────────────────


class _Tenant:
    def __init__(self, tid=TENANT):
        self.tenant_id = tid
        self.user_id = "u1"
        self.plan_tier = "pro"

    def require_permission(self, _perm):  # noqa: ANN001
        return True

    def has_permission(self, _perm):  # noqa: ANN001
        return True


class _Req:
    def __init__(self, tid=TENANT):
        self.state = type("S", (), {})()
        self.state.tenant = _Tenant(tid)
        self.state.request_id = "corr-1"


async def test_route_create_and_list(clean):
    from services.imports.routes import create_import, list_imports

    created = await create_import(_Req())
    assert created["status"] == "created"
    body = await list_imports(_Req(), limit=50, offset=0)
    assert body["count"] == 1
    # Another tenant sees none of it.
    other = await list_imports(_Req(OTHER), limit=50, offset=0)
    assert other["count"] == 0
