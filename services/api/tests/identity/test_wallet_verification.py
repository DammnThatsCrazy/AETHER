from __future__ import annotations

import base64
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from dataclasses import replace

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from nacl.signing import SigningKey  # noqa: E402

from identity.identity import verification as verification_module  # noqa: E402
from governance.consent import authority  # noqa: E402
from identity.identity import routes as identity_routes  # noqa: E402
from identity.identity.audit import IdentityAuditWriter  # noqa: E402
from identity.identity.conflicts import IdentityConflictManager  # noqa: E402
from identity.identity.evidence import EvidenceService  # noqa: E402
from identity.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from identity.identity.hashing import (  # noqa: E402
    decrypt_wallet_subject_binding,
    hash_wallet,
)
from identity.identity.metrics import IdentityMetrics  # noqa: E402
from identity.identity.models import (  # noqa: E402
    ConfidenceTier,
    EntityType,
    IdentitySignalType,
    VerificationChallenge,
    VerificationChallengeState,
    VerificationMethod,
)
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from identity.identity.resolution_replay import ResolutionReplayService  # noqa: E402
from identity.identity.resolver import IdentityResolutionService  # noqa: E402
from identity.identity.verification import WalletVerificationService  # noqa: E402
from identity.identity.verification_repository import (  # noqa: E402
    VerificationChallengeRepository,
    VerificationEvidenceRepository,
)
from identity.identity.schemas import (  # noqa: E402
    WalletVerificationChallengeRequest,
    WalletVerificationSignatureRequest,
)
from repositories.repos import reset_in_memory_stores  # noqa: E402
from config.settings import settings  # noqa: E402


class MemoryChallengeRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def create(self, challenge):
        self.rows[challenge.id] = challenge.to_record()
        return self.rows[challenge.id]

    async def get_for_tenant(self, tenant_id: str, challenge_id: str):
        row = self.rows.get(challenge_id)
        if row is None or row.get("tenant_id") != tenant_id:
            return None
        return dict(row)

    async def increment_attempt(self, tenant_id: str, challenge_id: str):
        row = await self.get_for_tenant(tenant_id, challenge_id)
        if row is None:
            return None
        row["attempt_count"] = int(row.get("attempt_count", 0)) + 1
        if row["attempt_count"] >= int(row.get("max_attempts", 5)):
            row["state"] = "locked"
        self.rows[challenge_id] = row
        return dict(row)

    async def record_failed_attempt(self, tenant_id: str, challenge_id: str):
        row = await self.get_for_tenant(tenant_id, challenge_id)
        if row is None or row.get("state") != "issued":
            return None
        attempts = int(row.get("attempt_count", 0))
        if attempts >= int(row.get("max_attempts", 5)):
            return None
        row["attempt_count"] = attempts + 1
        if row["attempt_count"] >= int(row.get("max_attempts", 5)):
            row["state"] = "locked"
        self.rows[challenge_id] = row
        return dict(row)

    async def consume_wallet_atomic(self, tenant_id: str, challenge_id: str):
        row = await self.get_for_tenant(tenant_id, challenge_id)
        if row is None or row.get("state") != "issued":
            return None
        attempts = int(row.get("attempt_count", 0))
        if attempts >= int(row.get("max_attempts", 5)):
            return None
        row.update(
            state="consumed",
            attempt_count=attempts + 1,
            consumed_at="2026-10-15T12:00:00+00:00",
        )
        self.rows[challenge_id] = row
        return dict(row)

    async def apply_update(self, tenant_id: str, challenge_id: str, fields: dict):
        row = await self.get_for_tenant(tenant_id, challenge_id)
        if row is None:
            return None
        row.update(fields)
        self.rows[challenge_id] = row
        return dict(row)

    async def consume_atomic(self, tenant_id: str, challenge_id: str):
        row = await self.get_for_tenant(tenant_id, challenge_id)
        if row is None or row.get("state") != "validated":
            return None
        row.update(state="consumed", consumed_at="2026-10-15T12:00:00+00:00")
        self.rows[challenge_id] = row
        return dict(row)


class MemoryEvidenceService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def issue_evidence(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="evidence-1")


class MemoryVerificationEvidenceRepository:
    async def create(self, evidence):
        return evidence.to_record()


class ReplaySpy:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result or {"status": "complete"}

    async def request_replay(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)


class FakeTenant:
    tenant_id = "tenant-route"
    site_ids = ["app-a"]

    def require_permission(self, permission: str) -> None:
        assert permission == "write"


class FakeRequest:
    state = SimpleNamespace(tenant=FakeTenant())


def _service():
    challenges = MemoryChallengeRepository()
    evidence = MemoryEvidenceService()
    return WalletVerificationService(challenges, evidence), challenges, evidence


@pytest.mark.asyncio
async def test_eip191_proof_is_tenant_and_subject_bound_and_single_use():
    service, challenges, evidence = _service()
    account = Account.create()
    issued = await service.issue_wallet_challenge(
        tenant_id="tenant-a",
        anonymous_id="anon-1",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        consent_snapshot={"receipt_id": "receipt-1"},
    )
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), account.key
    ).signature.hex()

    result = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-1",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
        consent_snapshot={"receipt_id": "receipt-1"},
    )

    assert result == {"status": "verified", "evidence_id": "evidence-1"}
    assert challenges.rows[issued["challenge_id"]]["state"] == "consumed"
    assert evidence.calls[0]["identifier_type"] == "wallet"
    assert evidence.calls[0]["verification_method"] == "wallet_signature"
    assert evidence.calls[0]["evidence_type"] == "wallet_ownership_verified"
    assert evidence.calls[0]["consent_snapshot"] == {"receipt_id": "receipt-1"}
    assert evidence.calls[0]["subject_hint_id"] == "anon-1"
    assert await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-1",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
    ) == {"status": "invalid_state", "state": "consumed"}
    assert len(evidence.calls) == 1


@pytest.mark.asyncio
async def test_solana_proof_checks_exact_ed25519_message():
    service, _, evidence = _service()
    key = SigningKey.generate()
    address = verification_module._base58_encode(bytes(key.verify_key))
    issued = await service.issue_wallet_challenge(
        tenant_id="tenant-a",
        anonymous_id="anon-2",
        wallet_address=address,
        chain_namespace="solana:mainnet",
    )
    signature = base64.b64encode(
        key.sign(issued["message"].encode("utf-8")).signature
    ).decode("ascii")

    result = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-2",
        wallet_address=address,
        chain_namespace="solana:mainnet",
        signature=signature,
    )

    assert result["status"] == "verified"
    assert evidence.calls[0]["metadata"] == {"chain_namespace": "solana:mainnet"}


@pytest.mark.asyncio
async def test_wrong_subject_tenant_expiry_and_unsupported_network_fail_closed(monkeypatch):
    current = [datetime(2026, 10, 15, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(verification_module, "utc_now", lambda: current[0])
    service, _, evidence = _service()
    account = Account.create()
    issued = await service.issue_wallet_challenge(
        tenant_id="tenant-a",
        anonymous_id="anon-3",
        wallet_address=account.address,
        chain_namespace="eip155:1",
    )
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), account.key
    ).signature.hex()

    wrong_subject = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-other",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
    )
    other_tenant = await service.verify_wallet_signature(
        tenant_id="tenant-b",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-3",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
    )
    current[0] += timedelta(seconds=301)
    expired = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-3",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
    )

    assert wrong_subject == {"status": "invalid"}
    assert other_tenant == {"status": "not_found"}
    assert expired == {"status": "expired"}
    assert evidence.calls == []
    with pytest.raises(ValueError, match="unsupported wallet proof network"):
        await service.issue_wallet_challenge(
            tenant_id="tenant-a",
            anonymous_id="anon-4",
            wallet_address="0x1234",
            chain_namespace="sui:mainnet",
        )


@pytest.mark.asyncio
async def test_valid_signature_succeeds_on_the_final_configured_attempt():
    service, challenges, _ = _service()
    account = Account.create()
    issued = await service.issue_wallet_challenge(
        tenant_id="tenant-a",
        anonymous_id="anon-final-attempt",
        wallet_address=account.address,
        chain_namespace="eip155:1",
    )
    challenges.rows[issued["challenge_id"]]["max_attempts"] = 2
    invalid = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-final-attempt",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature="not-a-signature",
    )
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), account.key
    ).signature.hex()

    final_attempt = await service.verify_wallet_signature(
        tenant_id="tenant-a",
        challenge_id=issued["challenge_id"],
        anonymous_id="anon-final-attempt",
        wallet_address=account.address,
        chain_namespace="eip155:1",
        signature=signature,
    )

    assert invalid == {"status": "invalid"}
    assert final_attempt["status"] == "verified"
    assert challenges.rows[issued["challenge_id"]]["attempt_count"] == 2
    assert challenges.rows[issued["challenge_id"]]["state"] == "consumed"


@pytest.mark.asyncio
async def test_wallet_evidence_forwards_chain_and_subject_scope_to_replay():
    replay = ReplaySpy()
    evidence_service = EvidenceService(
        repo=MemoryVerificationEvidenceRepository(), replay_service=replay
    )

    await evidence_service.issue_evidence(
        tenant_id="tenant-a",
        identifier_type="wallet",
        identifier_hash="wallet-hash",
        verification_method="wallet_signature",
        evidence_type="wallet_ownership_verified",
        challenge_id="challenge-1",
        subject_hint_id="anon-1",
        consent_snapshot={"purposes": {"identity": True}},
        metadata={"chain_namespace": "eip155:1"},
    )

    assert replay.calls[0]["identifier_type"] == "wallet"
    assert replay.calls[0]["chain_namespace"] == "eip155:1"
    assert replay.calls[0]["subject_hint_id"] == "anon-1"


@pytest.mark.asyncio
async def test_challenge_consume_is_single_use_under_concurrent_requests():
    reset_in_memory_stores()
    challenge_id = "challenge-concurrent-consume"
    first_repo = VerificationChallengeRepository()
    await first_repo.create(VerificationChallenge(
        id=challenge_id,
        tenant_id="tenant-a",
        identifier_type="wallet",
        identifier_hash="wallet-hash",
        method=VerificationMethod.WALLET_SIGNATURE.value,
        state=VerificationChallengeState.VALIDATED.value,
    ))
    second_repo = VerificationChallengeRepository()

    first, second = await asyncio.gather(
        first_repo.consume_atomic("tenant-a", challenge_id),
        second_repo.consume_atomic("tenant-a", challenge_id),
    )

    assert sum(result is not None for result in (first, second)) == 1
    stored = await first_repo.get_for_tenant("tenant-a", challenge_id)
    assert stored["state"] == VerificationChallengeState.CONSUMED.value


@pytest.mark.asyncio
async def test_wallet_routes_recheck_server_consent_and_bind_verify_path(monkeypatch):
    consent_context = {
        "authority": "server_consent_receipt",
        "receipt_id": "receipt-opaque",
        "purposes": {"identity": True},
    }
    calls: list[tuple[str, str]] = []

    async def allowed(tenant_id: str, anonymous_id: str):
        calls.append((tenant_id, anonymous_id))
        return True, None, consent_context

    class Service:
        calls: list[dict] = []

        async def issue_wallet_challenge(self, **kwargs):
            self.calls.append(kwargs)
            return {"challenge_id": "wvc-1", "consent": kwargs["consent_snapshot"]}

        async def verify_wallet_signature(self, **kwargs):
            self.calls.append(kwargs)
            return {"status": "verified", "consent": kwargs["consent_snapshot"]}

    monkeypatch.setattr(
        settings,
        "identity_continuity",
        replace(settings.identity_continuity, resolution_enabled=True),
    )
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", allowed)
    monkeypatch.setattr(identity_routes, "_get_wallet_verification_service", Service)
    wallet_address = Account.create().address

    issued = await identity_routes.issue_wallet_verification_challenge(
        WalletVerificationChallengeRequest(
            anonymous_id="anon-1",
            tenant_app_key="app-a",
            wallet_address=wallet_address,
            chain_namespace="eip155:1",
        ),
        FakeRequest(),
    )
    verified = await identity_routes.verify_wallet_verification_challenge(
        "wvc-1",
        WalletVerificationSignatureRequest(
            challenge_id="wvc-1",
            anonymous_id="anon-1",
            tenant_app_key="app-a",
            wallet_address=wallet_address,
            chain_namespace="eip155:1",
            signature="signature",
        ),
        FakeRequest(),
    )

    assert issued["data"]["consent"] == consent_context
    assert verified["data"]["consent"] == consent_context
    assert [call["identity_namespace"] for call in Service.calls] == [
        "app-a",
        "app-a",
    ]
    assert calls == [("tenant-route", "anon-1"), ("tenant-route", "anon-1")]


@pytest.mark.asyncio
async def test_wallet_evidence_retry_recovers_subject_and_binds_entity_after_reload(
    monkeypatch,
):
    reset_in_memory_stores()
    monkeypatch.setenv("IDENTITY_VERIFICATION_TOKEN_KEY", "wallet-binding-test-key")
    tenant_id = "tenant-durable-wallet"
    subject_id = "anon-recover-after-reload"
    evidence_repo = VerificationEvidenceRepository()
    first_replay = ReplaySpy({"status": "error", "error": "resolver unavailable"})
    evidence_service = EvidenceService(repo=evidence_repo, replay_service=first_replay)

    evidence = await evidence_service.issue_evidence(
        tenant_id=tenant_id,
        identifier_type="wallet",
        identifier_hash="wallet-hash",
        verification_method="wallet_signature",
        evidence_type="wallet_ownership_verified",
        subject_hint_id=subject_id,
        identity_namespace="app-a",
        consent_snapshot={"receipt_id": "receipt-1"},
        metadata={"chain_namespace": "eip155:1"},
    )
    persisted = await VerificationEvidenceRepository().get_for_tenant(
        tenant_id, evidence.id
    )
    assert persisted is not None
    assert persisted["subject_hint_ciphertext"]
    assert subject_id not in str(persisted)
    assert decrypt_wallet_subject_binding(
        persisted["subject_hint_ciphertext"], "tenant-other"
    ) == ""

    retry_replay = ReplaySpy(
        {"status": "complete", "canonical_entity_id": "entity-wallet-recovered"}
    )
    # A new service and repository instance model a process restart.
    restarted_service = EvidenceService(
        repo=VerificationEvidenceRepository(), replay_service=retry_replay
    )
    result = await restarted_service.retry_evidence_replay(tenant_id, evidence.id)

    assert result["status"] == "complete"
    assert retry_replay.calls[0]["subject_hint_id"] == subject_id
    assert retry_replay.calls[0]["identity_namespace"] == "app-a"
    assert retry_replay.calls[0]["chain_namespace"] == "eip155:1"
    rebound = await VerificationEvidenceRepository().get_for_tenant(
        tenant_id, evidence.id
    )
    assert rebound["canonical_entity_id"] == "entity-wallet-recovered"


@pytest.mark.asyncio
async def test_wallet_signature_challenge_consumption_is_atomic_under_concurrency(
    monkeypatch,
):
    reset_in_memory_stores()
    monkeypatch.setenv("IDENTITY_VERIFICATION_TOKEN_KEY", "wallet-binding-test-key")
    evidence = MemoryEvidenceService()
    service = WalletVerificationService(VerificationChallengeRepository(), evidence)
    account = Account.create()
    issued = await service.issue_wallet_challenge(
        tenant_id="tenant-concurrent-wallet",
        anonymous_id="anon-concurrent-wallet",
        wallet_address=account.address,
        chain_namespace="eip155:1",
    )
    signature = Account.sign_message(
        encode_defunct(text=issued["message"]), account.key
    ).signature.hex()

    results = await asyncio.gather(*(
        service.verify_wallet_signature(
            tenant_id="tenant-concurrent-wallet",
            challenge_id=issued["challenge_id"],
            anonymous_id="anon-concurrent-wallet",
            wallet_address=account.address,
            chain_namespace="eip155:1",
            signature=signature,
        )
        for _ in range(2)
    ))

    statuses = [result["status"] for result in results]
    assert statuses.count("verified") == 1
    assert next(status for status in statuses if status != "verified") in {
        "already_consumed",
        "invalid_state",
    }
    assert len(evidence.calls) == 1


@pytest.mark.asyncio
async def test_wallet_evidence_replay_binds_proof_to_consented_anonymous_subject():
    reset_in_memory_stores()
    tenant_id = "tenant-wallet-replay"
    subject_id = "anon-wallet-proof"
    wallet_address = Account.create().address
    chain_namespace = "eip155:1"
    wallet_hash = hash_wallet(wallet_address, chain_namespace)

    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    entity_id = "entity-wallet-proof"
    await repo.create_subject(tenant_id, entity_id, EntityType.ANONYMOUS_VISITOR)
    await repo.upsert_alias(
        tenant_id,
        entity_id,
        IdentitySignalType.ANONYMOUS_ID,
        subject_id,
        confidence_tier=ConfidenceTier.STRONG,
    )
    replay = ResolutionReplayService(resolver=resolver, repo=repo)

    result = await replay.request_replay(
        tenant_id=tenant_id,
        identifier_type="wallet",
        identifier_hash=wallet_hash,
        chain_namespace=chain_namespace,
        subject_hint_id=subject_id,
        trigger_type="wallet_verification_evidence",
        trigger_id="wallet-evidence-1",
        consent_snapshot={"purposes": {"identity": True}},
    )

    assert result["status"] == "complete"
    aliases = await repo.get_aliases_for_entity(tenant_id, entity_id)
    assert any(
        alias.get("alias_type") == IdentitySignalType.WALLET_SIGNATURE_VERIFIED.value
        and alias.get("alias_value_hash") == wallet_hash
        for alias in aliases
    )

    missing_binding = await replay.request_replay(
        tenant_id=tenant_id,
        identifier_type="wallet",
        identifier_hash=hash_wallet(Account.create().address, chain_namespace),
        chain_namespace=chain_namespace,
        trigger_type="wallet_verification_evidence",
        trigger_id="wallet-evidence-unbound",
        consent_snapshot={"purposes": {"identity": True}},
    )
    assert missing_binding["status"] == "error"
