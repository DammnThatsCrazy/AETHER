"""Rights Authority retention DELETION EXECUTOR — gates, scope, honest state.

The executor is the other half of retention: before it, the seam could only ever
persist a *pending* ``delete_at_expiry`` impact item and nothing acted on it.
Deletion is irreversible, so these tests pin the fail-closed behaviour rather
than the happy path alone:

- every enabling gate closed ⇒ zero deletions and every row still ``pending``;
- an unsupported ``component_type`` ⇒ the row stays ``pending`` (no stub adapter
  may report a completion it did not achieve);
- the enabled + supported path ⇒ the store delete is called exactly once and the
  row transitions to the ONLY terminal token the repository accepts;
- an out-of-tenant artifact ref ⇒ refused, nothing deleted, row still ``pending``;
- a scheduled expiry still in the future ⇒ not deleted (retention owns the data
  until its window closes).

The rows are produced by the REAL retention seam and read through the REAL
``rights_impact_repository`` (in-memory backend), so the repository's own
``remediation_state`` vocabulary validation is exercised rather than mocked.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from config.settings import RightsAuthorityConfig, settings
from repositories.repos import reset_in_memory_stores
from services.rights_authority import deletion_executor as executor_mod
from services.rights_authority import retention as retention_mod
from services.rights_authority.deletion_adapters import (
    BYTE_PLANE_DIMENSION,
    DELETION_STATUS_ALREADY_ABSENT,
    DELETION_STATUS_DELETED,
    UNSUPPORTED_DIMENSION_REASONS,
    DeletionAdapterRegistry,
    DeletionResult,
    ObjectStoreDeletionAdapter,
    deletion_adapter_registry,
    validate_object_key_for_tenant,
)
from services.rights_authority.deletion_executor import (
    BLOCKED_STATE,
    CLAIM_STATE,
    COMPLETE_STATE,
    RETENTION_DELETION_ACTIONS,
    deletion_gates,
    retention_due_instant,
    run_rights_deletion_sweep_loop,
    sweep_pending_deletions,
)
from services.rights_authority.impact import RIGHTS_IMPACT_DIMENSIONS
from services.rights_authority.repositories import rights_impact_repository
from services.rights_authority.retention import RETENTION_SCHEDULED_DELETE_ACTION
from services.rights_authority.rollout import (
    ROLLOUT_ENV_VAR,
    configure_rollout,
    reset_rollout,
)
from shared.common.common import utc_now
from shared.storage.object_store import InMemoryObjectStore

TENANT = "t1"
OTHER_TENANT = "t2"
ARTIFACT_KEY = f"data-exchange/{TENANT}/ingress/art_1"
OTHER_TENANT_KEY = f"data-exchange/{OTHER_TENANT}/ingress/art_1"
DELETE_FLAG_ENV = "RIGHTS_AUTHORITY_DELETION_EXECUTOR_ENABLED"

PAST = utc_now() - timedelta(days=1)
FUTURE = utc_now() + timedelta(days=30)


class _CountingStore(InMemoryObjectStore):
    """In-memory byte plane that records every ``delete`` call."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_calls: list[str] = []

    def delete(self, key: str) -> bool:
        self.delete_calls.append(key)
        return super().delete(key)


class _ExplodingAdapter:
    """Adapter whose delete always fails (store outage / backend misconfig)."""

    component_type = BYTE_PLANE_DIMENSION

    def validate_scope(self, *, tenant_id: str, artifact_ref: str):
        return artifact_ref

    async def delete(self, *, tenant_id: str, artifact_ref: str) -> DeletionResult:
        raise RuntimeError("byte plane unavailable")


async def _no_hold(_tenant_id: str) -> bool:
    return False


async def _always_hold(_tenant_id: str) -> bool:
    return True


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    reset_in_memory_stores()
    reset_rollout()
    monkeypatch.delenv(ROLLOUT_ENV_VAR, raising=False)
    monkeypatch.delenv(DELETE_FLAG_ENV, raising=False)
    # The ambient process settings must never decide these tests: pin the flag
    # OFF and let each test opt in explicitly.
    monkeypatch.setattr(settings, "rights_authority", RightsAuthorityConfig())
    yield
    reset_rollout()
    reset_in_memory_stores()


@pytest.fixture
def store() -> _CountingStore:
    return _CountingStore()


@pytest.fixture
def registry(store: _CountingStore) -> DeletionAdapterRegistry:
    return DeletionAdapterRegistry((ObjectStoreDeletionAdapter(store=store),))


def _enable_executor(monkeypatch) -> None:
    monkeypatch.setattr(
        settings,
        "rights_authority",
        RightsAuthorityConfig(deletion_executor_enabled=True),
    )


async def _seed_due_delete_row(
    *,
    tenant_id: str = TENANT,
    artifact_ref: str = ARTIFACT_KEY,
    expires_at=PAST,
    component_type: str = BYTE_PLANE_DIMENSION,
) -> str:
    """Persist a pending retention deletion row through the REAL retention seam."""
    resolution = await retention_mod.schedule_retention(
        tenant_id=tenant_id,
        artifact_ref=artifact_ref,
        expires_at=expires_at,
        component_type=component_type,
    )
    assert resolution.impact_ids, "retention seam should have scheduled a deletion"
    return resolution.impact_ids[0]


async def _row_state(impact_id: str) -> str:
    row = await rights_impact_repository.get(impact_id)
    assert row is not None, f"impact {impact_id} disappeared from the durable store"
    return str(row.get("remediation_state"))


async def _sweep(tenant_id: str = TENANT, **kwargs) -> dict:
    kwargs.setdefault("legal_hold_checker", _no_hold)
    return await sweep_pending_deletions(tenant_id=tenant_id, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════
# (1) Every gate closed ⇒ zero deletions, every row still pending
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_gates_off_deletes_nothing_and_leaves_rows_pending(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    first = await _seed_due_delete_row()
    second = await _seed_due_delete_row(artifact_ref=f"data-exchange/{TENANT}/ingress/art_2")
    store.put(ARTIFACT_KEY, b"payload-1")
    store.put(f"data-exchange/{TENANT}/ingress/art_2", b"payload-2")

    report = await _sweep(registry=registry)

    assert store.delete_calls == [], "no gate-permitted deletion may ever be attempted"
    assert await _row_state(first) == "pending"
    assert await _row_state(second) == "pending"
    assert report["totals"]["deleted"] == 0
    assert report["totals"]["eligible"] == 0
    assert report["totals"]["gate_blocked"] == 2
    gates = report["gates"][BYTE_PLANE_DIMENSION]
    assert gates["rollout_ok"] is False
    assert gates["enabled_ok"] is False
    assert gates["adapter_ok"] is True
    assert "rollout=off" in gates["reason"]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["off", "shadow", "warn"])
async def test_non_enforcing_rollout_never_deletes(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch, mode
):
    # Only ``enforce`` binds; shadow/warn record and warn but must never delete.
    _enable_executor(monkeypatch)
    configure_rollout(mode)
    impact_id = await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == []
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["gate_blocked"] == 1
    assert mode in report["gates"][BYTE_PLANE_DIMENSION]["reason"]


@pytest.mark.asyncio
async def test_enable_flag_off_alone_blocks_deletion(
    store: _CountingStore, registry: DeletionAdapterRegistry
):
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == []
    assert await _row_state(impact_id) == "pending"
    gates = report["gates"][BYTE_PLANE_DIMENSION]
    assert gates["rollout_ok"] is True and gates["enabled_ok"] is False
    assert DELETE_FLAG_ENV in gates["reason"]


# ═══════════════════════════════════════════════════════════════════════════
# (2) No adapter for the dimension ⇒ row stays pending (no fake completion)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_dimension_without_adapter_leaves_row_pending(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row(component_type="vector_embedding")
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == []
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["deleted"] == 0
    assert report["totals"]["gate_blocked"] == 1
    reason = report["gates"]["vector_embedding"]["reason"]
    assert "no deletion adapter" in reason
    assert UNSUPPORTED_DIMENSION_REASONS["vector_embedding"][:24] in reason


@pytest.mark.asyncio
async def test_default_registry_serves_only_the_byte_plane(
    store: _CountingStore, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    # A row the DEFAULT registry must refuse (no adapter registered for it).
    impact_id = await _seed_due_delete_row(component_type="exported_artifact")
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=deletion_adapter_registry)

    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["gate_blocked"] == 1
    assert deletion_adapter_registry.supported_dimensions() == (BYTE_PLANE_DIMENSION,)


# ═══════════════════════════════════════════════════════════════════════════
# (3) Enabled + supported path ⇒ one delete, row transitions
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_enabled_supported_path_deletes_once_and_completes(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == [ARTIFACT_KEY], "exactly one delete for the row"
    assert store.head(ARTIFACT_KEY) is None, "bytes are actually gone"
    assert await _row_state(impact_id) == COMPLETE_STATE
    assert report["totals"]["deleted"] == 1
    assert report["totals"]["eligible"] == 1
    assert report["totals"]["blocked"] == 0
    assert report["outcomes"][0]["evidence_refs"] == [f"objdel:{ARTIFACT_KEY}"]


@pytest.mark.asyncio
async def test_completed_row_is_not_swept_again(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    await _sweep(registry=registry)
    second = await _sweep(registry=registry)

    assert store.delete_calls == [ARTIFACT_KEY]
    assert second["totals"]["rows_scanned"] == 0


@pytest.mark.asyncio
async def test_already_absent_bytes_complete_without_a_delete_call(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row()  # nothing put in the store

    report = await _sweep(registry=registry)

    assert store.delete_calls == []
    assert await _row_state(impact_id) == COMPLETE_STATE
    assert report["totals"]["deleted"] == 0
    assert report["totals"]["already_absent"] == 1
    assert report["outcomes"][0]["action"] == DELETION_STATUS_ALREADY_ABSENT


@pytest.mark.asyncio
async def test_failed_delete_blocks_the_row_never_claims_completion(
    store: _CountingStore, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    registry = DeletionAdapterRegistry((_ExplodingAdapter(),))
    impact_id = await _seed_due_delete_row()

    report = await _sweep(registry=registry)

    assert await _row_state(impact_id) == BLOCKED_STATE
    assert report["totals"]["deleted"] == 0
    assert report["totals"]["blocked"] == 1


@pytest.mark.asyncio
async def test_dry_run_reports_without_mutating(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry, dry_run=True)

    assert store.delete_calls == []
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["dry_run_eligible"] == 1
    assert report["totals"]["deleted"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# (4) Tenant scope guard refuses an out-of-tenant ref
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_out_of_tenant_ref_is_refused_and_row_stays_pending(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row(artifact_ref=OTHER_TENANT_KEY)
    store.put(OTHER_TENANT_KEY, b"another-tenant-payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == [], "never delete outside the impact's tenant scope"
    assert store.head(OTHER_TENANT_KEY) is not None
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["refused_out_of_scope"] == 1
    assert report["totals"]["deleted"] == 0


@pytest.mark.asyncio
async def test_scope_guard_refuses_malformed_and_foreign_keys(
    store: _CountingStore
):
    adapter = ObjectStoreDeletionAdapter(store=store)
    # In scope.
    assert adapter.validate_scope(tenant_id=TENANT, artifact_ref=ARTIFACT_KEY) == ARTIFACT_KEY
    # Foreign tenant, sibling-tenant prefix (acme vs acme2), traversal, and
    # non-data-exchange key shapes are all refused.
    for ref in (
        OTHER_TENANT_KEY,
        f"data-exchange/{TENANT}2/ingress/art_1",
        f"data-exchange/{TENANT}/../art_1",
        f"data-exchange/{TENANT}/ingress",
        "raw/t1/art_1",
        "",
    ):
        assert adapter.validate_scope(tenant_id=TENANT, artifact_ref=ref) is None, ref
    assert validate_object_key_for_tenant(TENANT, ARTIFACT_KEY) == ARTIFACT_KEY
    assert validate_object_key_for_tenant(TENANT, OTHER_TENANT_KEY) is None


@pytest.mark.asyncio
async def test_direct_adapter_delete_refuses_out_of_scope_ref(store: _CountingStore):
    # Defence in depth: even called directly (not through the sweep), the adapter
    # revalidates and refuses rather than trusting its caller.
    store.put(OTHER_TENANT_KEY, b"payload")
    adapter = ObjectStoreDeletionAdapter(store=store)

    result = await adapter.delete(tenant_id=TENANT, artifact_ref=OTHER_TENANT_KEY)

    assert result.deleted is False
    assert result.status == "refused_out_of_scope"
    assert store.delete_calls == []


# ═══════════════════════════════════════════════════════════════════════════
# Due-ness: retention owns the data until its window closes
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_future_expiry_is_not_deleted(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row(expires_at=FUTURE)
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == [], "deleting before the retention window closes is data loss"
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["not_due"] == 1


@pytest.mark.asyncio
async def test_row_without_a_provable_due_instant_is_not_deleted(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    # A hand-written row carrying the retention action but no expiry anywhere.
    await rights_impact_repository.record({
        "impact_id": "rimp_no_due_instant",
        "tenant_id": TENANT,
        "artifact_ref": ARTIFACT_KEY,
        "component_type": BYTE_PLANE_DIMENSION,
        "required_action": RETENTION_SCHEDULED_DELETE_ACTION,
        "remediation_state": "pending",
        "reason": "retention expiry unknown",
    })
    store.put(ARTIFACT_KEY, b"payload")

    report = await _sweep(registry=registry)

    assert store.delete_calls == []
    assert await _row_state("rimp_no_due_instant") == "pending"
    assert report["totals"]["no_due_instant"] == 1


def test_retention_due_instant_reads_structure_then_reason():
    from datetime import datetime, timezone

    aware = datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)
    assert retention_due_instant({"expires_at": aware.isoformat()}) == aware
    assert retention_due_instant({"delete_after": aware.isoformat()}) == aware
    # The retention seam's documented reason prefix.
    assert retention_due_instant(
        {"reason": f"retention expiry {aware.isoformat()} for art_1 (basis, decision ?) — x"}
    ) == aware
    # A naive DATETIME is refused rather than guessed into a zone.
    from datetime import datetime as _dt

    assert retention_due_instant({"expires_at": _dt(2026, 3, 4, 5, 6, 7)}) is None
    # Unprovable forms are None (fail closed), never "now".
    assert retention_due_instant({}) is None
    assert retention_due_instant({"reason": "retention expiry unknown"}) is None
    assert retention_due_instant({"expires_at": "not-a-date"}) is None
    assert retention_due_instant({"expires_at": ""}) is None
    # A naive ISO STRING follows the shared temporal parser's documented rule
    # (assume UTC, never infer a local zone) — it is the byte-plane/event-time
    # convention this codebase already uses for stored instants.
    assert retention_due_instant({"expires_at": "2026-03-04T05:06:07"}) == aware


# ═══════════════════════════════════════════════════════════════════════════
# Legal hold blocks deletion (reuses the Data Exchange expire-path rule)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_active_legal_hold_blocks_deletion(
    store: _CountingStore, registry: DeletionAdapterRegistry, monkeypatch
):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")
    impact_id = await _seed_due_delete_row()
    store.put(ARTIFACT_KEY, b"payload")

    report = await sweep_pending_deletions(
        tenant_id=TENANT, registry=registry, legal_hold_checker=_always_hold
    )

    assert store.delete_calls == []
    assert await _row_state(impact_id) == "pending"
    assert report["totals"]["held"] == 1


@pytest.mark.asyncio
async def test_unhealthy_hold_store_blocks_deletion(store: _CountingStore, monkeypatch):
    _enable_executor(monkeypatch)
    configure_rollout("enforce")

    async def _broken_checker(_tenant_id: str) -> bool:
        raise RuntimeError("holds store unavailable")

    impact_id = await _seed_due_delete_row()

    # The executor treats a raising checker as a block, never as "no holds".
    with pytest.raises(RuntimeError):
        await sweep_pending_deletions(
            tenant_id=TENANT, legal_hold_checker=_broken_checker
        )
    assert await _row_state(impact_id) == "pending"


# ═══════════════════════════════════════════════════════════════════════════
# State vocabulary: the repository accepts ``complete``, not ``executed``
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_update_state_rejects_executed_and_accepts_complete():
    impact_id = await _seed_due_delete_row()

    # The internal row vocabulary (impact.REMEDIATION_STATES) carries "executed",
    # but the durable repository validates against contracts
    # ALLOWED_REMEDIATION_STATES, which does not — so the executor must never
    # write it.
    for token in ("executed", "remediated", "done", ""):
        with pytest.raises(ValueError):
            await rights_impact_repository.update_state(impact_id, token)

    await rights_impact_repository.update_state(impact_id, COMPLETE_STATE)
    assert await _row_state(impact_id) == COMPLETE_STATE


def test_executor_writes_only_repository_permitted_states():
    from services.rights_authority.contracts import ALLOWED_REMEDIATION_STATES

    assert {CLAIM_STATE, COMPLETE_STATE, BLOCKED_STATE} <= ALLOWED_REMEDIATION_STATES
    assert "executed" not in ALLOWED_REMEDIATION_STATES
    assert RETENTION_DELETION_ACTIONS == frozenset({RETENTION_SCHEDULED_DELETE_ACTION})


# ═══════════════════════════════════════════════════════════════════════════
# Registry / gate declarations
# ═══════════════════════════════════════════════════════════════════════════

def test_every_dimension_is_supported_or_explicitly_unsupported():
    supported = set(deletion_adapter_registry.supported_dimensions())
    unsupported = set(deletion_adapter_registry.unsupported_dimensions())
    assert supported == {BYTE_PLANE_DIMENSION}
    assert supported | unsupported == set(RIGHTS_IMPACT_DIMENSIONS)
    assert supported & unsupported == set()
    for dimension in unsupported:
        reason = deletion_adapter_registry.unsupported_reason(dimension)
        assert reason and len(reason) > 20, f"{dimension} needs a real reason"
        assert deletion_adapter_registry.has_adapter(dimension) is False
    assert deletion_adapter_registry.has_adapter(BYTE_PLANE_DIMENSION) is True
    assert deletion_adapter_registry.unsupported_reason(BYTE_PLANE_DIMENSION) is None


def test_registry_rejects_unknown_and_duplicate_dimensions():
    registry = DeletionAdapterRegistry()

    class _Unknown:
        component_type = "not_a_dimension"

        def validate_scope(self, *, tenant_id, artifact_ref):
            return artifact_ref

        async def delete(self, *, tenant_id, artifact_ref):
            return DeletionResult(status=DELETION_STATUS_DELETED, deleted=True)

    with pytest.raises(ValueError):
        registry.register(_Unknown())

    registry.register(ObjectStoreDeletionAdapter())
    with pytest.raises(ValueError):
        registry.register(ObjectStoreDeletionAdapter())


@pytest.mark.parametrize("rollout,enabled,adapter,expect_allowed", [
    ("off", False, True, False),
    ("enforce", False, True, False),
    ("enforce", True, False, False),
    ("off", True, False, False),
    ("enforce", True, True, True),
])
def test_deletion_gates_require_all_three(
    monkeypatch, rollout, enabled, adapter, expect_allowed
):
    reset_rollout()
    configure_rollout(rollout)
    monkeypatch.setattr(
        settings,
        "rights_authority",
        RightsAuthorityConfig(deletion_executor_enabled=enabled),
    )
    registry = DeletionAdapterRegistry(
        (ObjectStoreDeletionAdapter(),) if adapter else ()
    )

    decision = deletion_gates(BYTE_PLANE_DIMENSION, registry=registry)

    assert decision.allowed is expect_allowed
    assert decision.rollout_ok is (rollout == "enforce")
    assert decision.enabled_ok is enabled
    assert decision.adapter_ok is adapter
    if not expect_allowed:
        assert decision.reason


# ═══════════════════════════════════════════════════════════════════════════
# Setting + supervised worker registration (disabled by default)
# ═══════════════════════════════════════════════════════════════════════════

def test_executor_setting_is_env_backed_and_defaults_off(monkeypatch):
    from config.settings import _env_bool

    # Fail-closed default: the flag is OFF unless the operator opts in.
    assert RightsAuthorityConfig().deletion_executor_enabled is False
    assert settings.rights_authority.deletion_executor_enabled is False

    # The flag is bound to the documented env key: truthy spellings turn it on,
    # and every other value (including an unparseable one) leaves it off. Like
    # every other flag in this module the binding is evaluated at import (process
    # start), which is what makes activation explicit rather than implicit.
    for truthy in ("true", "1", "yes", "TRUE", "Yes"):
        monkeypatch.setenv(DELETE_FLAG_ENV, truthy)
        assert _env_bool(DELETE_FLAG_ENV, False) is True
    for falsy in ("false", "0", "no", "bogus", ""):
        monkeypatch.setenv(DELETE_FLAG_ENV, falsy)
        assert _env_bool(DELETE_FLAG_ENV, False) is False


def test_worker_spec_is_registered_and_disabled_by_default(monkeypatch):
    from services.runtime.roles import ROLE_TO_SPEC_NAMES, owning_role
    from services.runtime.specs import build_worker_specs

    monkeypatch.setattr(settings, "rights_authority", RightsAuthorityConfig())
    specs = {
        spec.name: spec
        for spec in build_worker_specs(registry=object(), settings=settings)
    }
    spec = specs["rights_deletion_executor"]

    assert spec.enabled() is False, "the deletion executor must ship disabled"
    assert spec.required is False, "a stalled sweep must not abort startup"
    assert "rights_deletion_executor" in ROLE_TO_SPEC_NAMES["maintenance"]
    # A spec no role claims is an orphan the topology validator rejects: the
    # role map must attribute this one to maintenance.
    assert owning_role("rights_deletion_executor") == "maintenance"

    # The factory imports the real builder module lazily and returns a FRESH
    # coroutine per (re)start.
    coro = spec.factory()
    try:
        assert hasattr(coro, "send")
    finally:
        coro.close()

    monkeypatch.setattr(
        settings,
        "rights_authority",
        RightsAuthorityConfig(deletion_executor_enabled=True),
    )
    assert specs["rights_deletion_executor"].enabled() is True


def test_sweep_loop_builder_returns_a_fresh_coroutine(monkeypatch):
    monkeypatch.setenv("RIGHTS_DELETION_EXECUTOR_INTERVAL_SECONDS", "0")
    coro = executor_mod.build_rights_deletion_executor_coro()
    try:
        assert hasattr(coro, "send")
    finally:
        coro.close()
    # A non-positive / unparseable interval falls back to the safe default
    # rather than spinning.
    assert executor_mod._sweep_interval_seconds() == 3600
    monkeypatch.setenv("RIGHTS_DELETION_EXECUTOR_INTERVAL_SECONDS", "45")
    assert executor_mod._sweep_interval_seconds() == 45
    monkeypatch.setenv("RIGHTS_DELETION_EXECUTOR_INTERVAL_SECONDS", "soon")
    assert executor_mod._sweep_interval_seconds() == 3600


def test_sweep_loop_stays_alive_when_a_sweep_fails(monkeypatch):
    """A sweep that raises must be logged and retried, never kill the loop."""
    import asyncio

    calls = {"n": 0}

    async def _boom(**_kwargs):
        calls["n"] += 1
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(executor_mod, "sweep_pending_deletions", _boom)

    async def _scenario():
        task = asyncio.create_task(run_rights_deletion_sweep_loop(interval_seconds=0))
        while calls["n"] < 3:
            await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())

    assert calls["n"] >= 3, "the loop must log each failure and keep sweeping"


def test_deletion_status_tokens_are_the_adapter_contract():
    assert DELETION_STATUS_DELETED == "deleted"
    assert DELETION_STATUS_ALREADY_ABSENT == "already_absent"
