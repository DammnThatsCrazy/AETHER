"""Tests for the pull scheduler (open-run → fetch → raw store → normalize → bridge →
advance cursor → complete_run → meter). Fakes conform to the REAL Team A/D seams:
plugin protocol, AdapterResult/ReadBatch envelopes, RawProviderRecordStore,
EventBridge, SyncRunService, CredentialBroker, ProviderConnectionRepository."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

import pytest
from pydantic import SecretStr

import repositories.repos as repos
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from journeys.comms.sync_runs import SyncRun
from connectors.provider_runtime.connection import (
    ProviderConnection,
    ProviderConnectionRepository,
)
from connectors.provider_runtime.acquisition import (
    ProviderAccountRecord,
    ProviderAccountRepository,
)
from connectors.provider_runtime.errors import (
    ConnectionStateViolation,
    ProviderNotInstalled,
    ProviderPullFailed,
)
from connectors.provider_runtime.raw_store import RawProviderRecordStore
from connectors.provider_runtime.scheduler import ProviderCursorRepository, PullScheduler
from shared.credentials.types import ApiKeyWebhookSecretCredential
from shared.integration_contracts.events import ReadBatch, make_aether_event, make_raw_record
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.manifest import ConfigFieldSpec
from shared.integration_contracts.normalization import NormalizationResult
from shared.integration_contracts.results import AdapterResult, AdapterStatus, RateLimitInfo
from shared.integration_contracts.streams import StreamDescriptor
from shared.privacy.classification import DataClassification

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

    async def count(self, *, tenant_id, provider_identity, provider_record_type=None) -> int:
        return sum(
            1
            for r in self.records
            if r.tenant_id == tenant_id
            and r.provider_identity == provider_identity
            and (provider_record_type is None or r.provider_record_type == provider_record_type)
        )


class WrongAccountRawStore(FakeRawStore):
    async def ingest(self, records, *, tenant_id=None):
        return [
            (record.model_copy(update={"account_id": "unselected-account"}), True)
            for record in records
        ]


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
        manifest: Any = None,
    ) -> None:
        self._pull = pull
        self._normalizer = normalizer
        self._manifest = manifest

    def pull(self) -> Any:
        return self._pull

    def normalizer(self) -> Any:
        return self._normalizer

    def manifest(self) -> Any:
        return self._manifest


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


class StateObservingPull(FakePull):
    def __init__(self, results, *, connection, connections):
        super().__init__(results)
        self.connection = connection
        self.connections = connections
        self.observed_states: list[tuple[ConnectionState, ConnectionState]] = []

    async def fetch(self, context, cursor=None, limit=None):
        persisted = await self.connections.find(self.connection.connection_id)
        self.observed_states.append((self.connection.state, persisted.state))
        return await super().fetch(context, cursor=cursor, limit=limit)


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

    async def __call__(
        self, tenant_id: str, event_type: str, source_id: str, source_type: str
    ) -> None:
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
    state: ConnectionState = ConnectionState.CONNECTED,
) -> ProviderConnection:
    return ProviderConnection(
        connection_id=connection_id,
        tenant_id=tenant_id,
        provider_identity=provider_identity,
        state=state,
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


def make_stream(
    stream_id: str,
    *,
    enabled_by_default: bool = True,
    activation_config_field: Optional[str] = None,
    activation_config_value: Optional[str] = None,
    acquisition_modes: tuple[str, ...] = ("pull",),
) -> StreamDescriptor:
    pullable = "pull" in acquisition_modes
    return StreamDescriptor(
        stream_id=stream_id,
        object_kind="order",
        domain_pack="commerce",
        acquisition_modes=acquisition_modes,
        output_contract="order.updated",
        source_authority_class="commerce_order",
        data_classification=DataClassification.SENSITIVE_PII,
        initial_backfill=pullable,
        incremental=pullable,
        cursor_scheme=f"{stream_id}-cursor-v1" if pullable else None,
        enabled_by_default=enabled_by_default,
        activation_config_field=activation_config_field,
        activation_config_value=activation_config_value,
    )


def make_stream_manifest(
    *streams: StreamDescriptor,
    selection_required: bool = False,
    config_fields: tuple[ConfigFieldSpec, ...] = (),
) -> Any:
    return SimpleNamespace(
        streams=list(streams),
        accounts=SimpleNamespace(selection_required=selection_required),
        configuration=SimpleNamespace(fields=list(config_fields)),
    )


def build_scheduler(
    *,
    plugin: Any,
    provider_identity: str = IDENTITY,
    raw_store: Any = None,
    bridge: Any = None,
    broker: Any = None,
    connections: Any = None,
    cursors: Any = None,
    sync_runs: Any = None,
    meters: Any = None,
    accounts: Any = None,
) -> PullScheduler:
    return PullScheduler(
        registry=FakeRegistry({provider_identity: plugin}),
        raw_store=raw_store or FakeRawStore(),
        bridge=bridge or FakeBridge(),
        broker=broker or FakeBroker(),
        connections=connections or ProviderConnectionRepository(),
        cursors=cursors,
        sync_runs=sync_runs or FakeRunService(),
        meters=meters or FakeMeter(),
        accounts=accounts,
    )


# ── Success path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_success_advances_cursor_closes_run_and_meters():
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor="c2",
                    has_more=True,
                )
            ),
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o2")],
                    next_cursor=None,
                    has_more=False,
                )
            ),
        ]
    )
    raw_store = FakeRawStore()
    bridge = FakeBridge()
    meter = FakeMeter()
    run_svc = FakeRunService()
    connections = ProviderConnectionRepository()
    connection = make_connection()
    await connections.upsert(connection)

    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=raw_store,
        bridge=bridge,
        meters=meter,
        sync_runs=run_svc,
        connections=connections,
    )
    result = await scheduler.run_sync(connection)

    assert result.status == "completed"
    assert result.records_received == 2
    assert result.facts_written == 2
    assert run_svc.opened[0].mode == "backfill"
    # cursor advanced to the last page's next_cursor
    cursor = await ProviderCursorRepository().get_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
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
    assert meter.calls == [("tenant-1", "provider.sync.completed", "conn_1", "provider_runtime")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        ConnectionState.AVAILABLE,
        ConnectionState.VERIFIED,
        ConnectionState.ACCOUNT_SELECTION_REQUIRED,
        ConnectionState.REAUTHORIZATION_REQUIRED,
        ConnectionState.DISABLED,
    ],
)
async def test_manual_sync_rejects_ineligible_lifecycle_states_before_provider_work(state):
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    broker = FakeBroker()
    run_service = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        broker=broker,
        sync_runs=run_service,
    )

    with pytest.raises(ConnectionStateViolation) as excinfo:
        await scheduler.run_sync(make_connection(state=state))

    assert excinfo.value.details["state"] == state.value
    assert pull.calls == []
    assert broker.reveals == []
    assert run_service.opened == []


@pytest.mark.asyncio
async def test_initial_streamless_sync_persists_running_before_pull_then_connected():
    connections = ProviderConnectionRepository()
    connection = make_connection(state=ConnectionState.INITIAL_SYNC_PENDING)
    await connections.upsert(connection)
    pull = StateObservingPull(
        [AdapterResult.ok(ReadBatch(records=[], has_more=False))],
        connection=connection,
        connections=connections,
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        connections=connections,
    )

    result = await scheduler.run_sync(connection)

    assert result.status == "completed"
    assert pull.observed_states == [
        (ConnectionState.INITIAL_SYNC_RUNNING, ConnectionState.INITIAL_SYNC_RUNNING)
    ]
    persisted = await connections.find(connection.connection_id)
    assert persisted.state == ConnectionState.CONNECTED
    assert persisted.last_successful_sync_at is not None


@pytest.mark.asyncio
async def test_initial_sync_failure_persists_sync_failed():
    connections = ProviderConnectionRepository()
    connection = make_connection(state=ConnectionState.INITIAL_SYNC_PENDING)
    await connections.upsert(connection)
    unauthorized = AdapterResult(
        success=False,
        status=AdapterStatus.UNAUTHORIZED,
        error_code="auth_failed",
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=FakePull([unauthorized]), normalizer=FakeNormalizer()),
        connections=connections,
    )

    with pytest.raises(ProviderPullFailed):
        await scheduler.run_sync(connection)

    persisted = await connections.find(connection.connection_id)
    assert connection.state == ConnectionState.SYNC_FAILED
    assert persisted.state == ConnectionState.SYNC_FAILED


@pytest.mark.asyncio
async def test_declared_streams_keep_initial_sync_running_until_all_streams_finish():
    connections = ProviderConnectionRepository()
    connection = make_connection(
        selected_accounts=("account-a",),
        state=ConnectionState.INITIAL_SYNC_PENDING,
    )
    await connections.upsert(connection)
    pull = StateObservingPull(
        [
            AdapterResult.ok(ReadBatch(records=[], has_more=False)),
            AdapterResult.ok(ReadBatch(records=[], has_more=False)),
        ],
        connection=connection,
        connections=connections,
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(make_stream("orders"), make_stream("refunds")),
        ),
        connections=connections,
    )

    result = await scheduler.run_sync(connection)

    assert result["status"] == "completed"
    assert pull.observed_states == [
        (ConnectionState.INITIAL_SYNC_RUNNING, ConnectionState.INITIAL_SYNC_RUNNING),
        (ConnectionState.INITIAL_SYNC_RUNNING, ConnectionState.INITIAL_SYNC_RUNNING),
    ]
    assert (await connections.find(connection.connection_id)).state == ConnectionState.CONNECTED


@pytest.mark.asyncio
async def test_shopify_backfill_entrypoint_captures_hashed_unresolved_customer_evidence():
    from journeys.comms.sync_runs import SyncRunRepository, SyncRunService
    from identity.identity.hashing import hash_value
    from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from identity.identity.repository import IdentityResolutionRepository
    from identity.identity.source_identity_registry import SourceIdentityRegistry
    from identity.identity.provider_evidence_anchors import ProviderIdentityEvidenceAnchorRepository

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
    assert "backfill@example.com" not in repr(claims)
    assert "+14155550771" not in repr(claims)
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
    from journeys.comms.sync_runs import SyncRunService
    from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from identity.identity.repository import IdentityResolutionRepository
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
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor=None,
                    has_more=False,
                )
            )
        ]
    )
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    result = await scheduler.run(
        connection=make_connection(),
        since="2026-01-01T00:00:00+00:00",
    )
    assert result.status == "completed"
    assert run_svc.opened[0].mode == "incremental"
    assert run_svc.opened[0].requested_window == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_sync_resumes_from_prior_cursor():
    await ProviderCursorRepository().set_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
        cursor_value="c9",
        event_count=0,
    )
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor=None,
                    has_more=False,
                )
            )
        ]
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
    )
    await scheduler.run_sync(make_connection())
    assert pull.calls[0]["cursor"] == "c9"


@pytest.mark.asyncio
async def test_sync_zero_records_is_a_success():
    """An empty provider response is success — it is NOT a silent failure."""
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[],
                    next_cursor=None,
                    has_more=False,
                )
            )
        ]
    )
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.records_received == 0


@pytest.mark.asyncio
async def test_sync_passes_credential_into_context():
    cred = ApiKeyWebhookSecretCredential(
        api_key=SecretStr("sk_live_abc"),
        webhook_secret=SecretStr("whsec_abc"),
    )
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor=None,
                    has_more=False,
                )
            )
        ]
    )
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


@pytest.mark.asyncio
async def test_graphql_sync_binds_persisted_shop_gid_and_realm_before_fetch():
    identity = "shopify.admin.orders_read"
    selected_id = "shop:myshop.myshopify.com"
    persisted_gid = "gid://shopify/Shop/123"
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], next_cursor=None, has_more=False))])
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    connection = make_connection(
        provider_identity=identity,
        selected_accounts=(selected_id,),
        config={
            "orders_api": "graphql",
            "source_account_realm": "test",
            "_verified_shop_gid": "gid://shopify/Shop/999",  # caller config is never authority
        },
    )
    connection.last_verified_at = "2026-10-03T00:00:00+00:00"
    await connections.upsert(connection)
    await accounts.upsert(
        ProviderAccountRecord(
            account_id=f"{connection.connection_id}:{selected_id}",
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            provider_identity=identity,
            external_id=persisted_gid,
            metadata={"shop_gid": persisted_gid, "source_account_realm": "test"},
        )
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        provider_identity=identity,
        connections=connections,
        accounts=accounts,
    )

    result = await scheduler.run_sync(connection)

    assert result.status == "completed"
    assert len(pull.calls) == 1
    context = pull.calls[0]["context"]
    assert context.account_id == selected_id
    assert context.config["source_account_realm"] == "test"
    assert context.config["_verified_shop_gid"] == persisted_gid
    assert context.config["_verified_shop_gid"] != "gid://shopify/Shop/999"


@pytest.mark.asyncio
async def test_graphql_sync_rejects_persisted_shop_from_different_realm_before_fetch():
    identity = "shopify.admin.orders_read"
    selected_id = "shop:myshop.myshopify.com"
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], next_cursor=None, has_more=False))])
    run_svc = FakeRunService()
    connections = ProviderConnectionRepository()
    accounts = ProviderAccountRepository()
    connection = make_connection(
        provider_identity=identity,
        selected_accounts=(selected_id,),
        config={"orders_api": "graphql", "source_account_realm": "live"},
    )
    connection.last_verified_at = "2026-10-03T00:00:00+00:00"
    await connections.upsert(connection)
    await accounts.upsert(
        ProviderAccountRecord(
            account_id=f"{connection.connection_id}:{selected_id}",
            tenant_id=connection.tenant_id,
            connection_id=connection.connection_id,
            provider_identity=identity,
            external_id="gid://shopify/Shop/123",
            metadata={
                "shop_gid": "gid://shopify/Shop/123",
                "source_account_realm": "test",
            },
        )
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        provider_identity=identity,
        connections=connections,
        accounts=accounts,
        sync_runs=run_svc,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(connection)

    assert exc_info.value.details["error_code"] == "provider_account_unverified"
    assert pull.calls == []
    assert run_svc.completed[0].safe_error_code == "provider_account_unverified"


# ── Retry path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_rate_limited_then_recovers():
    rate_limited = AdapterResult(
        success=False,
        status=AdapterStatus.RATE_LIMITED,
        error_code="rate_limited",
        rate_limit=RateLimitInfo(retry_after_ms=1.0),
    )
    ok = AdapterResult.ok(
        ReadBatch(
            records=[make_record(record_id="o1")],
            next_cursor=None,
            has_more=False,
        )
    )
    pull = FakePull([rate_limited, ok])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.retry_count == 1
    assert result.rate_limit_events == 1
    assert len(pull.calls) == 2  # original attempt + one retry


@pytest.mark.asyncio
async def test_sync_retryable_error_then_recovers():
    retryable = AdapterResult(
        success=False,
        status=AdapterStatus.RETRYABLE_ERROR,
        error_code="temporary",
    )
    ok = AdapterResult.ok(
        ReadBatch(
            records=[make_record(record_id="o1")],
            next_cursor=None,
            has_more=False,
        )
    )
    pull = FakePull([retryable, ok])
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        sync_runs=run_svc,
    )
    result = await scheduler.run_sync(make_connection())
    assert result.status == "completed"
    assert result.retry_count == 1


@pytest.mark.asyncio
async def test_sync_rate_limited_after_retries_fails_typed():
    rate_limited = AdapterResult(
        success=False,
        status=AdapterStatus.RATE_LIMITED,
        error_code="rate_limited",
        rate_limit=RateLimitInfo(retry_after_ms=1.0),
    )
    pull = FakePull([rate_limited])  # never clears
    run_svc = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        sync_runs=run_svc,
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
        success=False,
        status=AdapterStatus.UNAUTHORIZED,
        error_code="auth_failed",
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
        success=False,
        status=AdapterStatus.PERMANENT_ERROR,
        error_code="bad_shape",
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
        registry=FakeRegistry({}),
        raw_store=FakeRawStore(),
        bridge=FakeBridge(),
        broker=FakeBroker(),
        connections=ProviderConnectionRepository(),
        sync_runs=FakeRunService(),
        meters=FakeMeter(),
    )
    with pytest.raises(ProviderNotInstalled):
        await scheduler.run_sync(make_connection())


@pytest.mark.asyncio
async def test_sync_page_cap_defensive():
    """A provider that never clears has_more is aborted, not looped forever."""
    always_more = AdapterResult.ok(
        ReadBatch(
            records=[make_record(record_id="o")],
            next_cursor="again",
            has_more=True,
        )
    )
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
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor=None,
                    has_more=False,
                )
            )
        ]
    )
    scheduler = PullScheduler(
        registry=FakeRegistry(
            {
                IDENTITY: FakePlugin(pull=pull, normalizer=FakeNormalizer()),
            }
        ),
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


@pytest.mark.asyncio
async def test_raw_persistence_failure_blocks_normalization_bridge_and_cursor():
    class FailingRawStore(FakeRawStore):
        async def ingest(self, records, *, tenant_id=None):
            raise RuntimeError("database unavailable")

    class CountingNormalizer(FakeNormalizer):
        calls = 0

        def normalize(self, record):
            self.calls += 1
            return super().normalize(record)

    normalizer = CountingNormalizer()
    bridge = FakeBridge()
    run_svc = FakeRunService()
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor="c2",
                    has_more=False,
                )
            )
        ]
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=normalizer),
        raw_store=FailingRawStore(),
        bridge=bridge,
        sync_runs=run_svc,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())

    assert exc_info.value.details["error_code"] == "provider_raw_persist_failed"
    assert normalizer.calls == 0
    assert bridge.events == []
    assert run_svc.completed[0].status == "failed"
    assert await ProviderCursorRepository().get_cursor("tenant-1", "conn_1", IDENTITY) is None


@pytest.mark.asyncio
async def test_missing_rights_blocks_raw_persistence_normalization_bridge_and_cursor(monkeypatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)

    class CountingNormalizer(FakeNormalizer):
        def __init__(self):
            self.calls = 0

        def normalize(self, record):
            self.calls += 1
            return super().normalize(record)

    normalizer = CountingNormalizer()
    bridge = FakeBridge()
    run_svc = FakeRunService()
    cursors = ProviderCursorRepository()
    await cursors.set_cursor(
        "tenant-1", "conn_1", IDENTITY, "cursor-before-quarantine"
    )
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="quarantined-order")],
                    next_cursor="cursor-after-quarantine",
                    has_more=False,
                )
            )
        ]
    )
    raw_store = RawProviderRecordStore()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=normalizer),
        raw_store=raw_store,
        bridge=bridge,
        cursors=cursors,
        sync_runs=run_svc,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())

    assert exc_info.value.details["error_code"] == "provider_raw_persist_failed"
    assert exc_info.value.details["detail"] == "ProviderRawRightsDenied"
    assert normalizer.calls == 0
    assert bridge.events == []
    assert run_svc.completed[0].status == "failed"
    cursor = await cursors.get_cursor("tenant-1", "conn_1", IDENTITY)
    assert cursor is not None
    assert cursor["cursor_value"] == "cursor-before-quarantine"
    rows = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-1", "source": IDENTITY}, limit=10
    )
    assert rows == []


@pytest.mark.asyncio
async def test_event_persistence_failure_does_not_advance_cursor():
    class FailingBridge(FakeBridge):
        async def ingest_events(self, tenant_id, events):
            raise RuntimeError("event lake unavailable")

    run_svc = FakeRunService()
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1")],
                    next_cursor="c2",
                    has_more=False,
                )
            )
        ]
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        bridge=FailingBridge(),
        sync_runs=run_svc,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(make_connection())

    assert exc_info.value.details["error_code"] == "provider_event_persist_failed"
    assert run_svc.completed[0].status == "failed"
    assert await ProviderCursorRepository().get_cursor("tenant-1", "conn_1", IDENTITY) is None


@pytest.mark.asyncio
async def test_scoped_cursor_separates_accounts_and_streams_without_rekeying_v1():
    cursors = ProviderCursorRepository()
    await cursors.set_cursor("tenant-1", "conn_1", IDENTITY, "legacy")
    await cursors.set_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
        "orders-a",
        account_id="account-a",
        stream_id="orders",
    )
    await cursors.set_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
        "refunds-a",
        account_id="account-a",
        stream_id="refunds",
    )
    await cursors.set_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
        "orders-b",
        account_id="account-b",
        stream_id="orders",
    )
    await cursors.set_cursor(
        "tenant-1",
        "conn_1",
        IDENTITY,
        "unscoped-account-orders",
        account_id="",
        stream_id="accountless_orders",
    )

    assert (await cursors.get_cursor("tenant-1", "conn_1", IDENTITY))["cursor_value"] == "legacy"
    assert (
        await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="account-a",
            stream_id="orders",
        )
    )["cursor_value"] == "orders-a"
    assert (
        await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="account-a",
            stream_id="refunds",
        )
    )["cursor_value"] == "refunds-a"
    assert (
        await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="account-b",
            stream_id="orders",
        )
    )["cursor_value"] == "orders-b"
    assert (
        await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="",
            stream_id="accountless_orders",
        )
    )["cursor_value"] == "unscoped-account-orders"
    with pytest.raises(ValueError, match="both required"):
        await cursors.get_cursor("tenant-1", "conn_1", IDENTITY, stream_id="orders")


@pytest.mark.asyncio
async def test_manifest_activation_runs_only_matching_pull_streams_for_each_account():
    enabled = make_stream(
        "orders",
        enabled_by_default=False,
        activation_config_field="sync_mode",
        activation_config_value="enabled",
    )
    disabled = make_stream(
        "refunds",
        enabled_by_default=False,
        activation_config_field="sync_mode",
        activation_config_value="disabled",
    )
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="order")],
                    next_cursor="next",
                    has_more=False,
                )
            )
        ]
    )
    plugin = FakePlugin(
        pull=pull,
        normalizer=FakeNormalizer(),
        manifest=make_stream_manifest(enabled, disabled),
    )
    scheduler = build_scheduler(plugin=plugin)
    connection = make_connection(
        selected_accounts=("account-a", "account-b"),
        config={"sync_mode": "enabled"},
    )

    result = await scheduler.run_sync(connection)

    assert result["status"] == "completed"
    assert [(call["context"].account_id, call["context"].stream_id) for call in pull.calls] == [
        ("account-a", "orders"),
        ("account-b", "orders"),
    ]
    assert all(
        record.account_id == call["context"].account_id
        for record, call in zip(scheduler.raw_store.records, pull.calls, strict=True)
    )
    assert all(record.stream_id == "orders" for record in scheduler.raw_store.records)
    assert len(result["stream_runs"]) == 2


@pytest.mark.asyncio
async def test_activation_uses_manifest_default_when_connection_omits_config_field():
    stream = make_stream(
        "orders",
        enabled_by_default=False,
        activation_config_field="sync_mode",
        activation_config_value="incremental",
    )
    manifest = make_stream_manifest(
        stream,
        config_fields=(
            ConfigFieldSpec(
                name="sync_mode",
                type="enum",
                allowed_values=["backfill", "incremental"],
                default_value="incremental",
            ),
        ),
    )
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=manifest,
        )
    )

    result = await scheduler.run_sync(make_connection(config={}))

    assert result["status"] == "completed"
    assert len(pull.calls) == 1
    assert pull.calls[0]["context"].stream_id == "orders"

    explicit_other_value = make_connection(config={"sync_mode": "backfill"})
    inactive_result = await scheduler.run_sync(explicit_other_value)
    assert inactive_result["status"] == "skipped"
    assert len(pull.calls) == 1


@pytest.mark.asyncio
async def test_manifest_inactive_streams_are_skipped_and_explicit_inactive_fails():
    inactive = make_stream(
        "orders",
        enabled_by_default=False,
        activation_config_field="sync_mode",
        activation_config_value="enabled",
    )
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    plugin = FakePlugin(
        pull=pull,
        normalizer=FakeNormalizer(),
        manifest=make_stream_manifest(inactive),
    )
    scheduler = build_scheduler(plugin=plugin)
    connection = make_connection(config={"sync_mode": "disabled"})

    skipped = await scheduler.run_sync(connection)
    assert skipped["status"] == "skipped"
    assert pull.calls == []

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(connection, stream_id="orders")
    assert excinfo.value.details["error_code"] == "provider_stream_inactive"
    assert pull.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_error"),
    [
        ("unknown_after_valid", "provider_stream_not_found"),
        ("non_pullable", "provider_stream_not_pullable"),
        ("inactive", "provider_stream_inactive"),
    ],
)
async def test_stream_selection_is_fully_validated_before_provider_work(case, expected_error):
    config = {}
    if case == "unknown_after_valid":
        streams = [make_stream("orders")]
        requested_stream_ids = ["orders", "missing"]
    elif case == "non_pullable":
        streams = [make_stream("reports", acquisition_modes=("report",))]
        requested_stream_ids = ["reports"]
    else:
        streams = [
            make_stream(
                "orders",
                enabled_by_default=False,
                activation_config_field="sync_mode",
                activation_config_value="enabled",
            )
        ]
        requested_stream_ids = ["orders"]
        config = {"sync_mode": "disabled"}

    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    broker = FakeBroker()
    run_service = FakeRunService()
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(*streams),
        ),
        broker=broker,
        sync_runs=run_service,
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(
            make_connection(selected_accounts=("account-a",), config=config),
            stream_ids=requested_stream_ids,
        )

    assert excinfo.value.details["error_code"] == expected_error
    assert pull.calls == []
    assert broker.reveals == []
    assert run_service.opened == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stream_ids", "expected_error"),
    [
        (["orders", "orders"], "provider_stream_selection_duplicate"),
        ([f"stream_{index}" for index in range(33)], "provider_stream_selection_too_large"),
    ],
)
async def test_scheduler_rejects_duplicate_or_oversized_stream_selection(
    stream_ids,
    expected_error,
):
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    broker = FakeBroker()
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(make_stream("orders")),
        ),
        broker=broker,
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(make_connection(), stream_ids=stream_ids)

    assert excinfo.value.details["error_code"] == expected_error
    assert pull.calls == []
    assert broker.reveals == []


@pytest.mark.asyncio
async def test_streamless_v1_plugin_rejects_explicit_stream_selection():
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    broker = FakeBroker()
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(),
        ),
        broker=broker,
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(make_connection(), stream_ids=["orders"])

    assert excinfo.value.details["error_code"] == "provider_stream_not_found"
    assert pull.calls == []
    assert broker.reveals == []


@pytest.mark.asyncio
async def test_scheduler_separates_cursors_by_account_and_stream():
    cursors = ProviderCursorRepository()
    initial = {
        ("account-a", "orders"): "a-orders-before",
        ("account-a", "refunds"): "a-refunds-before",
        ("account-b", "orders"): "b-orders-before",
        ("account-b", "refunds"): "b-refunds-before",
    }
    for (account_id, stream_id), value in initial.items():
        await cursors.set_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            value,
            account_id=account_id,
            stream_id=stream_id,
        )
    await cursors.set_cursor("tenant-1", "conn_1", IDENTITY, "legacy-before")

    batches = [
        AdapterResult.ok(
            ReadBatch(
                records=[make_record(record_id=f"record-{index}")],
                next_cursor=f"after-{index}",
                has_more=False,
            )
        )
        for index in range(4)
    ]
    pull = FakePull(batches)
    plugin = FakePlugin(
        pull=pull,
        normalizer=FakeNormalizer(),
        manifest=make_stream_manifest(make_stream("orders"), make_stream("refunds")),
    )
    scheduler = build_scheduler(plugin=plugin, cursors=cursors)

    result = await scheduler.run_sync(
        make_connection(selected_accounts=("account-a", "account-b")),
        stream_ids=[],
    )

    assert result["status"] == "completed"
    observed = [
        (call["context"].account_id, call["context"].stream_id, call["cursor"])
        for call in pull.calls
    ]
    assert observed == [
        ("account-a", "orders", "a-orders-before"),
        ("account-a", "refunds", "a-refunds-before"),
        ("account-b", "orders", "b-orders-before"),
        ("account-b", "refunds", "b-refunds-before"),
    ]
    for ((account_id, stream_id), _), index in zip(initial.items(), range(4), strict=True):
        stored = await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id=account_id,
            stream_id=stream_id,
        )
        assert stored["cursor_value"] == f"after-{index}"
    assert (await cursors.get_cursor("tenant-1", "conn_1", IDENTITY))[
        "cursor_value"
    ] == "legacy-before"


@pytest.mark.asyncio
async def test_scheduler_selects_stream_across_accounts_with_scoped_cursors():
    cursors = ProviderCursorRepository()
    initial = {
        ("account-a", "orders"): "a-orders-before",
        ("account-a", "refunds"): "a-refunds-before",
        ("account-b", "orders"): "b-orders-before",
        ("account-b", "refunds"): "b-refunds-before",
    }
    for (account_id, stream_id), value in initial.items():
        await cursors.set_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            value,
            account_id=account_id,
            stream_id=stream_id,
        )
    pull = FakePull(
        [
            AdapterResult.ok(ReadBatch(records=[], next_cursor="a-refunds-after", has_more=False)),
            AdapterResult.ok(ReadBatch(records=[], next_cursor="b-refunds-after", has_more=False)),
        ]
    )
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(make_stream("orders"), make_stream("refunds")),
        ),
        cursors=cursors,
    )

    result = await scheduler.run_sync(
        make_connection(selected_accounts=("account-a", "account-b")),
        stream_ids=["refunds"],
    )

    assert result["status"] == "completed"
    assert [(item["account_id"], item["stream_id"]) for item in result["stream_runs"]] == [
        ("account-a", "refunds"),
        ("account-b", "refunds"),
    ]
    assert [
        (call["context"].account_id, call["context"].stream_id, call["cursor"])
        for call in pull.calls
    ] == [
        ("account-a", "refunds", "a-refunds-before"),
        ("account-b", "refunds", "b-refunds-before"),
    ]
    for account_id, stream_id in initial:
        cursor = await cursors.get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id=account_id,
            stream_id=stream_id,
        )
        expected = (
            ("a-refunds-after" if account_id == "account-a" else "b-refunds-after")
            if stream_id == "refunds"
            else initial[(account_id, stream_id)]
        )
        assert cursor["cursor_value"] == expected


@pytest.mark.asyncio
async def test_stream_raw_record_scope_mismatch_fails_before_persistence():
    pull = FakePull(
        [
            AdapterResult.ok(
                ReadBatch(
                    records=[make_record(record_id="o1", account_id="different-account")],
                    next_cursor="must-not-advance",
                    has_more=False,
                )
            )
        ]
    )
    raw_store = FakeRawStore()
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(make_stream("orders")),
        ),
        raw_store=raw_store,
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(make_connection(selected_accounts=("account-a",)))

    assert excinfo.value.details["error_code"] == "provider_raw_scope_mismatch"
    assert raw_store.records == []
    assert (
        await ProviderCursorRepository().get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="account-a",
            stream_id="orders",
        )
        is None
    )


@pytest.mark.asyncio
async def test_streamless_manifest_keeps_v1_cursor_and_first_account_behavior():
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[], has_more=False))])
    scheduler = build_scheduler(
        plugin=FakePlugin(
            pull=pull,
            normalizer=FakeNormalizer(),
            manifest=make_stream_manifest(),
        ),
    )
    result = await scheduler.run_sync(make_connection(selected_accounts=("account-a", "account-b")))

    assert result.status == "completed"
    assert pull.calls[0]["context"].account_id == "account-a"
    assert pull.calls[0]["context"].stream_id is None
    assert (
        await ProviderCursorRepository().get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
        )
        is not None
    )
    assert (
        await ProviderCursorRepository().get_cursor(
            "tenant-1",
            "conn_1",
            IDENTITY,
            account_id="account-a",
            stream_id="orders",
        )
        is None
    )


@pytest.mark.asyncio
async def test_streamless_raw_record_is_bound_to_selected_account_before_persistence():
    record = make_record(record_id="o1")
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[record], has_more=False))])
    raw_store = FakeRawStore()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=raw_store,
    )

    await scheduler.run_sync(make_connection(selected_accounts=("account-a",)))

    assert len(raw_store.records) == 1
    assert raw_store.records[0].account_id == "account-a"


@pytest.mark.asyncio
async def test_streamless_raw_record_for_an_unselected_account_is_rejected_before_persistence():
    record = make_record(record_id="o1", account_id="account-b")
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[record], has_more=False))])
    raw_store = FakeRawStore()
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=raw_store,
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(make_connection(selected_accounts=("account-a",)))

    assert excinfo.value.details["error_code"] == "provider_raw_scope_mismatch"
    assert raw_store.records == []


@pytest.mark.asyncio
async def test_streamless_persisted_record_must_match_selected_account():
    record = make_record(record_id="o1")
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[record], has_more=False))])
    scheduler = build_scheduler(
        plugin=FakePlugin(pull=pull, normalizer=FakeNormalizer()),
        raw_store=WrongAccountRawStore(),
    )

    with pytest.raises(ProviderPullFailed) as excinfo:
        await scheduler.run_sync(make_connection(selected_accounts=("account-a",)))

    assert excinfo.value.details["error_code"] == "provider_raw_persist_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "orders_api,expected_stream",
    [
        (None, "orders_rest"),
        ("rest", "orders_rest"),
        ("rest_webhook", "orders_rest_webhook"),
        ("graphql", "orders"),
    ],
)
async def test_shopify_manifest_activation_runs_exactly_one_mode_stream(
    orders_api: Optional[str],
    expected_stream: str,
):
    from connectors.providers.shopify.plugin import ShopifyOrdersPlugin

    identity = "shopify.admin.orders_read"
    selected_id = "shop:myshop.myshopify.com"
    persisted_gid = "gid://shopify/Shop/123"
    record = make_raw_record(
        provider_identity=identity,
        provider_record_id="gid://shopify/Order/1",
        provider_record_type="order",
        payload={"id": "gid://shopify/Order/1"},
        tenant_id="tenant-1",
        connection_id="conn_1",
        acquisition_mode="poll",
    )
    pull = FakePull([AdapterResult.ok(ReadBatch(records=[record], has_more=False))])
    plugin = ShopifyOrdersPlugin()
    plugin.pull = lambda: pull
    plugin.normalizer = lambda: FakeNormalizer()
    accounts = ProviderAccountRepository()
    config = {"shop_domain": "myshop.myshopify.com"}
    if orders_api is not None:
        config["orders_api"] = orders_api
    if orders_api == "graphql":
        config["source_account_realm"] = "test"
    connection = make_connection(
        provider_identity=identity,
        selected_accounts=(selected_id,),
        config=config,
    )
    if orders_api == "graphql":
        connection.last_verified_at = "2026-10-03T00:00:00+00:00"
        await accounts.upsert(
            ProviderAccountRecord(
                account_id=f"{connection.connection_id}:{selected_id}",
                tenant_id=connection.tenant_id,
                connection_id=connection.connection_id,
                provider_identity=identity,
                external_id=persisted_gid,
                metadata={"shop_gid": persisted_gid, "source_account_realm": "test"},
            )
        )
    scheduler = build_scheduler(
        plugin=plugin,
        provider_identity=identity,
        accounts=accounts,
    )
    result = await scheduler.run_sync(connection)

    assert result["status"] == "completed"
    assert len(result["stream_runs"]) == 1
    assert result["stream_runs"][0]["stream_id"] == expected_stream
    assert len(pull.calls) == 1
    assert pull.calls[0]["context"].stream_id == expected_stream
    assert pull.calls[0]["context"].account_id == selected_id
    if orders_api == "graphql":
        assert pull.calls[0]["context"].config["_verified_shop_gid"] == persisted_gid
    assert scheduler.raw_store.records[0].stream_id == expected_stream
