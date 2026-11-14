"""Ingestion V2 — typed Bronze + transactional outbox + /v1/batch V2 (PR 5).

Exercises the correctness core (``ingestion.ingestion.bronze_bulk.ingest_many``)
and the flag-gated V2 route branch in ``ingestion.ingestion.batch`` under
AETHER_ENV=local (in-memory backend, no asyncpg/Redis):

  * all-new events accepted
  * all-duplicate events reported duplicate (DB uniqueness, not Redis)
  * mixed new/duplicate
  * repeated ids WITHIN one request de-duplicated (first wins)
  * same event_id across two tenants  → BOTH accepted
  * same event_id across two schema_versions → BOTH accepted
  * simulated transaction failure rolls back BOTH Bronze and outbox
  * result ordering preserved (input order)
  * outbox rows written only for accepted events
  * V2 route path (flag ON) returns the exact BatchResponse schema
  * V1 and V2 return the same response keys/statuses for the same input
  * V1 and V2 attach equivalent gateway-stamped SDK envelopes when enabled
  * flag OFF uses V1 (does not call ingest_many)

Robust to suite ordering: every test evicts and re-imports the backend modules
so a single consistent generation of config.settings / repositories.repos is
used, resets the in-memory stores, and flips ``settings.ingestion_v2`` on the
LIVE singleton (which the route reads at call time).
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "api"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = (
    "config", "tenancy", "ingestion", "identity", "graph", "journeys", "intelligence", "value", "actions", "governance", "workers", "connectors", "replay", "billing", "shared", "middleware", "dependencies", "repositories",
)


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


class _Backend:
    """Freshly-imported, mutually-consistent backend module handle."""

    def __init__(self, **iv2_overrides):
        _evict_backend()
        self.settings_mod = importlib.import_module("config.settings")
        self.repos = importlib.import_module("repositories.repos")
        self.repos.reset_in_memory_stores()
        self.bulk = importlib.import_module("ingestion.ingestion.bronze_bulk")
        self.batch = importlib.import_module("ingestion.ingestion.batch")
        self.settings = self.settings_mod.settings
        if iv2_overrides:
            object.__setattr__(
                self.settings,
                "ingestion_v2",
                dataclasses.replace(self.settings.ingestion_v2, **iv2_overrides),
            )

    @property
    def bronze_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})

    @property
    def outbox_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("event_outbox", {})


@contextmanager
def fresh(**iv2_overrides):
    b = _Backend(**iv2_overrides)
    try:
        yield b
    finally:
        _evict_backend()


def _run(coro):
    return asyncio.run(coro)


# ── Builders ─────────────────────────────────────────────────────────────────

def _mk_event(bulk, *, tenant="t1", event_id="e1", schema="1.0.0", topic="aether.sdk.events.validated"):
    payload = {"event_id": event_id, "tenant_id": tenant, "properties": {"k": "v"}}
    rec = bulk.BronzeSDKEvent(
        tenant_id=tenant,
        event_id=event_id,
        schema_version=schema,
        batch_id="batch-1",
        event_type="track",
        event_family="core",
        event_timestamp="2026-07-24T00:00:00Z",
        received_at="2026-07-24T00:00:01Z",
        session_id="s1",
        anonymous_id="anon1",
        user_id=None,
        entity_id="anon1",
        payload=payload,
        source="sdk",
        source_tag="batch:batch-1",
    )
    ob = bulk.OutboxEvent(
        tenant_id=tenant,
        event_id=event_id,
        topic=topic,
        partition_key="anon1",
        payload=payload,
    )
    return rec, ob


def _many(bulk, specs):
    """specs: list of dicts of kwargs for _mk_event. Returns (records, outbox)."""
    recs, obs = [], []
    for spec in specs:
        r, o = _mk_event(bulk, **spec)
        recs.append(r)
        obs.append(o)
    return recs, obs


# ── ingest_many core ─────────────────────────────────────────────────────────

def test_all_new_accepted():
    with fresh() as b:
        recs, obs = _many(b.bulk, [{"event_id": f"e{i}"} for i in range(4)])
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["accepted"] * 4
        assert res.accepted_count == 4
        assert res.duplicate_count == 0
        assert len(b.bronze_store) == 4
        assert len(b.outbox_store) == 4


def test_all_duplicate_second_call():
    with fresh() as b:
        recs, obs = _many(b.bulk, [{"event_id": f"e{i}"} for i in range(3)])
        _run(b.bulk.ingest_many(recs, obs))
        # Re-ingest the same batch — DB uniqueness marks every one duplicate.
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["duplicate"] * 3
        assert res.accepted_count == 0
        assert res.duplicate_count == 3
        assert len(b.bronze_store) == 3  # unchanged
        assert len(b.outbox_store) == 3  # no new outbox rows


def test_mixed_new_and_duplicate():
    with fresh() as b:
        first, first_obs = _many(b.bulk, [{"event_id": "e1"}, {"event_id": "e2"}])
        _run(b.bulk.ingest_many(first, first_obs))
        recs, obs = _many(
            b.bulk, [{"event_id": "e2"}, {"event_id": "e3"}, {"event_id": "e1"}]
        )
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["duplicate", "accepted", "duplicate"]
        assert len(b.bronze_store) == 3  # e1, e2, e3
        # Outbox only for the newly accepted e3.
        assert len(b.outbox_store) == 3  # e1,e2 from first call + e3 now


def test_repeated_ids_within_request_deduped():
    with fresh() as b:
        recs, obs = _many(
            b.bulk, [{"event_id": "e1"}, {"event_id": "e1"}, {"event_id": "e2"}]
        )
        res = _run(b.bulk.ingest_many(recs, obs))
        # First occurrence wins; the intra-request repeat is a duplicate.
        assert res.statuses == ["accepted", "duplicate", "accepted"]
        assert res.accepted_count == 2
        assert len(b.bronze_store) == 2
        assert len(b.outbox_store) == 2


def test_same_event_id_two_tenants_both_accepted():
    with fresh() as b:
        recs, obs = _many(
            b.bulk, [{"tenant": "tA", "event_id": "same"}, {"tenant": "tB", "event_id": "same"}]
        )
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["accepted", "accepted"]
        assert len(b.bronze_store) == 2


def test_same_event_id_two_schema_versions_both_accepted():
    with fresh() as b:
        recs, obs = _many(
            b.bulk, [{"event_id": "same", "schema": "1.0.0"}, {"event_id": "same", "schema": "2.0.0"}]
        )
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["accepted", "accepted"]
        assert res.accepted_count == 2
        assert len(b.bronze_store) == 2


def test_ordering_preserved():
    with fresh() as b:
        # Seed e2 so it is a cross-request duplicate; interleave.
        seed, seed_obs = _many(b.bulk, [{"event_id": "e2"}])
        _run(b.bulk.ingest_many(seed, seed_obs))
        recs, obs = _many(
            b.bulk,
            [{"event_id": "e0"}, {"event_id": "e2"}, {"event_id": "e1"}, {"event_id": "e2"}],
        )
        res = _run(b.bulk.ingest_many(recs, obs))
        # e0 new, e2 dup(cross-request), e1 new, e2 dup(intra-request)
        assert res.statuses == ["accepted", "duplicate", "accepted", "duplicate"]


def test_transaction_rollback_persists_nothing():
    with fresh() as b:
        recs, obs = _many(b.bulk, [{"event_id": "e1"}, {"event_id": "e2"}])

        def _boom():
            raise RuntimeError("simulated mid-commit failure")

        b.bulk._commit_hook = _boom  # inject failure between bronze + outbox apply
        with pytest.raises(RuntimeError):
            _run(b.bulk.ingest_many(recs, obs))
        # BOTH Bronze and outbox rolled back — nothing persisted.
        assert len(b.bronze_store) == 0
        assert len(b.outbox_store) == 0


def test_outbox_only_for_accepted():
    with fresh() as b:
        first, first_obs = _many(b.bulk, [{"event_id": "e1"}])
        _run(b.bulk.ingest_many(first, first_obs))
        outbox_after_first = dict(b.outbox_store)
        # e1 duplicate, e2 accepted → only e2 adds an outbox row.
        recs, obs = _many(b.bulk, [{"event_id": "e1"}, {"event_id": "e2"}])
        res = _run(b.bulk.ingest_many(recs, obs))
        assert res.statuses == ["duplicate", "accepted"]
        assert len(b.outbox_store) == len(outbox_after_first) + 1


# ── Route: V2 dispatch ───────────────────────────────────────────────────────

class _FakeTenant:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    def require_permission(self, _perm):
        return None


class _FakeState:
    pass


class _FakeRequest:
    def __init__(self, tenant):
        self.state = _FakeState()
        self.state.tenant = tenant


class _FakeProducer:
    def __init__(self):
        self.published = []

    async def publish_batch(self, events):
        self.published.extend(events)


def _mk_body(batch_mod, event_ids, event_type=None):
    from ingestion.ingestion.generated_registry import SDK_EMITTABLE_EVENT_TYPES

    # Only SDK-emittable types are accepted from clients; pick one deterministically.
    et = event_type or sorted(SDK_EMITTABLE_EVENT_TYPES & set(batch_mod.CANONICAL_EVENT_TYPES))[0]
    events = [
        batch_mod.BaseEvent(
            id=eid,
            type=et,
            timestamp="2026-07-24T00:00:00Z",
            sessionId="s1",
            anonymousId="anon1",
        )
        for eid in event_ids
    ]
    return batch_mod.BatchRequest(batch=events, sentAt="2026-07-24T00:00:00Z")


def _patch_v1_deps(batch_mod):
    """Neutralize V1's identity-resolution side effects for a clean route run."""
    async def _noop(*_a, **_kw):
        return None

    batch_mod._resolve_identity_safe = _noop
    batch_mod.get_identity_resolver = lambda: None


def _enable_observation_envelope(backend):
    """Turn on the existing additive Envelope-B flags for one route run."""
    object.__setattr__(
        backend.settings,
        "observation_envelope",
        dataclasses.replace(backend.settings.observation_envelope, enabled=True),
    )
    object.__setattr__(
        backend.settings,
        "ingress_gateway",
        dataclasses.replace(backend.settings.ingress_gateway, enabled=True),
    )


def test_observation_envelope_is_omitted_when_adoption_flag_is_off():
    with fresh() as b:
        object.__setattr__(
            b.settings,
            "observation_envelope",
            dataclasses.replace(b.settings.observation_envelope, enabled=False),
        )
        object.__setattr__(
            b.settings,
            "ingress_gateway",
            dataclasses.replace(b.settings.ingress_gateway, enabled=True),
        )
        normalized = {"event_id": "legacy", "event_type": "track"}
        original = dict(normalized)

        b.batch._attach_observation_envelope(
            normalized, batch_id="batch-1", tenant_id="tenant-x"
        )

        assert normalized == original


def _stable_envelope_fields(payload):
    """Drop request-time stamps while retaining the shared envelope contract."""
    envelope = payload["observation_envelope"]
    observation = envelope["observation"]
    return {
        "observation": {
            "observation_id": observation["observation_id"],
            "observation_type": observation["observation_type"],
            "family": observation["family"],
            "schema_version": observation["schema_version"],
            "occurred_at": observation["occurred_at"],
        },
        "tenancy": envelope["tenancy"],
        "source": envelope["source"],
        "subjects": envelope["subjects"],
        "correlation": envelope.get("correlation"),
        "temporal": envelope.get("temporal"),
        "provenance": envelope.get("provenance"),
        "quality": envelope.get("quality"),
    }


def test_v2_route_accepts_and_returns_batchresponse_schema():
    with fresh(enabled=True) as b:
        tenant = _FakeTenant("tenant-x")
        req = _FakeRequest(tenant)
        body = _mk_body(b.batch, ["e1", "e2", "e3"])
        resp = _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))
        assert set(resp.keys()) == {
            "accepted", "duplicates", "rejected", "events", "batchId", "receivedAt",
            "requestId", "usageEventId", "usageEvidenceId", "auditEventId",
            "consentReceiptIds",
        }
        assert resp["accepted"] == 3
        assert resp["duplicates"] == 0
        assert resp["rejected"] == 0
        assert [e["status"] for e in resp["events"]] == ["accepted"] * 3
        # Went through the transactional path → typed Bronze + outbox populated.
        assert len(b.bronze_store) == 3
        assert len(b.outbox_store) == 3


def test_v2_route_audit_reference_joins_request_and_batch():
    with fresh(enabled=True) as b:
        tenant = _FakeTenant("tenant-audit")
        req = _FakeRequest(tenant)
        req.state.context = SimpleNamespace(
            tenant_id="tenant-audit", correlation_id="req-audit-join"
        )
        security_context = importlib.import_module("governance.security.request_context")
        security_context.bind_current_request(req)
        try:
            response = _run(
                b.batch.ingest_batch(
                    req,
                    _mk_body(b.batch, ["audit-join-event"]),
                    producer=_FakeProducer(),
                )
            )
        finally:
            security_context.bind_current_request(None)

        audit_rows = b.repos._IN_MEMORY_STORES["security_audit_events"]
        audit = audit_rows[response["auditEventId"]]
        assert response["auditEventId"].startswith("audit_")
        assert audit["event_type"] == "ingestion.batch"
        assert audit["actor_type"] == "system"
        assert audit["actor_id"] == "aether_ingestion"
        assert audit["resource_id"] == response["batchId"]
        assert audit["correlation_id"] == "req-audit-join"
        assert audit["metadata"]["accepted_count"] == 1


def test_v2_batch_joins_meter_audit_and_authoritative_consent_evidence(monkeypatch):
    with fresh(enabled=True) as b:
        object.__setattr__(
            b.settings,
            "consent_authority",
            dataclasses.replace(
                b.settings.consent_authority,
                authoritative_consent_enforcement_enabled=True,
            ),
        )
        _enable_observation_envelope(b)
        consent = importlib.import_module("governance.consent.authority")
        _run(consent.ConsentReceiptRepository().record(
            "receipt-route-proof", "tenant-proof", "analytics", "granted",
            subject_id="user-proof",
        ))

        body = _mk_body(b.batch, ["correlated-event"], event_type="track")
        body.consents = ["analytics"]
        body.batch[0] = body.batch[0].model_copy(update={
            "userId": "user-proof",
            "context": b.batch.EventContext(consent={"analytics": True}),
        })
        request_id = "req-route-correlation-proof"
        tenant = _FakeTenant("tenant-proof")
        tenant.user_id = "user-proof"
        request = _FakeRequest(tenant)
        request.state.request_id = request_id
        request.state.context = SimpleNamespace(
            tenant_id="tenant-proof", correlation_id=request_id
        )

        meter_calls = []

        async def meter(*_args, **kwargs):
            meter_calls.append(kwargs)
            return SimpleNamespace(
                metered_event_id="usage-event-proof",
                evidence_id="usage-evidence-proof",
            )

        monkeypatch.setattr(b.batch, "meter_family_usage", meter)
        security_context = importlib.import_module("governance.security.request_context")
        security_context.bind_current_request(request)
        try:
            response = _run(
                b.batch.ingest_batch(request, body, producer=_FakeProducer())
            )
        finally:
            security_context.bind_current_request(None)

        assert response["accepted"] == 1
        assert response["requestId"] == request_id
        assert response["usageEventId"] == "usage-event-proof"
        assert response["usageEvidenceId"] == "usage-evidence-proof"
        assert meter_calls[0]["metadata"] == {"correlation_id": request_id}

        audit = b.repos._IN_MEMORY_STORES["security_audit_events"][response["auditEventId"]]
        assert audit["resource_id"] == response["batchId"]
        assert audit["correlation_id"] == request_id
        assert audit["metadata"]["usage_event_id"] == response["usageEventId"]
        assert audit["metadata"]["usage_evidence_id"] == response["usageEvidenceId"]

        bronze = next(iter(b.bronze_store.values()))
        assert bronze["payload"]["observation_envelope"]["privacy"]["consent_snapshot"] == "receipt-route-proof"


def test_v2_route_dedupes_repeated_ids_in_request():
    with fresh(enabled=True) as b:
        tenant = _FakeTenant("tenant-x")
        req = _FakeRequest(tenant)
        body = _mk_body(b.batch, ["dup", "dup", "unique"])
        resp = _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))
        statuses = [e["status"] for e in resp["events"]]
        assert statuses == ["accepted", "duplicate", "accepted"]
        assert resp["accepted"] == 2
        assert resp["duplicates"] == 1


def test_v2_canary_tenant_routes_to_v2():
    with fresh(enabled=False, canary_tenants=["canary-t"]) as b:
        called = {"v2": False}
        real = b.bulk.ingest_many

        async def _spy(recs, obs):
            called["v2"] = True
            return await real(recs, obs)

        b.batch.ingest_many = _spy

        # Non-canary tenant → V1 (spy not called).
        _patch_v1_deps(b.batch)
        req = _FakeRequest(_FakeTenant("other"))
        body = _mk_body(b.batch, ["e1"])
        _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))
        assert called["v2"] is False

        # Canary tenant → V2 (spy called).
        req2 = _FakeRequest(_FakeTenant("canary-t"))
        body2 = _mk_body(b.batch, ["e1"])
        _run(b.batch.ingest_batch(req2, body2, producer=_FakeProducer()))
        assert called["v2"] is True


def test_flag_off_uses_v1_not_ingest_many():
    with fresh(enabled=False) as b:
        called = {"v2": False}

        async def _spy(recs, obs):
            called["v2"] = True
            raise AssertionError("V2 must not run when the flag is off")

        b.batch.ingest_many = _spy
        _patch_v1_deps(b.batch)

        req = _FakeRequest(_FakeTenant("tenant-x"))
        body = _mk_body(b.batch, ["e1", "e2"])
        resp = _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))
        assert called["v2"] is False
        assert set(resp.keys()) == {
            "accepted", "duplicates", "rejected", "events", "batchId", "receivedAt",
            "requestId", "usageEventId", "usageEvidenceId", "auditEventId",
            "consentReceiptIds",
        }
        assert resp["accepted"] == 2


def test_v1_and_v2_same_response_schema_and_statuses():
    # V2 run.
    with fresh(enabled=True) as b:
        req = _FakeRequest(_FakeTenant("tenant-x"))
        body = _mk_body(b.batch, ["e1", "e2", "e3"])
        v2_resp = _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))

    # V1 run (fresh backend, flag OFF).
    with fresh(enabled=False) as b:
        _patch_v1_deps(b.batch)
        req = _FakeRequest(_FakeTenant("tenant-x"))
        body = _mk_body(b.batch, ["e1", "e2", "e3"])
        v1_resp = _run(b.batch.ingest_batch(req, body, producer=_FakeProducer()))

    assert set(v1_resp.keys()) == set(v2_resp.keys())
    assert [e["status"] for e in v1_resp["events"]] == [e["status"] for e in v2_resp["events"]]
    assert v1_resp["accepted"] == v2_resp["accepted"] == 3
    # Per-event result objects share the same shape.
    for e1, e2 in zip(v1_resp["events"], v2_resp["events"]):
        assert set(e1.keys()) == set(e2.keys())


def test_v1_and_v2_attach_equivalent_gateway_stamped_sdk_envelopes():
    # V1 writes its published payload; V2 writes the same normalized payload to
    # its transactional outbox. Compare stable Envelope-B fields because each
    # request intentionally receives distinct server timestamps and batch ids.
    with fresh(enabled=False) as b:
        _enable_observation_envelope(b)
        _patch_v1_deps(b.batch)
        producer = _FakeProducer()
        body = _mk_body(b.batch, ["envelope-parity"], event_type="track")
        body.consents = ["analytics"]
        response = _run(
            b.batch.ingest_batch(
                _FakeRequest(_FakeTenant("tenant-x")), body, producer=producer
            )
        )
        assert response["accepted"] == 1
        assert len(producer.published) == 1
        v1_envelope = _stable_envelope_fields(producer.published[0].payload)

    with fresh(enabled=True) as b:
        _enable_observation_envelope(b)
        persisted = {}
        real_ingest_many = b.batch.ingest_many

        async def _capture_outbox(records, outbox_events):
            assert len(records) == len(outbox_events) == 1
            persisted["envelope"] = _stable_envelope_fields(records[0].payload)
            persisted["outbox_envelope"] = _stable_envelope_fields(
                outbox_events[0].payload
            )
            return await real_ingest_many(records, outbox_events)

        b.batch.ingest_many = _capture_outbox
        body = _mk_body(b.batch, ["envelope-parity"], event_type="track")
        body.consents = ["analytics"]
        response = _run(
            b.batch.ingest_batch(
                _FakeRequest(_FakeTenant("tenant-x")), body, producer=_FakeProducer()
            )
        )
        assert response["accepted"] == 1

    assert persisted["envelope"] == v1_envelope
    assert persisted["outbox_envelope"] == v1_envelope
    assert persisted["envelope"]["provenance"]["credential_class"] == "PUBLIC_CLIENT"
    assert persisted["envelope"]["quality"]["validation_state"] == "gateway:accepted"


def test_v1_and_v2_stamp_credential_platform_and_namespace_on_sdk_source():
    tenant = _FakeTenant("tenant-x")
    tenant.credential_platform = "ios"
    sources = []
    with fresh(enabled=False) as b:
        _enable_observation_envelope(b)
        _patch_v1_deps(b.batch)
        producer = _FakeProducer()
        body = _mk_body(b.batch, ["source-v1"], event_type="track")
        body.consents = ["analytics"]
        _run(b.batch.ingest_batch(_FakeRequest(tenant), body, producer=producer))
        sources.append(producer.published[0].payload["observation_envelope"]["source"])

    with fresh(enabled=True) as b:
        _enable_observation_envelope(b)
        real_ingest_many = b.batch.ingest_many

        async def _capture(records, outbox_events):
            sources.append(records[0].payload["observation_envelope"]["source"])
            return await real_ingest_many(records, outbox_events)

        b.batch.ingest_many = _capture
        body = _mk_body(b.batch, ["source-v2"], event_type="track")
        body.consents = ["analytics"]
        _run(b.batch.ingest_batch(_FakeRequest(tenant), body, producer=_FakeProducer()))

    assert len(sources) == 2
    for source in sources:
        assert source["source_type"] == "sdk"
        assert source["source_relationship"] == "first_party_application"
        assert source["source_provider"] == "ios"
        assert source["source_instance"] == "tenant:tenant-x"
