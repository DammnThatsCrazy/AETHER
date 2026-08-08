"""Credential authority domain generalization — P3 invariants.

The credential authority is now the ONLY secret authority for reward signing,
the reward webhook secret, and (later) x402/RPC — not payments alone. These
tests pin:

* the merged slot registry (payment adapters + static reward domain sources),
  with globally-unique provider names and correct domain partitioning;
* tenant reward-signer resolution: credential-authority first, local-only env
  bootstrap, fail-closed everywhere else;
* the reward webhook secret dual-write → secret_ref → send-time resolution
  round-trip (no plaintext in the ref);
* credential rotation/revocation propagating to the capability lifecycle
  authority as demotions.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import uuid

import pytest

from repositories.repos import reset_in_memory_stores
from services.providers.credentials.authority import credential_authority
from services.providers.credentials.schema import CREDENTIAL_DOMAINS, CredentialDomain
from services.providers.credentials.slot_registry import (
    build_slot_registry,
    providers_for_domain,
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── Merged registry / domain partition ────────────────────────────────────


def test_domains_declared():
    assert CredentialDomain.SIGNING in CREDENTIAL_DOMAINS
    assert CredentialDomain.REWARDS in CREDENTIAL_DOMAINS
    assert CredentialDomain.PAYMENTS == "payments"


def test_reward_domain_slots_present_and_partitioned():
    reg = build_slot_registry()
    assert "reward_signer" in reg
    assert "tenant_webhook" in reg
    signer_slots = {s.slot_name for s in reg["reward_signer"]}
    assert signer_slots == {"evm_reward_signer_key", "svm_reward_signer_key"}
    assert providers_for_domain("signing") == ("reward_signer",)
    assert providers_for_domain("rewards") == ("tenant_webhook",)
    # no provider is claimed by two static sources (build would raise) and
    # payment providers are unchanged
    assert "stripe" in providers_for_domain("payments")


def test_signer_slot_validation_strategy_is_key_derivation():
    reg = build_slot_registry()
    for slot in reg["reward_signer"]:
        assert slot.validation_strategy == "key_derivation_check"
        assert slot.secret_type == "signing_private_key"
    # evm required, svm optional (SVM rail is explicit-beta)
    by_name = {s.slot_name: s for s in reg["reward_signer"]}
    assert by_name["evm_reward_signer_key"].required is True
    assert by_name["svm_reward_signer_key"].required is False


# ── Signer resolution ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_signer_resolves_from_authority():
    from services.rewards.signing import resolve_reward_signer

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    key = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff81"
    pending = await credential_authority.create_pending(
        tenant, "reward_signer", "sandbox", "evm_reward_signer_key", key, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "reward_signer", "sandbox", "evm_reward_signer_key",
        credential_version=int(pending["credential_version"]), actor="admin",
    )
    resolved = await resolve_reward_signer(tenant, "sandbox", "evm")
    assert resolved == key


@pytest.mark.asyncio
async def test_signer_local_bootstrap_when_no_credential(monkeypatch):
    from services.rewards.signing import resolve_reward_signer

    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("ORACLE_SIGNER_KEY", "deadbeef" * 8)
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    resolved = await resolve_reward_signer(tenant, "sandbox", "evm")
    assert resolved == "deadbeef" * 8


@pytest.mark.asyncio
async def test_signer_fail_closed_outside_local(monkeypatch):
    from services.rewards.signing import SignerUnavailableError, resolve_reward_signer

    monkeypatch.setenv("AETHER_ENV", "staging")
    monkeypatch.setenv("ORACLE_SIGNER_KEY", "deadbeef" * 8)  # must be ignored
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    with pytest.raises(SignerUnavailableError):
        await resolve_reward_signer(tenant, "sandbox", "evm")


# ── Reward webhook secret dual-write / resolution ─────────────────────────


@pytest.mark.asyncio
async def test_reward_webhook_secret_roundtrip_no_plaintext_in_ref():
    from services.rewards.webhook_secret import (
        make_secret_ref,
        resolve_secrets,
        resolve_signing_secret,
        store_secret,
    )

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    secret = "whsec_reward_" + uuid.uuid4().hex
    ref = await store_secret(tenant, secret, actor="admin")
    assert ref == make_secret_ref("sandbox")
    assert secret not in ref  # the ref never contains the value

    secrets = await resolve_secrets(tenant, ref)
    assert secret in secrets

    resolved = await resolve_signing_secret(tenant, {"config": {"secret_ref": ref}})
    assert resolved == secret


@pytest.mark.asyncio
async def test_reward_webhook_rotation_keeps_overlap():
    from services.rewards.webhook_secret import resolve_secrets, store_secret

    tenant = f"t-{uuid.uuid4().hex[:8]}"
    first = "whsec_first_" + uuid.uuid4().hex
    ref = await store_secret(tenant, first, actor="admin")
    second = "whsec_second_" + uuid.uuid4().hex
    await store_secret(tenant, second, actor="admin")  # rotation

    secrets = await resolve_secrets(tenant, ref)
    # both the new active and the overlapping previous verify during the window
    assert second in secrets
    assert first in secrets


@pytest.mark.asyncio
async def test_send_time_resolution_fail_closed_without_credential(monkeypatch):
    from services.rewards.webhook_secret import resolve_signing_secret

    monkeypatch.setenv("AETHER_ENV", "staging")
    tenant = f"t-{uuid.uuid4().hex[:8]}"
    # a secret_ref with no stored credential, and no inline secret → empty
    resolved = await resolve_signing_secret(
        tenant, {"config": {"secret_ref": "credref://rewards/tenant_webhook/live/webhook_signing_secret"}}
    )
    assert resolved == ""


# ── Credential event → lifecycle demotion ─────────────────────────────────


@pytest.mark.asyncio
async def test_rotation_demotes_bound_capability(monkeypatch):
    from services.capabilities.activation_repository import ActivationStateRepo
    from services.capabilities.lifecycle import (
        CapabilityLifecycleAuthority,
        reset_lifecycle_authority,
    )
    from shared.certification.readiness import CredentialReadiness as R

    reset_lifecycle_authority()
    tenant = f"t-{uuid.uuid4().hex[:8]}"

    # Seed a certified capability bound to the reward_signer/sandbox coordinate.
    async def _ok(refs):
        return True

    async def _active(t, p, e, s):
        return "credver://reward_signer/sandbox/evm_reward_signer_key@v1"

    async def _entitled(t, p, c):
        return True

    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(), evidence_resolver=_ok,
        credential_checker=_active, entitlement_checker=_entitled,
    )
    coord = dict(tenant_id=tenant, provider="reward_signer",
                 environment="sandbox", capability="proof_signing")
    await authority.promote(**coord, target=R.CREDENTIAL_SUPPLIED,
                            actor_type="user", actor_id="a",
                            credential_slot="evm_reward_signer_key")
    await authority.promote(**coord, target=R.CONNECTION_VALIDATED,
                            actor_type="user", actor_id="a", evidence_refs=["ev"])

    # Patch the module singleton the authority notifies, then rotate.
    import services.capabilities.lifecycle as lc

    monkeypatch.setattr(lc, "_authority", authority)
    key = "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff82"
    p = await credential_authority.create_pending(
        tenant, "reward_signer", "sandbox", "evm_reward_signer_key", key, created_by="admin"
    )
    await credential_authority.activate(
        tenant, "reward_signer", "sandbox", "evm_reward_signer_key",
        credential_version=int(p["credential_version"]), actor="admin",
    )  # first activation → "activated" (no-op for CONNECTION_VALIDATED)
    # rotate to force a "rotated" event
    await credential_authority.rotate(
        tenant, "reward_signer", "sandbox", "evm_reward_signer_key",
        "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff83",
        actor="admin",
    )
    current = await authority.get_state(**coord)
    assert current["readiness_state"] == R.CREDENTIAL_SUPPLIED.value
