"""Kyber workforce identity — security behaviour, not happy paths.

Every test here asserts a denial or a fail-closed outcome. The happy path is
covered incidentally by the fixtures that set each denial up.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import _IN_MEMORY_STORES  # noqa: E402
from services.kyber.identity.bootstrap import (  # noqa: E402
    FounderBootstrapService,
    founder_bootstrap_service,
)
from services.kyber.identity.directory_sync import directory_sync_service  # noqa: E402
from services.kyber.identity.invitations import (  # noqa: E402
    InvitationService,
    hash_invitation_token,
)
from services.kyber.identity.lifecycle import offboard_principal  # noqa: E402
from services.kyber.identity.oidc import (  # noqa: E402
    GoogleOidcClient,
    MockOidcProvider,
    OidcConfig,
    OidcError,
    OidcTransactionStore,
)
from services.kyber.identity.principals import PrincipalService  # noqa: E402
from shared.common.common import (  # noqa: E402
    BadRequestError,
    ConflictError,
    ForbiddenError,
)

KYBER_TABLES = (
    "olympus_workforce_principals",
    "olympus_workforce_invitations",
    "olympus_role_bindings",
    "olympus_capability_grants",
    "kyber_authentication_events",
    "security_audit_events",
)

BOOTSTRAP_ENV_VARS = (
    "KYBER_BOOTSTRAP_ENABLED",
    "KYBER_BOOTSTRAP_FOUNDER_EMAIL",
    "KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT",
)


@pytest.fixture(autouse=True)
def clean_stores():
    """Empty every table this package writes to, before and after each test."""
    def _clear() -> None:
        for table in KYBER_TABLES:
            _IN_MEMORY_STORES.setdefault(table, {}).clear()

    saved_env = {name: os.environ.get(name) for name in BOOTSTRAP_ENV_VARS}
    _clear()
    founder_bootstrap_service._consumed_in_process = False
    yield
    _clear()
    founder_bootstrap_service._consumed_in_process = False
    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture
def principals() -> PrincipalService:
    return PrincipalService()


@pytest.fixture
def invitations() -> InvitationService:
    return InvitationService()


def _oidc_client(**overrides) -> GoogleOidcClient:
    config = OidcConfig(
        client_id=overrides.pop("client_id", "kyber-client.apps.googleusercontent.com"),
        client_secret="secret",
        redirect_uri="https://kyber.example.com/v1/kyber/auth/callback",
        hosted_domain=overrides.pop("hosted_domain", None),
    )
    return GoogleOidcClient(config)


def _claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "kyber-client.apps.googleusercontent.com",
        "sub": "google-subject-1",
        "email": "operator@olympus.example",
        "email_verified": True,
        "name": "Test Operator",
        "iat": now,
        "exp": now + 600,
        "nonce": "nonce-value",
    }
    claims.update(overrides)
    return claims


async def _active_principal(
    principals: PrincipalService,
    *,
    email: str = "operator@olympus.example",
    subject: str = "google-subject-1",
    templates: list[str] | None = None,
    environments: list[str] | None = None,
):
    principal = await principals.create_principal(
        email=email,
        google_subject=None,
        display_name="Test Operator",
        created_by="test",
        role_template_ids=templates if templates is not None else ["observer"],
        allowed_environments=environments or [],
    )
    return await principals.activate(principal.operator_id, google_subject=subject)


# ── OIDC claim validation ─────────────────────────────────────────────────────

async def test_wrong_issuer_is_denied():
    client = _oidc_client()
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(iss="https://evil.example.com"), nonce="nonce-value")
    assert exc.value.reason == "issuer_invalid"


async def test_wrong_audience_is_denied():
    client = _oidc_client()
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(aud="some-other-client"), nonce="nonce-value")
    assert exc.value.reason == "audience_invalid"


async def test_invalid_nonce_is_denied():
    client = _oidc_client()
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(nonce="a-different-nonce"), nonce="nonce-value")
    assert exc.value.reason == "nonce_mismatch"


async def test_missing_nonce_is_denied_when_one_was_requested():
    client = _oidc_client()
    claims = _claims()
    claims.pop("nonce")
    with pytest.raises(OidcError) as exc:
        client.validate_claims(claims, nonce="nonce-value")
    assert exc.value.reason == "nonce_mismatch"


async def test_unverified_email_is_denied():
    client = _oidc_client()
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(email_verified=False), nonce="nonce-value")
    assert exc.value.reason == "email_unverified"


async def test_wrong_hosted_domain_is_denied():
    client = _oidc_client(hosted_domain="olympus.example")
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(hd="contractor.example"), nonce="nonce-value")
    assert exc.value.reason == "hosted_domain_mismatch"


async def test_missing_hosted_domain_is_denied_when_one_is_configured():
    client = _oidc_client(hosted_domain="olympus.example")
    with pytest.raises(OidcError) as exc:
        client.validate_claims(_claims(), nonce="nonce-value")
    assert exc.value.reason == "hosted_domain_mismatch"


async def test_expired_token_is_denied():
    client = _oidc_client()
    stale = int(time.time()) - 7200
    with pytest.raises(OidcError) as exc:
        client.validate_claims(
            _claims(iat=stale, exp=stale + 600), nonce="nonce-value"
        )
    assert exc.value.reason == "token_expired"


async def test_valid_claims_pass_every_check():
    client = _oidc_client(hosted_domain="olympus.example")
    claims = client.validate_claims(_claims(hd="olympus.example"), nonce="nonce-value")
    identity = client.identity_from_claims(claims)
    assert identity.google_subject == "google-subject-1"
    assert identity.email == "operator@olympus.example"


async def test_signature_verification_refuses_a_stubbed_jwt_module(monkeypatch):
    """An unverifiable token must be a denial, never a bypass."""
    import services.kyber.identity.oidc as oidc_module

    monkeypatch.setattr(oidc_module, "_jwt_module", None)
    client = _oidc_client()
    with pytest.raises(OidcError) as exc:
        await client._verify_signature("header.payload.signature")
    assert exc.value.reason == "jwt_unavailable"


# ── Transaction store: single use ─────────────────────────────────────────────

async def test_oidc_state_is_single_use():
    store = OidcTransactionStore()
    transaction = store.start(redirect_uri="https://kyber.example.com/cb")
    assert store.consume(transaction.state) is not None
    assert store.consume(transaction.state) is None


async def test_oidc_state_expires():
    store = OidcTransactionStore(ttl_seconds=0)
    transaction = store.start(redirect_uri="https://kyber.example.com/cb")
    assert store.consume(transaction.state) is None


# ── Mock provider containment ─────────────────────────────────────────────────

async def test_mock_provider_refuses_to_construct_in_production():
    with pytest.raises(RuntimeError):
        MockOidcProvider(OidcConfig(), environment="production")


async def test_mock_provider_constructs_in_local():
    provider = MockOidcProvider(OidcConfig(), environment="local")
    assert provider.provider_name == "mock"


# ── Principal resolution ──────────────────────────────────────────────────────

async def test_unknown_google_subject_resolves_to_nothing(principals):
    await _active_principal(principals)
    assert await principals.get_by_google_subject("not-a-known-subject") is None


async def test_uninvited_user_has_no_principal_and_no_capabilities(principals):
    await _active_principal(principals)
    assert await principals.get_by_email("stranger@olympus.example") is None
    assert await principals.effective_capabilities("op_does_not_exist") == frozenset()


async def test_suspended_principal_resolves_to_no_capabilities(principals):
    principal = await _active_principal(principals, templates=["operations_command"])
    assert await principals.effective_capabilities(principal.operator_id)

    await principals.suspend(
        principal.operator_id, actor_id="founder", reason="security review"
    )
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()
    assert await principals.role_template_ids(principal.operator_id) == []


async def test_suspension_is_idempotent(principals):
    principal = await _active_principal(principals)
    first = await principals.suspend(
        principal.operator_id, actor_id="founder", reason="one"
    )
    second = await principals.suspend(
        principal.operator_id, actor_id="founder", reason="two"
    )
    assert first.suspended_at == second.suspended_at
    assert second.employment_status == "suspended"


async def test_offboarded_principal_is_denied_everything(principals):
    principal = await _active_principal(principals, templates=["founder_operator"])
    report = await offboard_principal(
        principal.operator_id, actor_id="founder", reason="left the company"
    )
    assert report["employment_status"] == "offboarded"

    refreshed = await principals.get_by_operator_id(principal.operator_id)
    assert refreshed.employment_status == "offboarded"
    assert refreshed.kyber_enabled is False
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()

    with pytest.raises(BadRequestError):
        await principals.activate(principal.operator_id, google_subject="google-subject-1")


async def test_kyber_disabled_principal_has_no_capabilities(principals):
    principal = await _active_principal(principals, templates=["observer"])
    await principals.principals.update(principal.operator_id, {"kyber_enabled": False})
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()


async def test_activation_cannot_rebind_a_different_google_identity(principals):
    principal = await _active_principal(principals)
    with pytest.raises(BadRequestError):
        await principals.activate(principal.operator_id, google_subject="another-subject")


# ── Capability composition ────────────────────────────────────────────────────

async def test_deny_grant_beats_an_allowing_role_template(principals):
    principal = await _active_principal(principals, templates=["security_auditor"])
    capabilities = await principals.effective_capabilities(principal.operator_id)
    assert "kyber.audit.read" in capabilities

    await principals.grant_capability(
        operator_id=principal.operator_id,
        capability_id="kyber.audit.read",
        effect="deny",
        granted_by="founder",
        reason="under investigation",
    )
    after = await principals.effective_capabilities(principal.operator_id)
    assert "kyber.audit.read" not in after


async def test_revoked_deny_grant_stops_applying(principals):
    principal = await _active_principal(principals, templates=["security_auditor"])
    grant = await principals.grant_capability(
        operator_id=principal.operator_id,
        capability_id="kyber.audit.read",
        effect="deny",
        granted_by="founder",
    )
    assert "kyber.audit.read" not in await principals.effective_capabilities(
        principal.operator_id
    )
    await principals.grants.update(grant.grant_id, {"revoked_at": "2020-01-01T00:00:00+00:00"})
    assert "kyber.audit.read" in await principals.effective_capabilities(
        principal.operator_id
    )


async def test_expired_role_binding_grants_nothing(principals):
    principal = await _active_principal(principals, templates=[])
    await principals.bind_role(
        operator_id=principal.operator_id,
        role_template_id="operations_command",
        granted_by="founder",
        expires_at="2020-01-01T00:00:00+00:00",
    )
    assert await principals.role_template_ids(principal.operator_id) == []
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()


async def test_environment_scoped_binding_does_not_apply_elsewhere(principals):
    principal = await _active_principal(principals, templates=[])
    await principals.bind_role(
        operator_id=principal.operator_id,
        role_template_id="operations_command",
        granted_by="founder",
        environment="staging",
    )
    staging = await principals.effective_capabilities(
        principal.operator_id, environment="staging"
    )
    production = await principals.effective_capabilities(
        principal.operator_id, environment="production"
    )
    assert "kyber.incident.manage" in staging
    assert production == frozenset()


async def test_principal_outside_allowed_environments_has_no_capabilities(principals):
    principal = await _active_principal(
        principals, templates=["operations_command"], environments=["local", "staging"]
    )
    assert await principals.effective_capabilities(
        principal.operator_id, environment="staging"
    )
    assert (
        await principals.effective_capabilities(
            principal.operator_id, environment="production"
        )
        == frozenset()
    )


async def test_revoked_role_binding_grants_nothing(principals):
    principal = await _active_principal(principals, templates=[])
    binding = await principals.bind_role(
        operator_id=principal.operator_id,
        role_template_id="operations_command",
        granted_by="founder",
    )
    await principals.revoke_role_binding(
        binding.binding_id, actor_id="founder", reason="role change"
    )
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()


async def test_unknown_role_template_is_rejected(principals):
    with pytest.raises(BadRequestError):
        await principals.create_principal(
            email="new@olympus.example",
            google_subject=None,
            display_name=None,
            created_by="founder",
            role_template_ids=["not_a_real_template"],
            allowed_environments=[],
        )


# ── Invitations ───────────────────────────────────────────────────────────────

async def test_invitation_token_is_returned_once_and_stored_hashed(invitations):
    invitation, token = await invitations.create_invitation(
        email="New.Hire@Olympus.Example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
    )
    assert invitation.email == "new.hire@olympus.example"
    assert invitation.token_hash == hash_invitation_token(token)
    assert token not in invitation.model_dump_json()


async def test_invitation_cannot_request_founder_operator(invitations):
    with pytest.raises(ForbiddenError):
        await invitations.create_invitation(
            email="new@olympus.example",
            role_template_ids=["founder_operator"],
            allowed_environments=[],
            invited_by="founder",
        )


async def test_invitation_cannot_request_emergency_root(invitations):
    with pytest.raises(ForbiddenError):
        await invitations.create_invitation(
            email="new@olympus.example",
            role_template_ids=["emergency_root"],
            allowed_environments=[],
            invited_by="founder",
        )


async def test_invitation_ttl_is_clamped(invitations):
    _, _token = await invitations.create_invitation(
        email="a@olympus.example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
        ttl_hours=1000,
    )
    invitation = (await invitations.list_invitations())[0]
    from services.kyber.identity.principals import parse_timestamp

    from datetime import datetime, timedelta, timezone

    expires = parse_timestamp(invitation.expires_at)
    assert expires <= datetime.now(timezone.utc) + timedelta(hours=48, minutes=1)


async def test_expired_invitation_is_denied(invitations):
    invitation, token = await invitations.create_invitation(
        email="new@olympus.example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
    )
    await invitations.repo.update(
        invitation.invitation_id, {"expires_at": "2020-01-01T00:00:00+00:00"}
    )
    with pytest.raises(ForbiddenError):
        await invitations.accept_invitation(
            token=token,
            google_subject="google-subject-new",
            email="new@olympus.example",
            display_name="New Hire",
        )


async def test_reused_invitation_is_denied(invitations, principals):
    invitation, token = await invitations.create_invitation(
        email="new@olympus.example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
    )
    principal = await invitations.accept_invitation(
        token=token,
        google_subject="google-subject-new",
        email="new@olympus.example",
        display_name="New Hire",
    )
    assert principal.employment_status == "active"
    assert await principals.role_template_ids(principal.operator_id) == ["observer"]

    with pytest.raises(ForbiddenError):
        await invitations.accept_invitation(
            token=token,
            google_subject="google-subject-other",
            email="new@olympus.example",
            display_name="Impostor",
        )


async def test_invitation_email_mismatch_is_denied(invitations):
    _invitation, token = await invitations.create_invitation(
        email="invited@olympus.example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
    )
    with pytest.raises(ForbiddenError):
        await invitations.accept_invitation(
            token=token,
            google_subject="google-subject-forwarded",
            email="someone.else@olympus.example",
            display_name="Forwarded",
        )


async def test_revoked_invitation_is_denied(invitations):
    invitation, token = await invitations.create_invitation(
        email="new@olympus.example",
        role_template_ids=["observer"],
        allowed_environments=[],
        invited_by="founder",
    )
    await invitations.revoke_invitation(invitation.invitation_id, actor_id="founder")
    with pytest.raises(ForbiddenError):
        await invitations.accept_invitation(
            token=token,
            google_subject="google-subject-new",
            email="new@olympus.example",
        )


async def test_unknown_invitation_token_is_denied(invitations):
    with pytest.raises(ForbiddenError):
        await invitations.accept_invitation(
            token="not-a-real-token",
            google_subject="google-subject-new",
            email="new@olympus.example",
        )


async def test_invited_principal_holds_no_authority_before_acceptance(
    invitations, principals
):
    await invitations.create_invitation(
        email="pending@olympus.example",
        role_template_ids=["operations_command"],
        allowed_environments=[],
        invited_by="founder",
    )
    principal = await principals.get_by_email("pending@olympus.example")
    assert principal.employment_status == "invited"
    assert await principals.effective_capabilities(principal.operator_id) == frozenset()


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _enable_bootstrap(email: str = "founder@olympus.example", subject: str = "") -> None:
    os.environ["KYBER_BOOTSTRAP_ENABLED"] = "true"
    os.environ["KYBER_BOOTSTRAP_FOUNDER_EMAIL"] = email
    if subject:
        os.environ["KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT"] = subject
    else:
        os.environ.pop("KYBER_BOOTSTRAP_FOUNDER_GOOGLE_SUBJECT", None)


async def test_bootstrap_is_unavailable_when_the_gate_is_off():
    os.environ["KYBER_BOOTSTRAP_ENABLED"] = "false"
    service = FounderBootstrapService()
    assert await service.is_available() is False
    with pytest.raises(ForbiddenError):
        await service.bootstrap(
            google_subject="s", email="founder@olympus.example", display_name=None
        )


async def test_bootstrap_refuses_when_a_principal_exists(principals):
    await _active_principal(principals)
    _enable_bootstrap()
    service = FounderBootstrapService()
    assert await service.is_available() is False
    with pytest.raises(ConflictError):
        await service.bootstrap(
            google_subject="founder-subject",
            email="founder@olympus.example",
            display_name="Founder",
        )


async def test_bootstrap_refuses_a_non_founder_email():
    _enable_bootstrap()
    service = FounderBootstrapService()
    with pytest.raises(ForbiddenError):
        await service.bootstrap(
            google_subject="someone-subject",
            email="someone@olympus.example",
            display_name="Someone",
        )


async def test_bootstrap_refuses_a_mismatched_google_subject():
    _enable_bootstrap(subject="the-real-founder-subject")
    service = FounderBootstrapService()
    with pytest.raises(ForbiddenError):
        await service.bootstrap(
            google_subject="a-different-subject",
            email="founder@olympus.example",
            display_name="Founder",
        )


async def test_bootstrap_creates_one_founder_and_disables_itself(principals):
    _enable_bootstrap()
    service = FounderBootstrapService()
    assert await service.is_available() is True

    principal = await service.bootstrap(
        google_subject="founder-subject",
        email="Founder@Olympus.Example",
        display_name="Founder",
        client_ip="10.0.0.1",
        user_agent="pytest",
    )
    assert principal.employment_status == "active"
    assert await principals.role_template_ids(principal.operator_id) == [
        "founder_operator"
    ]
    assert "kyber.workforce.manage" in await principals.effective_capabilities(
        principal.operator_id
    )

    # Second attempt fails even though the environment gate is still on.
    assert os.environ["KYBER_BOOTSTRAP_ENABLED"] == "true"
    assert await service.is_available() is False
    with pytest.raises(ConflictError):
        await service.bootstrap(
            google_subject="founder-subject",
            email="founder@olympus.example",
            display_name="Founder",
        )


async def test_bootstrap_marker_survives_principal_removal(principals):
    _enable_bootstrap()
    service = FounderBootstrapService()
    principal = await service.bootstrap(
        google_subject="founder-subject",
        email="founder@olympus.example",
        display_name="Founder",
    )
    await principals.principals.delete(principal.operator_id)
    service._consumed_in_process = False

    assert await principals.count_principals() == 0
    assert await service.is_available() is False
    with pytest.raises(ConflictError):
        await service.bootstrap(
            google_subject="founder-subject",
            email="founder@olympus.example",
            display_name="Founder",
        )


# ── Directory freshness ───────────────────────────────────────────────────────

async def test_directory_freshness_denies_an_unknown_principal():
    fresh, reason = await directory_sync_service.directory_freshness("op_missing")
    assert fresh is False
    assert reason == "principal_unknown"


async def test_directory_freshness_denies_a_suspended_principal(principals):
    principal = await _active_principal(principals, templates=["founder_operator"])
    await principals.suspend(principal.operator_id, actor_id="founder", reason="review")
    fresh, reason = await directory_sync_service.directory_freshness(
        principal.operator_id
    )
    assert fresh is False
    assert reason == "principal_inactive"


async def test_unprivileged_principal_is_fresh_without_a_directory(principals):
    principal = await _active_principal(principals, templates=["observer"])
    fresh, reason = await directory_sync_service.directory_freshness(
        principal.operator_id
    )
    assert fresh is True
    assert reason is None


async def test_privileged_principal_is_denied_when_strict_sync_is_required(
    principals, monkeypatch
):
    principal = await _active_principal(principals, templates=["founder_operator"])
    monkeypatch.setenv("KYBER_DIRECTORY_SYNC_REQUIRED", "true")
    fresh, reason = await directory_sync_service.directory_freshness(
        principal.operator_id
    )
    assert fresh is False
    assert reason == "directory_sync_unconfigured"


async def test_unconfigured_reconcile_does_not_mark_a_principal_fresh(principals):
    principal = await _active_principal(principals, templates=["observer"])
    result = await directory_sync_service.reconcile_principal(principal.operator_id)
    assert result.action == "not_configured"
    refreshed = await principals.get_by_operator_id(principal.operator_id)
    assert refreshed.last_directory_sync_at is None
