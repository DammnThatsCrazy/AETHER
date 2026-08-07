"""Mobile plane reachable by a DSR erasure, end-to-end, with real evidence.

Seeds a continuation (+ selection), an installation (+ push subscription), a
sync_change_log row, and the three kyber device stores (trusted device, WebAuthn
credential, device proof key) for one subject, then runs the ``consent.erasure``
handler and asserts all six ``dsr_propagation`` components are marked ``completed``
with each store's OWN real erased-row count — and that the rows are actually gone.

A forced per-store failure must mark only that one component ``failed`` (isolated),
leave the other components ``completed``, and keep the whole job retryable
(handler returns ``failed`` so the worker re-runs the idempotent erasure).
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.client_sync_repo import (
    get_client_sync_repository,
    reset_client_sync_memory,
)
from repositories.continuation_repo import (
    get_continuation_repository,
    reset_continuation_memory,
)
from repositories.installation_repo import (
    get_installation_repository,
    reset_installation_memory,
)
from repositories.jobs_repo import reset_jobs_memory
from repositories.repos import reset_in_memory_stores

from services.client_sync import service as client_sync_service
from services.consent.erasure_jobs import ERASURE_JOB_TYPE, register_consent_erasure_handler
from services.dsr_propagation.service import dsr_propagation_service
from services.jobs.handlers import HANDLER_REGISTRY, JobContext
from services.kyber.access.contracts import (
    DeviceProofKey,
    TrustedDevice,
    WebAuthnCredential,
)
from services.kyber.devices.repository import (
    DeviceProofKeyRepository,
    TrustedDeviceRepository,
    WebAuthnCredentialRepository,
)
from services.measurement import privacy as privacy_mod
from services.mobile import service as mobile_service

pytestmark = pytest.mark.asyncio

TENANT = "tenant-mobile-dsr"
USER = "subject-to-erase"
SCOPE = mobile_service.tenant_scope(TENANT)  # "t:{tenant_id}"
JOB_ID = "job_mobile_dsr"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    reset_in_memory_stores()
    reset_jobs_memory()
    reset_continuation_memory()
    reset_installation_memory()
    reset_client_sync_memory()
    register_consent_erasure_handler()
    # Neutralize the measurement erasure so the test isolates the mobile plane.
    monkeypatch.setattr(
        privacy_mod._touchpoint_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    monkeypatch.setattr(
        privacy_mod._conversion_repo, "tombstone_for_profile", AsyncMock(return_value=0)
    )
    from services.measurement.engine.journey_compiler import JourneyCompiler

    monkeypatch.setattr(
        JourneyCompiler, "rebuild_affected_by_consent_change", AsyncMock(return_value=None)
    )
    yield
    reset_in_memory_stores()
    reset_jobs_memory()
    reset_continuation_memory()
    reset_installation_memory()
    reset_client_sync_memory()


async def _seed_mobile_data() -> None:
    """Seed the DSR-reachable principal-scoped rows for the subject: 2
    continuation rows (1 continuation + 1 selection), 2 installation rows
    (1 installation + 1 push subscription), 1 sync_change_log row, and 3 kyber
    device rows (trusted device + WebAuthn credential + device proof key)."""
    cont_repo = get_continuation_repository()
    await cont_repo.create(
        tenant_scope=SCOPE, continuation_id="cont_x", principal_id=USER,
        app_kind="aether", source_client="mobile", surface="graph",
        sensitivity="standard", freshness="live", context={"id": "cont_x"},
    )
    await cont_repo.create_selection(
        tenant_scope=SCOPE, principal_id=USER, mode="explicit",
        selection={"resource_ids": ["a"]},
    )

    inst_repo = get_installation_repository()
    await inst_repo.register(
        tenant_scope=SCOPE, principal_id=USER, installation_id="inst_x",
        app_kind="aether", platform="ios", bundle_id="com.aether.app",
        environment="production", device_name="iPhone",
    )
    await inst_repo.add_subscription(
        tenant_scope=SCOPE, installation_id="inst_x", principal_id=USER,
        platform="ios", provider="apns", token_hash="tok", environment="production",
    )

    await get_client_sync_repository().enqueue(
        scope_key=SCOPE, principal_id=USER, change_type="continuation_changed",
        resource_kind="continuation", resource_id="cont_x", revision="1",
    )

    # Kyber device plane — operator-keyed, one row per store (M8-E1). The DSR
    # subject doubles as the operator id so the erasure job reaches these stores.
    await TrustedDeviceRepository().save(
        TrustedDevice(
            operator_id=USER,
            device_id="dev_dsr_1",
            display_name="DSR test device",
            platform_family="mobile",
            approval_state="approved",
            risk_state="ok",
        )
    )
    await WebAuthnCredentialRepository().save(
        WebAuthnCredential(
            device_id="dev_dsr_1",
            operator_id=USER,
            credential_id="cred_dsr_1",
            public_key="cHJvZmUta2V5LTA=",
        )
    )
    await DeviceProofKeyRepository().save(
        DeviceProofKey(
            device_id="dev_dsr_1",
            operator_id=USER,
            public_key="cHJvZmUta2V5LTA=",
        )
    )


async def _open_propagation() -> str:
    return await dsr_propagation_service.open_request(TENANT, f"user:{USER}", "erasure")


def _ctx() -> JobContext:
    return JobContext(
        job_id=JOB_ID,
        tenant_id=TENANT,
        correlation_id="corr",
        worker_id="test_worker",
        heartbeat=AsyncMock(return_value=True),
        emit_event=AsyncMock(return_value=None),
    )


async def _run_handler(propagation_id: str):
    handler = HANDLER_REGISTRY[ERASURE_JOB_TYPE]
    return await handler(
        {"user_id": USER, "propagation_request_id": propagation_id}, _ctx()
    )


async def test_mobile_stores_erased_with_real_evidence():
    await _seed_mobile_data()
    propagation_id = await _open_propagation()

    outcome = await _run_handler(propagation_id)
    assert outcome.status == "succeeded"

    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    by_comp = {c["component"]: c for c in status["components"]}

    # Each mobile component is completed WITH its store's own real erased-row count.
    assert by_comp["continuation_records"]["status"] == "completed"
    assert by_comp["continuation_records"]["records_impacted"] == 2  # continuation + selection
    assert by_comp["mobile_installations"]["status"] == "completed"
    assert by_comp["mobile_installations"]["records_impacted"] == 2  # installation + subscription
    assert by_comp["client_sync_records"]["status"] == "completed"
    assert by_comp["client_sync_records"]["records_impacted"] == 1  # one change-log row
    # Each kyber device store is completed WITH its own real erased-row count.
    assert by_comp["kyber_trusted_devices"]["status"] == "completed"
    assert by_comp["kyber_trusted_devices"]["records_impacted"] == 1  # one trusted device
    assert by_comp["kyber_webauthn_credentials"]["status"] == "completed"
    assert by_comp["kyber_webauthn_credentials"]["records_impacted"] == 1  # one credential
    assert by_comp["kyber_device_proof_keys"]["status"] == "completed"
    assert by_comp["kyber_device_proof_keys"]["records_impacted"] == 1  # one proof key
    # The durable job id is the audit pointer for each store's execution.
    for comp in (
        "continuation_records", "mobile_installations", "client_sync_records",
        "kyber_trusted_devices", "kyber_webauthn_credentials", "kyber_device_proof_keys",
    ):
        assert by_comp[comp]["audit_event_id"] == JOB_ID

    # The rows are actually gone from every mobile store.
    assert await get_continuation_repository().list_recent(SCOPE, USER) == []
    assert await get_installation_repository().list_for_principal(SCOPE, USER) == []
    assert await get_client_sync_repository().read_since(SCOPE, 0, 200) == []
    # ...and from every kyber device store.
    assert await TrustedDeviceRepository().find_by_operator(USER) == []
    assert await WebAuthnCredentialRepository().find_by_operator(USER) == []
    assert await DeviceProofKeyRepository().find_by_operator(USER) == []


async def test_per_store_failure_is_isolated_and_retryable(monkeypatch):
    await _seed_mobile_data()
    propagation_id = await _open_propagation()

    # Force ONLY the client-sync store to fail; the others must still complete.
    monkeypatch.setattr(
        client_sync_service,
        "erase_principal",
        AsyncMock(side_effect=RuntimeError("sync store down")),
    )

    outcome = await _run_handler(propagation_id)
    # A per-store failure fails the attempt so the worker retries the idempotent job.
    assert outcome.status == "failed"
    assert "sync store down" in (outcome.error or "")

    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    by_comp = {c["component"]: c for c in status["components"]}

    # The failed store is honestly marked failed; the others are untouched-completed.
    assert by_comp["client_sync_records"]["status"] == "failed"
    assert by_comp["continuation_records"]["status"] == "completed"
    assert by_comp["continuation_records"]["records_impacted"] == 2
    assert by_comp["mobile_installations"]["status"] == "completed"
    assert by_comp["mobile_installations"]["records_impacted"] == 2
    # The kyber device stores also completed — they never depended on client-sync.
    assert by_comp["kyber_trusted_devices"]["status"] == "completed"
    assert by_comp["kyber_trusted_devices"]["records_impacted"] == 1
    assert by_comp["kyber_webauthn_credentials"]["status"] == "completed"
    assert by_comp["kyber_webauthn_credentials"]["records_impacted"] == 1
    assert by_comp["kyber_device_proof_keys"]["status"] == "completed"
    assert by_comp["kyber_device_proof_keys"]["records_impacted"] == 1
    # Fail-closed roll-up surfaces the failure.
    assert status["overall"] == "failed"

    # The stores that succeeded really were erased; the failed store's row remains
    # (so the retry can finish erasing it).
    assert await get_continuation_repository().list_recent(SCOPE, USER) == []
    assert await get_installation_repository().list_for_principal(SCOPE, USER) == []
    assert await get_client_sync_repository().read_since(SCOPE, 0, 200) != []
    assert await TrustedDeviceRepository().find_by_operator(USER) == []
    assert await WebAuthnCredentialRepository().find_by_operator(USER) == []
    assert await DeviceProofKeyRepository().find_by_operator(USER) == []


async def test_kyber_device_failure_is_isolated_and_retryable(monkeypatch):
    """A failing kyber device store marks ONLY that component failed.

    The three kyber device stores are erased independently (M8-E1): a proof-key
    store failure must not block the trusted-device / WebAuthn erasures, and the
    whole job stays retryable so the worker can finish the failed store.
    """
    await _seed_mobile_data()
    propagation_id = await _open_propagation()

    # Force ONLY the proof-key store to fail; the sibling device stores must
    # still complete (each component carries its OWN real receipt).
    monkeypatch.setattr(
        DeviceProofKeyRepository,
        "delete_by_operator",
        AsyncMock(side_effect=RuntimeError("proof store down")),
    )

    outcome = await _run_handler(propagation_id)
    assert outcome.status == "failed"
    assert "proof store down" in (outcome.error or "")

    status = await dsr_propagation_service.status(propagation_id, tenant_id=TENANT)
    by_comp = {c["component"]: c for c in status["components"]}

    assert by_comp["kyber_device_proof_keys"]["status"] == "failed"
    assert by_comp["kyber_trusted_devices"]["status"] == "completed"
    assert by_comp["kyber_trusted_devices"]["records_impacted"] == 1
    assert by_comp["kyber_webauthn_credentials"]["status"] == "completed"
    assert by_comp["kyber_webauthn_credentials"]["records_impacted"] == 1
    assert by_comp["continuation_records"]["status"] == "completed"
    assert by_comp["mobile_installations"]["status"] == "completed"
    assert by_comp["client_sync_records"]["status"] == "completed"
    assert status["overall"] == "failed"

    # The failing proof-key row remains for the retry; the sibling device rows
    # and the mobile-plane rows really are gone.
    assert await TrustedDeviceRepository().find_by_operator(USER) == []
    assert await WebAuthnCredentialRepository().find_by_operator(USER) == []
    assert await DeviceProofKeyRepository().find_by_operator(USER) != []
    assert await get_continuation_repository().list_recent(SCOPE, USER) == []
    assert await get_installation_repository().list_for_principal(SCOPE, USER) == []
    assert await get_client_sync_repository().read_since(SCOPE, 0, 200) == []
