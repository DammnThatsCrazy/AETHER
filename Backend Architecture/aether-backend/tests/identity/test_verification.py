"""Tests for the identity assurance verification service (Agent B).

Covers the verification/evidence layer end-to-end against the in-memory
backend, without depending on Agent C's ``resolution_replay`` module: a FAKE
replay service is injected into :class:`EvidenceService` and used to assert the
best-effort fan-out is invoked and that a failing replay never breaks issuance.

Covered:
  * OTP happy path -> verified + active evidence exists
  * expired OTP rejected
  * wrong code increments attempts and eventually locks
  * a consumed challenge cannot re-verify
  * magic-link GET (validate) does NOT create evidence; POST consume does
  * OIDC trusted claim creates evidence; untrusted issuer / wrong audience /
    missing email_verified do NOT
  * tenant isolation (evidence for tenant A invisible to B)
  * revoke marks evidence inactive
  * replay is triggered best-effort and a failing replay never breaks issuance
"""
from __future__ import annotations

import os
import sys

import pytest

# Make backend packages importable when this suite is run in isolation.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.evidence import EvidenceService  # noqa: E402
from services.identity.hashing import hash_email  # noqa: E402
from services.identity.models import (  # noqa: E402
    REASON_UNTRUSTED_VERIFICATION_ISSUER,
    IdentitySignalType,
    VerificationEvidenceType,
)
from services.identity.verification import EmailVerificationService  # noqa: E402
from services.identity.verification_repository import (  # noqa: E402
    VerificationChallengeRepository,
    VerificationEvidenceRepository,
)

TENANT = "tenant_verify"
OTHER_TENANT = "tenant_other"
EMAIL = "person@example.com"


@pytest.fixture(autouse=True)
def _reset():
    # The local secret is only echoed back when AETHER_ENV=local, which the
    # OTP/magic-link tests rely on to drive the flow.
    prev = os.environ.get("AETHER_ENV")
    os.environ["AETHER_ENV"] = "local"
    reset_in_memory_stores()
    yield
    if prev is None:
        os.environ.pop("AETHER_ENV", None)
    else:
        os.environ["AETHER_ENV"] = prev


class _FakeReplay:
    """Records request_replay calls so tests can assert the fan-out fired."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request_replay(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "queued", **kwargs}


class _BoomReplay:
    """A replay service that always fails — issuance must survive it."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def request_replay(self, **kwargs):
        self.calls.append(kwargs)
        raise RuntimeError("replay backend down")


def _make_service(replay=None):
    """Build an EmailVerificationService wired to an injectable replay fake."""
    replay = replay if replay is not None else _FakeReplay()
    evidence_service = EvidenceService(replay_service=replay)
    return EmailVerificationService(evidence_service=evidence_service), replay


# ── OTP flow ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_otp_happy_path_issues_active_evidence():
    svc, replay = _make_service()
    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)
    assert issued["method"] == "email_otp"
    assert issued["identifier_hash"] == hash_email(EMAIL, TENANT)
    assert "secret" in issued  # local env echoes the OTP

    result = await svc.verify_email_otp(
        tenant_id=TENANT, challenge_id=issued["challenge_id"], code=issued["secret"],
    )
    assert result["status"] == "verified"
    assert result["evidence_id"]

    # Active evidence exists for the identifier.
    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    )
    assert len(active) == 1
    assert active[0]["evidence_type"] == (
        VerificationEvidenceType.EMAIL_OWNERSHIP_VERIFIED.value
    )
    assert active[0]["verification_method"] == "email_otp"
    # No raw secret was ever persisted on the challenge.
    challenge_repo = VerificationChallengeRepository()
    row = await challenge_repo.get_for_tenant(TENANT, issued["challenge_id"])
    assert row["state"] == "consumed"
    assert issued["secret"] not in str(row)

    # Best-effort replay fan-out fired on issuance.
    assert any(c["trigger_type"] == "verification_evidence_issued" for c in replay.calls)


@pytest.mark.asyncio
async def test_expired_otp_is_rejected():
    svc, _ = _make_service()
    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)

    # Force expiry in the shared in-memory store.
    challenge_repo = VerificationChallengeRepository()
    await challenge_repo.apply_update(
        TENANT, issued["challenge_id"], {"expires_at": "2000-01-01T00:00:00+00:00"},
    )

    result = await svc.verify_email_otp(
        tenant_id=TENANT, challenge_id=issued["challenge_id"], code=issued["secret"],
    )
    assert result["status"] == "expired"

    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    )
    assert active == []


@pytest.mark.asyncio
async def test_wrong_code_increments_attempts_then_locks():
    svc, _ = _make_service()
    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)
    cid = issued["challenge_id"]

    # First four wrong attempts increment the counter.
    for expected_attempts in (1, 2, 3, 4):
        result = await svc.verify_email_otp(
            tenant_id=TENANT, challenge_id=cid, code="000000",
        )
        assert result["status"] == "invalid"
        assert result["attempts"] == expected_attempts

    # Fifth attempt hits max_attempts (5) and locks the challenge.
    locked = await svc.verify_email_otp(tenant_id=TENANT, challenge_id=cid, code="000000")
    assert locked["status"] == "locked"

    # Even the correct code cannot verify a locked challenge.
    after_lock = await svc.verify_email_otp(
        tenant_id=TENANT, challenge_id=cid, code=issued["secret"],
    )
    assert after_lock["status"] in {"locked", "invalid_state"}

    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    )
    assert active == []


@pytest.mark.asyncio
async def test_consumed_challenge_cannot_reverify():
    svc, _ = _make_service()
    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)
    cid = issued["challenge_id"]

    first = await svc.verify_email_otp(tenant_id=TENANT, challenge_id=cid, code=issued["secret"])
    assert first["status"] == "verified"

    # Re-presenting the same correct code against a consumed challenge fails,
    # and no second evidence row is created.
    second = await svc.verify_email_otp(tenant_id=TENANT, challenge_id=cid, code=issued["secret"])
    assert second["status"] == "invalid_state"

    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    )
    assert len(active) == 1


# ── Magic-link flow ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_magic_link_get_does_not_issue_evidence_post_consume_does():
    svc, _ = _make_service()
    issued = await svc.issue_email_challenge(
        tenant_id=TENANT, email=EMAIL, method="email_magic_link",
    )
    cid = issued["challenge_id"]
    token = issued["secret"]

    evidence_repo = VerificationEvidenceRepository()

    # Consuming before validation is refused.
    early = await svc.consume_magic_link(tenant_id=TENANT, challenge_id=cid)
    assert early["status"] == "not_validated_or_consumed"

    # A wrong token on the GET landing is rejected.
    bad = await svc.validate_magic_link(tenant_id=TENANT, challenge_id=cid, token="nope")
    assert bad["status"] == "invalid"

    # The GET landing validates but must NOT create evidence.
    validated = await svc.validate_magic_link(tenant_id=TENANT, challenge_id=cid, token=token)
    assert validated["status"] == "validated"
    assert await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    ) == []

    # The POST consume issues evidence.
    consumed = await svc.consume_magic_link(tenant_id=TENANT, challenge_id=cid)
    assert consumed["status"] == "verified"
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    )
    assert len(active) == 1
    assert active[0]["verification_method"] == "email_magic_link"


# ── OIDC trusted-claim flow ──────────────────────────────────────────────────

def _oidc_claims(**overrides) -> dict:
    claims = {
        "iss": "https://accounts.example.com",
        "aud": "aether-app",
        "sub": "provider-subject-123",
        "email": EMAIL,
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


@pytest.mark.asyncio
async def test_oidc_trusted_claim_issues_authoritative_evidence():
    svc, _ = _make_service()
    result = await svc.verify_trusted_claim(
        tenant_id=TENANT,
        claims=_oidc_claims(aud=["aether-app", "other"]),
        issuer_allowlist=["https://accounts.example.com"],
        expected_audience="aether-app",
    )
    assert result["status"] == "verified"

    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", hash_email(EMAIL, TENANT),
    )
    assert len(active) == 1
    assert active[0]["assurance_level"] == "authoritative"
    assert active[0]["verification_method"] == "oidc_verified_claim"
    assert active[0]["issuer"] == "https://accounts.example.com"
    # The provider subject is stored only as a digest, never in the clear.
    assert active[0]["issuer_subject_hash"]
    assert "provider-subject-123" not in str(active[0])


@pytest.mark.asyncio
async def test_oidc_untrusted_issuer_creates_no_evidence():
    svc, _ = _make_service()
    result = await svc.verify_trusted_claim(
        tenant_id=TENANT,
        claims=_oidc_claims(iss="https://evil.example.com"),
        issuer_allowlist=["https://accounts.example.com"],
        expected_audience="aether-app",
    )
    assert result["status"] == "untrusted_issuer"
    assert result["reason"] == REASON_UNTRUSTED_VERIFICATION_ISSUER

    evidence_repo = VerificationEvidenceRepository()
    assert await evidence_repo.get_active_for_identifier(
        TENANT, "email", hash_email(EMAIL, TENANT),
    ) == []


@pytest.mark.asyncio
async def test_oidc_wrong_audience_creates_no_evidence():
    svc, _ = _make_service()
    result = await svc.verify_trusted_claim(
        tenant_id=TENANT,
        claims=_oidc_claims(aud="some-other-app"),
        issuer_allowlist=["https://accounts.example.com"],
        expected_audience="aether-app",
    )
    assert result["status"] == "invalid_audience"
    evidence_repo = VerificationEvidenceRepository()
    assert await evidence_repo.get_active_for_identifier(
        TENANT, "email", hash_email(EMAIL, TENANT),
    ) == []


@pytest.mark.asyncio
async def test_oidc_missing_email_verified_creates_no_evidence():
    svc, _ = _make_service()
    result = await svc.verify_trusted_claim(
        tenant_id=TENANT,
        claims=_oidc_claims(email_verified=False),
        issuer_allowlist=["https://accounts.example.com"],
        expected_audience="aether-app",
    )
    assert result["status"] == "unverified"
    evidence_repo = VerificationEvidenceRepository()
    assert await evidence_repo.get_active_for_identifier(
        TENANT, "email", hash_email(EMAIL, TENANT),
    ) == []


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_is_tenant_isolated():
    svc, _ = _make_service()
    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)
    result = await svc.verify_email_otp(
        tenant_id=TENANT, challenge_id=issued["challenge_id"], code=issued["secret"],
    )
    evidence_id = result["evidence_id"]

    evidence_repo = VerificationEvidenceRepository()
    # Point read is tenant-scoped.
    assert await evidence_repo.get_for_tenant(TENANT, evidence_id) is not None
    assert await evidence_repo.get_for_tenant(OTHER_TENANT, evidence_id) is None
    # Identifier lookup for the other tenant finds nothing.
    assert await evidence_repo.get_active_for_identifier(
        OTHER_TENANT, "email", issued["identifier_hash"],
    ) == []


# ── Revocation ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revoke_marks_evidence_inactive():
    replay = _FakeReplay()
    evidence_service = EvidenceService(replay_service=replay)
    svc = EmailVerificationService(evidence_service=evidence_service)

    issued = await svc.issue_email_challenge(tenant_id=TENANT, email=EMAIL)
    result = await svc.verify_email_otp(
        tenant_id=TENANT, challenge_id=issued["challenge_id"], code=issued["secret"],
    )
    evidence_id = result["evidence_id"]

    row = await evidence_service.revoke_evidence(TENANT, evidence_id, reason="user_request")
    assert row is not None
    assert row["status"] == "revoked"
    assert row["revoked_at"]

    evidence_repo = VerificationEvidenceRepository()
    assert await evidence_repo.get_active_for_identifier(
        TENANT, "email", issued["identifier_hash"],
    ) == []
    # Revocation also triggers a best-effort replay.
    assert any(c["trigger_type"] == "verification_evidence_revoked" for c in replay.calls)

    # Revoking an evidence id that is not in the tenant returns None.
    assert await evidence_service.revoke_evidence(OTHER_TENANT, evidence_id) is None


# ── Replay is best-effort ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failing_replay_never_breaks_evidence_issuance():
    boom = _BoomReplay()
    evidence_service = EvidenceService(replay_service=boom)

    evidence = await evidence_service.issue_evidence(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=hash_email(EMAIL, TENANT),
        verification_method="email_otp",
    )
    # Issuance succeeded despite the replay raising.
    assert evidence.id
    assert boom.calls, "replay was still attempted"

    evidence_repo = VerificationEvidenceRepository()
    active = await evidence_repo.get_active_for_identifier(
        TENANT, "email", hash_email(EMAIL, TENANT),
    )
    assert len(active) == 1


@pytest.mark.asyncio
async def test_evidence_to_signal_maps_email_ownership():
    evidence_service = EvidenceService(replay_service=_FakeReplay())
    evidence = await evidence_service.issue_evidence(
        tenant_id=TENANT,
        identifier_type="email",
        identifier_hash=hash_email(EMAIL, TENANT),
        verification_method="email_otp",
    )
    signal, identifier_hash = evidence_service.evidence_to_signal(evidence)
    assert signal == IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED
    assert identifier_hash == hash_email(EMAIL, TENANT)


@pytest.mark.asyncio
async def test_invalid_email_raises_value_error():
    svc, _ = _make_service()
    with pytest.raises(ValueError):
        await svc.issue_email_challenge(tenant_id=TENANT, email="not-an-email")
