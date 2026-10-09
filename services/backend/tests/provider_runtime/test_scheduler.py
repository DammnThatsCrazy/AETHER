"""Tests for the pull scheduler (open-run → fetch → raw store → normalize → bridge →
advance cursor → complete_run → meter). Fakes conform to the REAL Team A/D seams:
plugin protocol, AdapterResult/ReadBatch envelopes, RawProviderRecordStore,
EventBridge, SyncRunService, CredentialBroker, ProviderConnectionRepository."""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import SecretStr

from repositories.repos import reset_in_memory_stores
from services.comms.sync_runs import SyncRun
from services.provider_runtime.connection import (
    ProviderConnection,
    ProviderConnectionRepository,
)
from services.provider_runtime.errors import ProviderNotInstalled, ProviderPullFailed
from services.provider_runtime.scheduler import ProviderCursorRepository, PullScheduler
from shared.credentials.types import ApiKeyWebhookSecretCredential
from shared.integration_contracts.events import ReadBatch, make_aether_event, make_raw_record
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.results import AdapterResult, AdapterStatus, RateLimitInfo

IDENTITY = "shopify.orders.catalog"


# ── Protocol-conforming fakes (Team C owns the real plugin; these match its surface) ──


class FakeRegistry:
    def __init__(self, plugins: dict[str, Any]) -> None:
        self._plugins = dict(plugins)

    def get(self, identity_key: str) -> Any:
        return self._plugins.get(identity_key)


class FakeBroker:
    def __init__(self, credential: Any = None) -> None:
        self.credential = credential
        self.reveals: list[tuple[str, str]] = []

    async def reveal(self, tenant_id: str, ref: str) -> Any:
        self.reveals.append((tenant_id, ref))
        return self.credential


class FakeRawStore:
    """Matches RawProviderRecordStore.ingest(iterable) / count(*, tenant_id, ...)."""

    def __init__(self) -> None:
        self.records: list[Any] = []
        self._seen: set[tuple] = set()

    async def ingest(self, records, *, tenant_id=None) -> list[tuple[Any, bool]]:
        outcomes = []
        for record in records:
            effective_tenant = tenant_id if tenant_id is not None else record.tenant_id
            key = (
                effective_tenant,
                record.provider_identity,
                record.provider_record_id,
                record.schema_version,
            )
            was_new = key not in self._seen
            self._seen.add(key)
            self.records.append(record)
            outcomes.append((record, was_new))
        return outcomes

    async def ingest_with_admission(self, records, *, tenant_id=None):
        """The scheduler fake explicitly models a Bronze-admitted fixture."""
        outcomes = await self.ingest(records, tenant_id=tenant_id)
        return [(*outcome, True, "test_verified_admission") for outcome in outcomes]

    async def count(self, *, tenant_id, provider_identity, provider_record_type=None) -> int:
        return sum(
            1
            for r in self.records
            if r.tenant_id == tenant_id
            and r.provider_identity == provider_identity
            and (provider_record_type is None or r.provider_record_type == provider_record_type)
        )


class FakeBridge:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def ingest_events(self, tenant_id: str, events) -> int:
        self.events.extend(events)
        return len(events)


class FakeNormalizer:
    def normalize(self, record):
        return NormalizationResult(
            events=[
                make_aether_event(
                    provider_identity=record.provider_identity,
                    event_type="commerce.order.created",
                    event_family="commerce",
                    tenant_id=record.tenant_id,
                    source_record_id=record.record_id,
                    data={"record_id": record.provider_record_id},
                    context={"acquisition_mode": record.acquisition_mode},
                )
            ],
            skipped=0,
            dropped=[],
            normalizer_version="1",
        )


class FakePlugin:
    def __init__(
        self,
        *,
        pull: Any = None,
        normalizer: Any = None,
    ) -> None:
        self._pull = pull
        self._normalizer = normalizer

    def pull(self) -> Any:
        return self._pull

    def normalizer(self) -> Any:
        return self._normalizer


class FakePull:
    """Returns results in order, staying on the last result forever after."""

    def __init__(self, results: list[AdapterResult[Any]]) -> None:
        self._results = list(results)
        self._index = 0
        self.calls: list[dict[str, Any]] = []

    async def fetch(self, context, cursor=None, limit=None):
        self.calls.append({"cursor": cursor, "limit": limit, "context": context})
        if not self._results:
            return AdapterResult.ok(ReadBatch(records=[], next_cursor=None, has_more=False))
        i = min(self._index, len(self._results) - 1)
        self._index += 1
        return self._results[i]


class FakeRunService:
    """Matches SyncRunService.open_run / complete_run signatures (real SyncRun model)."""

    def __init__(self) -> None:
        self.opened: list[SyncRun] = []
        self.completed: list[SyncRun] = []

    async def open_run(self, **kwargs) -> SyncRun:
        run = SyncRun(**kwargs)
        self.opened.append(run)
        return run

    async def complete_run(
        self,
        run: SyncRun,
        *,
        status,
        cursor_after=None,
        counts=None,
        safe_error_code=None,
        safe_error_detail=None,
        reconciliation_status=None,
    ) -> SyncRun:
        run.status = status
        if cursor_after is not None:
            run.cursor_after = cursor_after
        run.safe_error_code = safe_error_code
        run.safe_error_detail = (safe_error_detail or "")[:500] or None
        if reconciliation_status is not None:
            run.reconciliation_status = reconciliation_status
        for key, value in (counts or {}).items():
            if hasattr(run, key) and isinstance(value, int):
                setattr(run, key, value)
        self.completed.append(run)
        return run


class FakeMeter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    async def __call__(self, tenant_id: str, event_type: str, source_id: str, source_type: str) -> None:
        self.calls.append((tenant_id, event_type, source_id, source_type))


# ── Builders ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_stores():
    """Real BaseRepository-backed repos share the in-memory table dicts."""
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def make_connection(
    *,
    tenant_id: str = "tenant-1",
    connection_id: str = "conn_1",
    provider_identity: str = IDENTITY,
    credential_ref: str = "provider:tenant-1:shopify.orders.catalog",
    selected_accounts: tuple[str, ...] = ("acc_1",),
    config: Optional[dict[str, Any]] = None,
) -> ProviderConnection:
    return ProviderConnection(
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_identity=provider_identity,
        state=ConnectionState.CONNECTED,
        credential_ref=credential_ref,
        selected_accounts=list(selected_accounts),
        config=config or {},
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


def make_record(*, record_id: str, provider_record_type: str = "order", **overrides) -> Any:
    return make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id=record_id,
        provider_record_type=provider_record_type,
        payload={"id": record_id},
        tenant_id="tenant-1",
        connection_id="conn_1",
        acquisition_mode="poll",
        **overrides,
    )


def build_scheduler(
    *,
    plugin: Any,
    raw_store: Any = None,
    bridge: Any = None,
    broker: Any = None,
    connections: Any = None,
    sync_runs: Any = None,
    meters: Any = None,
) -> PullScheduler:
    return PullScheduler(
        registry=FakeRegistry({IDENTITY: plugin}),
        raw_store=raw_store or FakeRawStore(),
        bridge=bridge or FakeBridge(),
        broker=broker or FakeBroker(),
        connections=connections or ProviderConnectionRepository(),
        sync_runs=sync_runs or FakeRunService(),
        meters=meters or FakeMeter(),
    )


# ── Success path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_success_advances_cursor_closes_run_and_meters():
    pull = FakePull([
        AdapterResult.ok(ReadBatch(
            records=[make_record(record_id="o1")], next_cursor="c2", has_more=True,
        )),
        AdapterResult.ok(ReadBatch(
            records=[make_record(record_id="o2")], next_cursor=None, has_more=False,
        )),
    ])
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    meter = FakeMeter()
    run_svc = FakeRunService()
    connections = ProviderConnectionRepository()
    connection = make_connection()
    await connections.upsert(connection)

    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=raw_store, bridge=bridge, meters=meter,
        sync_runs=run_svc, connections=connections,
    )
    result = await scheduler.run_sync(connection)

    assert result.status == "completed"
    assert result.records_received == 2
    assert result.facts_written == 2
    assert run_svc.opened[0].mode == "backfill"
    # cursor advanced to the last page's next_cursor
    cursor = await ProviderCursorRepository().get_cursor(
        "tenant-1", "conn_1", IDENTITY,
    )
    assert cursor is not None
    assert cursor["cursor_value"] == "c2"
    # raw records landed before normalization, events bridged
    assert await raw_store.count(tenant_id="tenant-1", provider_identity=IDENTITY) == 2
    assert len(bridge.events) == 2
    # connection success timestamp persisted
    persisted = await connections.find("conn_1")
    assert persisted is not None
    assert persisted.last_successful_sync_at is not None
    # metered exactly once with the spec'd event type
    assert meter.calls == [
        ("tenant-1", "provider.sync.completed", "conn_1", "provider_runtime")
    ]


@pytest.mark.asyncio
async def test_shopify_backfill_entrypoint_captures_hashed_unresolved_customer_evidence():
    from services.comms.sync_runs import SyncRunRepository, SyncRunService
    from services.identity.hashing import hash_value
    from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from services.identity.repository import IdentityResolutionRepository
    from services.identity.source_identity_registry import SourceIdentityRegistry
    from services.identity.provider_evidence_anchors import ProviderIdentityEvidenceAnchorRepository

    record = make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id="order-771",
        provider_record_type="order",
        payload={
            "id": "order-771",
            "customer": {"id": 771, "email": "backfill@example.com", "phone": "+14155550771"},
        },
        acquisition_mode="poll",
    )
    raw_store = FakeRawStore()
    sync_runs = SyncRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=FakePull([AdapterResult.ok(ReadBatch(records=[record]))]),
            normalizer=FakeNormalizer(),
        ),
        raw_store=raw_store,
        sync_runs=sync_runs,
    )

    await scheduler.run_sync(make_connection(selected_accounts=("shop-77",)))

    assert raw_store.records[0].tenant_id == "tenant-1"
    assert raw_store.records[0].connection_id == "conn_1"
    assert raw_store.records[0].account_id == "shop-77"
    source = await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        "tenant-1", "shopify:shop-77:conn_1", external_id="771",
    )
    assert source is not None and source.status == "unresolved"
    assert source.canonical_entity_id
    provisional_subject = await IdentityResolutionRepository().get_subject_by_canonical_entity_id(
        "tenant-1", source.canonical_entity_id
    )
    assert provisional_subject["metadata"]["identity_state"] == "provisional"
    assert provisional_subject["metadata"]["source_identity_id"] == source.id
    claims = await IdentityResolutionRepository().get_claims_for_source(source.id)
    by_type = {claim["claim_type"]: claim for claim in claims}
    assert by_type["email"]["normalized_value"] == hash_value(
        "backfill@example.com", scope="email:tenant-1",
    )
    assert by_type["phone"]["normalized_value"] == hash_value(
        "+14155550771", scope="phone:tenant-1",
    )
    assert by_type["email"]["raw_value"] is None
    assert by_type["phone"]["raw_value"] is None
    assert by_type["external_customer_id"]["raw_value"] == "771"
    assert all(claim["source_record_id"] == "order-771" for claim in claims)
    candidate_adapter = ImportIdentityCandidateAdapter(IdentityResolutionRepository())
    candidate = await candidate_adapter.evaluate(
        tenant_id="tenant-1", claims={"email": "backfill@example.com"},
    )
    assert candidate.outcome == "candidate"
    assert candidate.candidate_source_identity_ids == [source.id]
    email_claim = by_type["email"]
    assert email_claim["provider_raw_checksum"] == record.checksum
    assert email_claim["provider_raw_schema_version"] == record.schema_version
    # Candidate evaluation verifies that claim provenance still agrees with
    # the durable lifecycle anchor; mismatched checksum/version fails closed.
    await IdentityResolutionRepository().update_claim_provider_provenance(
        "tenant-1", email_claim["id"], raw_checksum="mismatch",
        raw_schema_version=record.schema_version,
    )
    tampered_candidate = await candidate_adapter.evaluate(
        tenant_id="tenant-1", claims={"email": "backfill@example.com"},
    )
    assert tampered_candidate.outcome == "no_match"
    await IdentityResolutionRepository().update_claim_provider_provenance(
        "tenant-1", email_claim["id"], raw_checksum=record.checksum,
        raw_schema_version=record.schema_version,
    )
    completed_runs = await SyncRunRepository().list_for_connector(
        "tenant-1", "conn_1", limit=10,
    )
    assert len(completed_runs) == 1 and completed_runs[0]["status"] == "completed"

    # A retry of the same raw row is a dedupe hit, so the existing completed
    # anchor remains current and the source evidence stays idempotent.
    replay_scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=FakePull([AdapterResult.ok(ReadBatch(records=[record]))]),
            normalizer=FakeNormalizer(),
        ),
        raw_store=raw_store,
        sync_runs=SyncRunService(),
    )
    await replay_scheduler.run_sync(make_connection(selected_accounts=("shop-77",)))
    replay_candidate = await candidate_adapter.evaluate(
        tenant_id="tenant-1", claims={"email": "backfill@example.com"},
    )
    assert replay_candidate.outcome == "candidate"
    assert len(await IdentityResolutionRepository().get_claims_for_source(source.id)) == 3

    # Tenant scope is part of the claim hash and anchor lookup.
    cross_tenant = await candidate_adapter.evaluate(
        tenant_id="tenant-other", claims={"email": "backfill@example.com"},
    )
    assert cross_tenant.outcome == "no_match"

    current_anchor = await ProviderIdentityEvidenceAnchorRepository().find_by_id(
        ProviderIdentityEvidenceAnchorRepository._id("tenant-1", claims[0]["id"]),
    )
    assert current_anchor is not None
    await SyncRunService().rollback_run(
        tenant_id="tenant-1", sync_run_id=current_anchor["lifecycle_id"],
    )
    rolled_back = await candidate_adapter.evaluate(
        tenant_id="tenant-1", claims={"email": "backfill@example.com"},
    )
    assert rolled_back.outcome == "no_match"


@pytest.mark.asyncio
async def test_failed_provider_sync_never_exposes_pending_identity_evidence():
    from services.comms.sync_runs import SyncRunService
    from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from services.identity.repository import IdentityResolutionRepository
    from shared.integration_contracts.results import AdapterStatus

    record = make_raw_record(
        provider_identity=IDENTITY,
        provider_record_id="order-fail-1",
        provider_record_type="order",
        payload={"id": "order-fail-1", "customer": {"id": 772, "email": "failed@example.com"}},
        acquisition_mode="poll",
    )
    pull = FakePull([
        AdapterResult.ok(ReadBatch(records=[record], next_cursor="next", has_more=True)),
        AdapterResult(
            success=False, status=AdapterStatus.PERMANENT_ERROR,
            error_code="provider_test_failure", retryable=False,
        ),
    ])
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=FakeRawStore(),
        sync_runs=SyncRunService(),
    )
    with pytest.raises(ProviderPullFailed):
        await scheduler.run_sync(make_connection())

    decision = await ImportIdentityCandidateAdapter(IdentityResolutionRepository()).evaluate(
        tenant_id="tenant-1", claims={"email": "failed@example.com"},
    )
    assert decision.outcome == "no_match"


@pytest.mark.asyncio
async def test_run_alias_is_d_ee_compatible():
    """Team D's ConnectionOrchestrator calls PullScheduler().run(connection=..., since=...)."""
    pull = FakePull([AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()), sync_runs=run_svc,
    )
    result = await scheduler.run(
        connection=make_connection(), since="2026-01-01T00:00:00+00:00",
    )
    assert result.status == "completed"
    assert run_svc.opened[0].mode == "incremental"
    assert run_svc.opened[0].requested_window == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_sync_resumes_from_prior_cursor():
    await ProviderCursorRepository().set_cursor(
        "tenant-1", "conn_1", IDENTITY, cursor_value="c9", event_count=0,
    )
    pull = FakePull([AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))])
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
    )
    await scheduler.run_sync(make_connection())
    assert pull.calls[0]["cursor"] == "c9"


@pytest.mark.asyncio
async def test_sync_zero_records_is_a_success():
    """An empty provider response is success — it is NOT a silent failure."""
    pull = FakePull([AdapterResult.ok(ReadBatch(
        records=[], next_cursor=None, has_more=False,
    ))])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()), sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.records_received == 0


@pytest.mark.asyncio
async def test_sync_passes_credential_into_context():
    cred = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("sk_live_abc"), webhook_secret=SecretStr("whsec_abc"),
    )
    pull = FakePull([AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))])
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        broker=FakeBroker(credential=cred),
    )
    connection = make_connection()
    await scheduler.run_sync(connection)
    ctx = pull.calls[0]["context"]
    assert ctx.tenant_id == "tenant-1"
    assert ctx.credential.api_key.get_secret_value() == "sk_live_abc"
    assert ctx.account_id == "acc_1"
    assert ctx.config == {}


# ── Retry path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_rate_limited_then_recovers():
    rate_limited = AdapterResult(
        success=False, status=AdapterStatus.RATE_LIMITED, error_code="rate_limited",
        rate_limit=RateLimitInfo(retry_after_ms=1.0),
    )
    ok = AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))
    pull = FakePull([rate_limited, ok])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()), sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.retry_count == 1
    assert result.rate_limit_events == 1
    assert len(pull.calls) == 2  # original attempt + one retry


@pytest.mark.asyncio
async def test_sync_retryable_error_then_recovers():
    retryable = AdapterResult(
        success=False, status=AdapterStatus.RETRYABLE_ERROR, error_code="temporary",
    )
    ok = AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))
    pull = FakePull([retryable, ok])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()), sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_sync_rate_limited_after_retries_fails_typed():
    rate_limited = AdapterResult(
        success=False, status=AdapterStatus.RATE_LIMITED, error_code="rate_limited",
        rate_limit=RateLimitInfo(retry_after_ms=1.0),
    )
    pull = FakePull([rate_limited])  # never clears
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()), sync_runs=run_svc,
    )
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_rate_limited"
    assert run_svc.completed[0].status == "failed"
    assert run_svc.completed[0].safe_error_code == "provider_rate_limited"
    assert run_svc.completed[0].retry_count == 3  # MAX_RETRIES


# ── Failure paths (never a silent empty success) ────────────────────────────


@pytest.mark.asyncio
async def test_sync_unauthorized_fails_run_with_typed_error():
    unauthorized = AdapterResult(
        success=False, status=AdapterStatus.UNAUTHORIZED, error_code="auth_failed",
    )
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=FakePull([unauthorized]), normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_unauthorized"
    assert run_svc.completed[0].status == "failed"
    assert run_svc.completed[0].safe_error_code == "provider_unauthorized"
    assert run_svc.completed[0].safe_error_detail


@pytest.mark.asyncio
async def test_sync_permanent_error_fails_run():
    permanent = AdapterResult(
        success=False, status=AdapterStatus.PERMANENT_ERROR, error_code="bad_shape",
    )
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=FakePull([permanent]), normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_permanent_error"
    assert run_svc.completed[0].status == "failed"


@pytest.mark.asyncio
async def test_sync_provider_without_pull_capability_fails():
    plugin = FakePlugin(pull=None, normalizer=FakeNormalizer())
    scheduler = build_scheduler(plugin=plugin)
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_pull_not_supported"


@pytest.mark.asyncio
async def test_sync_missing_plugin_raises_provider_not_installed():
    scheduler = PullScheduler(
        registry=FakeRegistry({}), raw_store=FakeRawStore(), bridge=FakeBridge(),
        broker=FakeBroker(), connections=ProviderConnectionRepository(),
        sync_runs=FakeRunService(), meters=FakeMeter(),
    )
    with pytest.raises(ProviderNotInstalled):
        await scheduler.run_sync(make_connection())


@pytest.mark.asyncio
async def test_sync_page_cap_defensive():
    """A provider that never clears has_more is aborted, not looped forever."""
    always_more = AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o")], next_cursor="again", has_more=True,
    ))
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=FakePull([always_more]), normalizer=FakeNormalizer()),
    )
    scheduler.MAX_PAGES = 5  # shrink the defensive cap for the test
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_pull_failed"
    assert "has_more" in exc_info.value.details["detail"]


@pytest.mark.asyncio
async def test_sync_adapter_exception_fails_run_typed():
    """An untyped adapter exception is a provider failure: the ledger closes as
    FAILED with a typed error — never a silent empty success nor a hung run."""

    class ThrowingPull:
        async def fetch(self, context, cursor=None, limit=None):
            raise RuntimeError("provider exploded")

    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=ThrowingPull(), normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())
    assert exc_info.value.details["error_code"] == "provider_pull_failed"
    assert "provider exploded" in exc_info.value.details["detail"]
    assert run_svc.completed[0].status == "failed"
    assert run_svc.completed[0].safe_error_code == "provider_pull_failed"


@pytest.mark.asyncio
async def test_sync_default_path_persists_connection_success():
    """With no injected connections repo (the real PullScheduler() path Team D
    constructs), last_successful_sync_at is still persisted to the store."""
    pull = FakePull([AdapterResult.ok(ReadBatch(
        records=[make_record(record_id="o1")], next_cursor=None, has_more=False,
    ))])
    scheduler = PullScheduler(
        registry=FakeRegistry({
            IDENTITY: FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        }),
        raw_store=FakeRawStore(),
        bridge=FakeBridge(),
        broker=FakeBroker(),
        sync_runs=FakeRunService(),
        meters=FakeMeter(),
        # NOTE: connections intentionally NOT injected — exercises the lazy default.
    )
    await scheduler.run_sync(make_connection())
    persisted = await ProviderConnectionRepository().find("conn_1")
    assert persisted is not None
    assert persisted.last_successful_sync_at is not None
