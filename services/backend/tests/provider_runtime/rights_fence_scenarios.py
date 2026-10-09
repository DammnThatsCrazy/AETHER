"""Scenarios for the revocation fence around provider raw-record writes.

A grant is admitted at one instant and the raw record is written later. These
scenarios hold the writer between the two and race a revocation against it. They
run unchanged against the in-memory grant store (``test_rights_revocation_fence``)
and against real PostgreSQL
(``tests/prod_equivalent/test_real_stack_rights_revocation_fence.py``), where the
fence is a session-level advisory lock rather than an asyncio lock.

Invariant under test: once a revocation has returned, no raw record is retained
for that grant, and a revocation never commits between a writer's final grant
check and its Bronze insert.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from repositories.lake import BronzeRepository
from services.integrations.data_rights.models import (
    DataRightsGrantCreate,
    DataRightsGrantRevoke,
    GrantStatus,
)
from services.provider_runtime.raw_store import RawProviderRecordStore
from services.provider_runtime.rights_admission import (
    ProviderRawRightsAdmission,
    ProviderRawRightsDenied,
    ProviderRawRightsEvidence,
    provider_account_source_id,
)
from shared.integration_contracts.events import make_raw_record

PROVIDER = "shopify.orders.catalog"
CONNECTION = "connection-fence"
ACCOUNT = "shop-fence"


class FencedAdmission(ProviderRawRightsAdmission):
    """Real ``hold_grant`` fence; the allow decision itself is stubbed.

    ``after_admit`` runs between the allow decision and the write, which is the
    window the fence has to close.
    """

    def __init__(self, grant, *, after_admit: Optional[Callable[[Any], Awaitable[None]]] = None, **kw):
        super().__init__(**kw)
        self._grant = grant
        self.after_admit = after_admit

    async def admit(self, record):
        evidence = ProviderRawRightsEvidence(
            tenant_id=record.tenant_id,
            source_id=self._grant.source_id,
            source_grant_ref=self._grant.data_rights_grant_id,
            rights_decision_ref=f"rdec_{record.idempotency_key}",
            decision_identity=f"rdid_{record.idempotency_key}",
            policy_version="irrl-2",
            evaluated_at="2026-10-09T00:00:00+00:00",
        )
        if self.after_admit is not None:
            await self.after_admit(record)
        return evidence

    async def verify_persisted(self, record, *, current_admission):
        return None


@dataclass
class Env:
    service: Any  # DataRightsService bound to the store under test
    tenant: str

    def record(self, n: int):
        return make_raw_record(
            provider_identity=PROVIDER,
            provider_record_id=f"order-{n}",
            provider_record_type="order",
            tenant_id=self.tenant,
            connection_id=CONNECTION,
            account_id=ACCOUNT,
            stream_id="orders",
            payload={"id": f"order-{n}"},
        )

    async def grant(self):
        return await self.service.create_grant(
            DataRightsGrantCreate(
                tenant_id=self.tenant,
                source_id=provider_account_source_id(CONNECTION, ACCOUNT),
                connector_id=PROVIDER,
                connector_class="tenant_byod_data",
                data_category="customer",
                data_sensitivity="sensitive_pii",
                raw_data_owner="tenant",
                tenant_lake_allowed=True,
            ),
            "tenant-admin",
        )

    async def revoke(self, grant):
        return await self.service.revoke_grant(
            grant.data_rights_grant_id,
            DataRightsGrantRevoke(revocation_reason="fence test", revoked_by_user_id="tenant-admin"),
            tenant_id=self.tenant,
        )

    async def rows(self) -> int:
        return await BronzeRepository("provider_records").count(
            filters={"tenant_id": self.tenant, "source": PROVIDER}
        )

    def store(self, admission, repository=None):
        return RawProviderRecordStore(
            repository=repository or BronzeRepository("provider_records"),
            rights_admission=admission,
        )


def new_tenant() -> str:
    return f"tenant-fence-{uuid.uuid4().hex[:12]}"


async def revocation_waits_for_an_in_flight_write(env: Env) -> None:
    """A write that already holds the grant finishes first; revocation waits for it."""
    grant = await env.grant()
    entered, gate = asyncio.Event(), asyncio.Event()

    class Gated(BronzeRepository):
        async def ingest(self, **kwargs):
            entered.set()
            await gate.wait()
            return await super().ingest(**kwargs)

    store = env.store(
        FencedAdmission(grant, grant_service=env.service),
        repository=Gated("provider_records"),
    )
    writer = asyncio.create_task(store.ingest([env.record(1)]))
    await asyncio.wait_for(entered.wait(), 10)

    revoker = asyncio.create_task(env.revoke(grant))
    await asyncio.sleep(0.3)
    assert not revoker.done(), "revocation committed while a write held the grant"

    gate.set()
    outcomes = await asyncio.wait_for(writer, 10)
    revoked = await asyncio.wait_for(revoker, 10)
    assert outcomes[0][1] is True
    assert revoked.status == GrantStatus.REVOKED
    assert await env.rows() == 1


async def a_write_after_a_committed_revocation_is_denied(env: Env) -> None:
    """Admitted, then revoked before the write: the write is refused and retains nothing."""
    grant = await env.grant()
    admitted, release = asyncio.Event(), asyncio.Event()

    async def pause(_record):
        admitted.set()
        await release.wait()

    store = env.store(FencedAdmission(grant, after_admit=pause, grant_service=env.service))
    writer = asyncio.create_task(store.ingest([env.record(1)]))
    await asyncio.wait_for(admitted.wait(), 10)

    revoked = await asyncio.wait_for(env.revoke(grant), 10)
    assert revoked.status == GrantStatus.REVOKED

    release.set()
    try:
        await asyncio.wait_for(writer, 10)
    except ProviderRawRightsDenied:
        pass
    else:
        raise AssertionError("a record was retained after its grant was revoked")
    assert await env.rows() == 0


async def no_record_is_retained_after_revocation_returns(env: Env) -> None:
    """Racing writers: whatever is stored when revoke returns is all that is ever stored."""
    grant = await env.grant()

    async def delay(record):
        # Early records reach the write before the revocation; late ones after it.
        n = int(record.provider_record_id.split("-")[1])
        await asyncio.sleep(0 if n < 6 else 0.4)

    store = env.store(FencedAdmission(grant, after_admit=delay, grant_service=env.service))
    writers = [asyncio.create_task(store.ingest([env.record(n)])) for n in range(12)]
    await asyncio.sleep(0.15)
    revoked = await asyncio.wait_for(env.revoke(grant), 20)
    assert revoked.status == GrantStatus.REVOKED
    stored_at_revoke = await env.rows()

    results = await asyncio.wait_for(asyncio.gather(*writers, return_exceptions=True), 30)
    succeeded = [r for r in results if not isinstance(r, BaseException)]
    denied = [r for r in results if isinstance(r, ProviderRawRightsDenied)]
    unexpected = [r for r in results if isinstance(r, BaseException) and not isinstance(r, ProviderRawRightsDenied)]
    assert not unexpected, unexpected

    assert await env.rows() == stored_at_revoke, "a record was retained after the revocation returned"
    assert len(succeeded) == stored_at_revoke
    assert len(succeeded) + len(denied) == 12
    assert denied, "the late writers should have been refused"


ALL = (
    revocation_waits_for_an_in_flight_write,
    a_write_after_a_committed_revocation_is_denied,
    no_record_is_retained_after_revocation_returns,
)
