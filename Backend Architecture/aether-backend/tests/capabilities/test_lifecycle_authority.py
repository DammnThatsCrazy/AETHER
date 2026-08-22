"""Capability lifecycle authority — machine-enforced transition tests.

Pins the canonical persisted lifecycle: legal edges only, fail-closed
promotion preconditions (evidence / entitlement / credential slot), rotation
and revocation demotions, suspend/resume restoring the certified level,
append-only history with actor attribution, and CAS against concurrent
transitions.
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from shared.certification.readiness import CredentialReadiness as R
from services.capabilities.activation_repository import (
    ActivationStateRepo,
    ConcurrentTransitionError,
)
from services.capabilities.activation_schema import (
    ACTIVATION_STATE_FIELDS,
    TRANSITIONS,
    is_legal_transition,
)
from services.capabilities.lifecycle import (
    CapabilityLifecycleAuthority,
    IllegalTransitionError,
    PromotionPreconditionError,
)

import uuid


@pytest.fixture()
def coord() -> dict:
    """Unique coordinate per test — the in-memory store is process-shared."""
    return dict(
        tenant_id=f"tenant-lc-{uuid.uuid4().hex[:10]}",
        provider="stripe_credit",
        environment="sandbox",
        capability="rewards",
    )


async def _ok_evidence(refs):
    return True


async def _active_credential(tenant_id, provider, environment, slot):
    return f"credver://{provider}/{environment}/{slot}@v1"


async def _entitled(tenant_id, provider, capability):
    return True


def _full_authority() -> CapabilityLifecycleAuthority:
    return CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_active_credential,
        entitlement_checker=_entitled,
    )


async def _walk_to(authority, coord, target_chain):
    """Promote through the chain in order, returning the last row."""
    row = None
    for target in target_chain:
        row = await authority.promote(
            **coord,
            target=target,
            actor_type="user",
            actor_id="alex",
            reason=f"walk to {target.value}",
            evidence_refs=["ev-1"] if target in (
                R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED, R.PARTNER_LIVE
            ) else [],
            credential_slot="server_api_key" if target == R.CREDENTIAL_SUPPLIED else None,
        )
    return row


# ── Legal-edge machine ────────────────────────────────────────────────────


def test_no_rung_skipping_edges_exist():
    assert not is_legal_transition(R.CREDENTIAL_WAITING, R.CONNECTION_VALIDATED)
    assert not is_legal_transition(R.CREDENTIAL_WAITING, R.PARTNER_LIVE)
    assert not is_legal_transition(R.CREDENTIAL_SUPPLIED, R.SANDBOX_VALIDATED)
    assert not is_legal_transition(R.CONNECTION_VALIDATED, R.PARTNER_LIVE)


def test_nothing_returns_to_scaffolded():
    assert not any(target == R.SCAFFOLDED for _, target in TRANSITIONS)


def test_offramps_reachable_from_every_progression_state():
    for state in (
        R.CREDENTIAL_WAITING, R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED,
        R.SANDBOX_VALIDATED, R.PARTNER_LIVE,
    ):
        for off in (R.DEGRADED, R.SUSPENDED, R.REVOKED, R.DISABLED):
            assert is_legal_transition(state, off), f"{state}->{off} missing"


@pytest.mark.asyncio
async def test_illegal_promotion_raises(coord):
    authority = _full_authority()
    with pytest.raises(IllegalTransitionError):
        await authority.promote(
            **coord, target=R.PARTNER_LIVE, actor_type="user", actor_id="alex",
            evidence_refs=["ev-1"],
        )


# ── Fail-closed preconditions ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promotion_without_evidence_is_refused(coord):
    authority = _full_authority()
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED])
    with pytest.raises(PromotionPreconditionError, match="evidence"):
        await authority.promote(
            **coord, target=R.CONNECTION_VALIDATED,
            actor_type="user", actor_id="alex", evidence_refs=[],
        )


@pytest.mark.asyncio
async def test_promotion_without_registered_resolver_is_refused(coord):
    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=None,
        credential_checker=_active_credential,
        entitlement_checker=_entitled,
    )
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED])
    with pytest.raises(PromotionPreconditionError, match="resolver"):
        await authority.promote(
            **coord, target=R.CONNECTION_VALIDATED,
            actor_type="user", actor_id="alex", evidence_refs=["ev-1"],
        )


@pytest.mark.asyncio
async def test_promotion_without_entitlement_checker_is_refused(coord):
    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_active_credential,
        entitlement_checker=None,
    )
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED])
    with pytest.raises(PromotionPreconditionError, match="entitlement"):
        await authority.promote(
            **coord, target=R.CONNECTION_VALIDATED,
            actor_type="user", actor_id="alex", evidence_refs=["ev-1"],
        )


@pytest.mark.asyncio
async def test_promotion_with_denied_entitlement_is_refused(coord):
    async def _not_entitled(tenant_id, provider, capability):
        return False

    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_active_credential,
        entitlement_checker=_not_entitled,
    )
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED])
    with pytest.raises(PromotionPreconditionError, match="not entitled"):
        await authority.promote(
            **coord, target=R.CONNECTION_VALIDATED,
            actor_type="user", actor_id="alex", evidence_refs=["ev-1"],
        )


@pytest.mark.asyncio
async def test_declared_credential_slot_without_active_version_is_refused(coord):
    async def _no_active(tenant_id, provider, environment, slot):
        return None

    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_no_active,
        entitlement_checker=_entitled,
    )
    with pytest.raises(PromotionPreconditionError, match="no ACTIVE credential"):
        await authority.promote(
            **coord, target=R.CREDENTIAL_SUPPLIED,
            actor_type="user", actor_id="alex", credential_slot="server_api_key",
        )


@pytest.mark.asyncio
async def test_credential_supplied_promotion_denied_without_active_credential_or_slot():
    """BUG FIX: an admin omitting the OPTIONAL `credential_slot` field must
    not be able to persist CREDENTIAL_SUPPLIED for a provider that has no
    active credential. The REQUIRED slots are resolved server-side from the
    slot registry — never left to whatever the caller happened to declare."""
    async def _no_active(tenant_id, provider, environment, slot):
        return None

    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_no_active,
        entitlement_checker=_entitled,
    )
    tenant_id = f"tenant-lc-{uuid.uuid4().hex[:10]}"
    with pytest.raises(
        PromotionPreconditionError, match="no ACTIVE credential for required slot"
    ):
        await authority.promote(
            tenant_id=tenant_id,
            provider="reward_signer",  # registered provider with a REQUIRED slot
            environment="sandbox",
            capability="proof_signing",
            target=R.CREDENTIAL_SUPPLIED,
            actor_type="operator",
            actor_id="ops-1",
            # credential_slot intentionally omitted.
        )
    # confirms nothing was persisted — the coordinate never advanced
    current = await authority.get_state(
        tenant_id, "reward_signer", "sandbox", "proof_signing"
    )
    assert current is None


# ── Full walk + history + attribution ─────────────────────────────────────


@pytest.mark.asyncio
async def test_full_promotion_walk_records_history_and_actors(coord):
    authority = _full_authority()
    row = await _walk_to(
        authority,
        coord,
        [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED, R.PARTNER_LIVE],
    )
    assert row["readiness_state"] == "partner_live"
    assert row["state_version"] == 4
    assert row["actor_type"] == "user" and row["actor_id"] == "alex"
    # credential ref resolved by the checker at CREDENTIAL_SUPPLIED
    history = await authority.history(**coord)
    assert [h["readiness_state"] for h in history] == [
        "partner_live", "sandbox_validated", "connection_validated", "credential_supplied",
    ]
    assert history[-1]["credential_version_ref"].startswith("credver://")
    # exactly one non-superseded row
    current = await authority.get_state(**coord)
    assert current["readiness_state"] == "partner_live"
    assert set(current.keys()) >= set(ACTIVATION_STATE_FIELDS)


# ── Suspend / resume ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suspend_then_resume_restores_certified_level(coord):
    authority = _full_authority()
    await _walk_to(
        authority, coord, [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED]
    )
    suspended = await authority.suspend(
        **coord, actor_type="operator", actor_id="op-1", reason="incident", kill_switch=True
    )
    assert suspended["readiness_state"] == "suspended"
    assert suspended["kill_switch"] is True
    assert suspended["prior_state"] == "sandbox_validated"

    resumed = await authority.resume(
        **coord, actor_type="operator", actor_id="op-1"
    )
    assert resumed["readiness_state"] == "sandbox_validated"


@pytest.mark.asyncio
async def test_resume_without_suspension_is_refused(coord):
    authority = _full_authority()
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED])
    with pytest.raises(IllegalTransitionError):
        await authority.resume(**coord, actor_type="user", actor_id="alex")


# ── Credential events ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rotation_demotes_certified_capability_to_credential_supplied(coord):
    authority = _full_authority()
    await _walk_to(
        authority, coord, [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED]
    )
    outcomes = await authority.on_credential_event(
        tenant_id=coord["tenant_id"], provider=coord["provider"], environment="sandbox",
        event="rotated", credential_version_ref="credver://v2",
    )
    assert len(outcomes) == 1
    assert outcomes[0]["readiness_state"] == "credential_supplied"
    assert outcomes[0]["credential_version_ref"] == "credver://v2"
    assert outcomes[0]["actor_type"] == "system_worker"


@pytest.mark.asyncio
async def test_revocation_demotes_to_revoked(coord):
    authority = _full_authority()
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED])
    outcomes = await authority.on_credential_event(
        tenant_id=coord["tenant_id"], provider=coord["provider"], environment="sandbox",
        event="revoked",
    )
    assert outcomes[0]["readiness_state"] == "revoked"
    # re-entry path: revoked -> credential_waiting is legal
    assert is_legal_transition(R.REVOKED, R.CREDENTIAL_WAITING)


@pytest.mark.asyncio
async def test_credential_events_do_not_cross_environments(coord):
    authority = _full_authority()
    await _walk_to(authority, coord, [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED])
    outcomes = await authority.on_credential_event(
        tenant_id=coord["tenant_id"], provider=coord["provider"], environment="live",
        event="revoked",
    )
    assert outcomes == []
    current = await authority.get_state(**coord)
    assert current["readiness_state"] == "connection_validated"


# ── Bug fix: revocation while suspended ────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_while_suspended_moves_to_revoked_and_blocks_resume(coord):
    """BUG FIX (a): a credential revoked/deleted while the capability is
    SUSPENDED must still take effect. SUSPENDED/DEGRADED rank BELOW
    CREDENTIAL_WAITING (off-ramp states), so the naive rank comparison used
    to silently drop the event, leaving prior_state=partner_live in place.
    Once the row is REVOKED, resume() can no longer even be attempted, so it
    can never blindly restore partner_live with a dead credential."""
    authority = _full_authority()
    await _walk_to(
        authority, coord,
        [R.CREDENTIAL_SUPPLIED, R.CONNECTION_VALIDATED, R.SANDBOX_VALIDATED, R.PARTNER_LIVE],
    )
    suspended = await authority.suspend(
        **coord, actor_type="operator", actor_id="op-1", reason="incident",
    )
    assert suspended["readiness_state"] == "suspended"
    assert suspended["prior_state"] == "partner_live"

    outcomes = await authority.on_credential_event(
        tenant_id=coord["tenant_id"], provider=coord["provider"], environment="sandbox",
        event="revoked",
    )
    assert len(outcomes) == 1
    assert outcomes[0]["readiness_state"] == "revoked"

    current = await authority.get_state(**coord)
    assert current["readiness_state"] == "revoked"

    # resume() does NOT restore partner_live — the row is no longer even a
    # legal resume target (only SUSPENDED/DEGRADED are).
    with pytest.raises(IllegalTransitionError):
        await authority.resume(**coord, actor_type="operator", actor_id="op-1")


@pytest.mark.asyncio
async def test_resume_revalidates_and_fails_closed_when_credential_goes_missing():
    """BUG FIX (b): resume() re-verifies the interrupted rung's preconditions
    instead of trusting the persisted row. Here the row STAYS suspended (no
    on_credential_event fired — e.g. a race, or some other off-ramp path)
    yet the credential the certified level depended on has gone missing;
    resume() must fail closed to CREDENTIAL_WAITING rather than restoring
    partner_live."""
    tenant_id = f"tenant-lc-{uuid.uuid4().hex[:10]}"
    provider, environment, capability = "reward_signer", "sandbox", "proof_signing"
    credential_available = {"evm_reward_signer_key": True}

    async def _flaky_credential(t, p, e, slot):
        if credential_available.get(slot):
            return f"credver://{p}/{e}/{slot}@v1"
        return None

    authority = CapabilityLifecycleAuthority(
        ActivationStateRepo(),
        evidence_resolver=_ok_evidence,
        credential_checker=_flaky_credential,
        entitlement_checker=_entitled,
    )
    common = dict(
        tenant_id=tenant_id, provider=provider, environment=environment, capability=capability
    )
    await authority.promote(
        **common, target=R.CREDENTIAL_SUPPLIED, actor_type="user", actor_id="alex",
        credential_slot="evm_reward_signer_key",
    )
    await authority.promote(
        **common, target=R.CONNECTION_VALIDATED, actor_type="user", actor_id="alex",
        evidence_refs=["ev-1"],
    )
    await authority.promote(
        **common, target=R.SANDBOX_VALIDATED, actor_type="user", actor_id="alex",
        evidence_refs=["ev-1"],
    )
    await authority.promote(
        **common, target=R.PARTNER_LIVE, actor_type="user", actor_id="alex",
        evidence_refs=["ev-1"],
    )

    suspended = await authority.suspend(
        **common, actor_type="operator", actor_id="op-1", reason="incident",
    )
    assert suspended["prior_state"] == "partner_live"

    # credential goes away while suspended, without an on_credential_event.
    credential_available["evm_reward_signer_key"] = False

    resumed = await authority.resume(**common, actor_type="operator", actor_id="op-1")
    assert resumed["readiness_state"] == "credential_waiting"
    assert resumed["readiness_state"] != "partner_live"


# ── CAS / concurrency ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_transition_is_refused(coord):
    repo = ActivationStateRepo()
    authority = CapabilityLifecycleAuthority(
        repo,
        evidence_resolver=_ok_evidence,
        credential_checker=_active_credential,
        entitlement_checker=_entitled,
    )
    first = await authority.promote(
        **coord, target=R.CREDENTIAL_SUPPLIED,
        actor_type="user", actor_id="alex", credential_slot="server_api_key",
    )
    # a second writer advances the coordinate...
    await repo.advance(first, {**first, "state_version": 2, "readiness_state": "suspended",
                               "id": None} | {"id": "ignored"})
    # ...so advancing from the stale `first` row must fail
    with pytest.raises(ConcurrentTransitionError):
        await repo.advance(first, {**first, "state_version": 3})
