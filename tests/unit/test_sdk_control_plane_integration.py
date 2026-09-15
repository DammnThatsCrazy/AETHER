"""A site install as a managed integration of the Reconciled Control Plane.

The SDK distribution layer and the control plane meet at one seam: a registered
site becomes an integration the plane can observe, register and admit. What is
worth testing is not that the calls happen but that they are safe to make from
where they are made:

  * an install must never accumulate control-plane rows for a plane the deploy
    is not running (the plane defaults OFF);
  * a control-plane write must never fail a tenant's install path — the site
    record is already durable by the time this runs;
  * a site without identity must be refused rather than filed under a guessed
    key, because a guessed key is how one tenant's install lands on another
    tenant's surface;
  * the version the plane reconciles is the version the distribution layer
    derives its own drift verdict from, so the two cannot disagree about a site.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from services.sdk_distribution.control_plane import (  # noqa: E402
    INTEGRATION_KIND_SITE,
    SOURCE_ORIGIN_SITE,
    SOURCE_OWNER_SITE,
    register_site_install,
    site_install_observation,
    site_integration_ref,
)

SITE = "site_0123456789abcdef"
TENANT = "tenant-a"


def _run(coro):
    return asyncio.run(coro)


def _site(**overrides) -> dict:
    return {
        "id": SITE,
        "tenant_id": TENANT,
        "name": "Marketing site",
        "origins": ["https://example.com"],
        "environment": "production",
        "status": "active",
        **overrides,
    }


def _described_install(**overrides) -> dict:
    return {
        "state": "live",
        "status": "live",
        "signals": {"sdk_loaded": {"count": 1}},
        "signals_observed": ["sdk_loaded"],
        "signals_missing": ["sdk_initialized", "sdk_init_failed"],
        "last_signal": "sdk_loaded",
        "last_signal_at": "2026-09-06T11:00:00+00:00",
        "first_signal_at": "2026-09-06T11:00:00+00:00",
        "age_seconds": 60.0,
        "install_mode": "snippet",
        "loader_version": "0.1.0-alpha.0",
        "sdk_version": "0.1.0-alpha.0",
        "compatibility_tier": "supported",
        "desired_version": "0.1.0-alpha.0",
        "drift_status": "current",
        "reason": None,
        "warnings": [],
        **overrides,
    }


# ── Identity ─────────────────────────────────────────────────────────────────

def test_the_site_id_is_the_integration_id_and_survives_re_prefixing():
    """One identifier, not two.

    ``site_id`` is already the key every SDK authority uses — the snippet's
    data-site, the request header, the install row — so the plane reuses it
    instead of minting a second id that would need its own mapping table.
    """
    assert site_integration_ref(SITE) == SITE
    # Idempotent: an already-prefixed id is not prefixed again.
    assert site_integration_ref(site_integration_ref(SITE)) == SITE
    # A bare id (a caller that stripped the prefix) is namespaced, not collided
    # with a fleet installation id.
    assert site_integration_ref("0123456789abcdef") == f"site_0123456789abcdef"


def test_the_registered_kind_and_origin_are_declared_vocabulary():
    """A kind or origin outside the plane's §6/§16 vocabulary is rejected by
    the plane's own admission, so naming one here would fail at runtime."""
    from services.managed_integrations.contracts import (
        INTEGRATION_SOURCE_ORIGINS,
        MANAGED_INTEGRATION_KINDS,
    )

    assert INTEGRATION_KIND_SITE in MANAGED_INTEGRATION_KINDS
    assert SOURCE_ORIGIN_SITE in INTEGRATION_SOURCE_ORIGINS
    assert SOURCE_OWNER_SITE in ("tenant", "olympus", "provider")


# ── The observation ──────────────────────────────────────────────────────────

def test_the_observation_reads_the_site_environment_as_the_plane_environment():
    snap = site_install_observation(site=_site(), site_install=_described_install())
    assert snap.tenant_id == TENANT
    assert snap.environment_id == "production"
    assert snap.managed_integration_ref == SITE


def test_a_site_with_no_readable_environment_is_not_filed_under_a_real_one():
    snap = site_install_observation(
        site=_site(environment=None), site_install=_described_install()
    )
    assert snap.environment_id == "unknown"


def test_the_observed_version_is_the_field_the_drift_verdict_uses():
    """The distribution layer derives drift_status from loader_version. If the
    plane read sdk_version instead, a site whose loader is current but whose
    bundle is pinned would reconcile against a different fact than the one the
    install page shows."""
    from services.sdk_distribution.versions import describe_install_version

    snap = site_install_observation(
        site=_site(),
        site_install=_described_install(loader_version="0.1.0-alpha.0", sdk_version="9.9.9"),
    )
    assert snap.runtime_version == describe_install_version("0.1.0-alpha.0")["loader_version"]
    assert snap.runtime_version == "0.1.0-alpha.0"


def test_a_site_that_never_installed_observes_as_missing_not_as_drift():
    snap = site_install_observation(site=_site(), site_install=None)
    assert snap.availability == "missing"
    assert snap.provenance == "unknown"


# ── Registration ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_stores():
    """Both stores the seam writes to, emptied between tests."""
    from services.managed_integrations.admission_repository import (
        reset_admission_record_stores,
    )
    from services.managed_integrations.repository import (
        reset_managed_integration_in_memory_store,
    )

    reset_managed_integration_in_memory_store()
    reset_admission_record_stores()
    yield
    reset_managed_integration_in_memory_store()
    reset_admission_record_stores()


@pytest.fixture
def plane_flags(monkeypatch):
    """Swap the plane's flag block in place, as the plane's own tests do.

    The nested block is replaced rather than mutated, and restored on teardown,
    so a test that turns the plane on cannot leak it into the next one.
    """
    import config.settings as config_settings

    original = getattr(config_settings.settings, "reconciled_control", None)

    def _set(**overrides):
        state = {
            "enabled": False,
            "reconciler_enabled": False,
            "kyber_route_enabled": False,
            "scheduler_enabled": False,
        }
        state.update(overrides)
        config_settings.settings.reconciled_control = SimpleNamespace(**state)
        return config_settings.settings.reconciled_control

    yield _set
    config_settings.settings.reconciled_control = original


@pytest.fixture
def plane_on(plane_flags):
    plane_flags(enabled=True)
    yield


@pytest.fixture
def plane_off(plane_flags):
    # The default: the master switch is off and nothing is written.
    plane_flags()
    yield


def test_a_site_install_writes_nothing_while_the_plane_is_off(plane_off):
    """The default path. A deploy that has not adopted the plane must not
    accumulate control-plane rows from tenants installing the SDK."""
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
    )

    assert _run(register_site_install(_site())) is None
    assert _run(
        get_managed_integration_repository().get(
            tenant_id=TENANT, environment_id="production", managed_integration_id=SITE
        )
    ) is None


def test_registering_a_site_registers_the_integration_and_opens_its_admission(plane_on):
    from services.managed_integrations.admission_repository import (
        get_admission_record_repository,
    )
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
    )

    row = _run(register_site_install(_site()))
    assert row is not None
    assert row["managed_integration_id"] == SITE
    assert row["integration_kind"] == INTEGRATION_KIND_SITE
    assert row["source_origin"] == SOURCE_ORIGIN_SITE
    assert row["source_owner"] == SOURCE_OWNER_SITE
    assert row["release_channel"] == "managed_stable"

    admission = _run(
        get_admission_record_repository().get_for_integration(
            tenant_id=TENANT, environment_id="production", managed_integration_ref=SITE
        )
    )
    assert admission is not None
    assert admission["current_stage"] == "discover"
    assert admission["lifecycle_state"] == "monitor"


def test_an_explicit_release_channel_is_honoured_and_never_invented(plane_on):
    """The channel is the tenant's update policy, which this layer does not own.

    Absent one, the contracted default applies — and `managed_stable` is
    deliberately not "follow the newest published build" (§28).
    """
    default = _run(register_site_install(_site()))
    assert default["release_channel"] == "managed_stable"

    explicit = _run(register_site_install(_site(), release_channel="pinned"))
    assert explicit["release_channel"] == "pinned"


def test_registering_twice_is_one_integration_and_one_admission(plane_on):
    from services.managed_integrations.admission_repository import (
        get_admission_record_repository,
    )

    first = _run(register_site_install(_site()))
    second = _run(register_site_install(_site()))
    assert first["managed_integration_id"] == second["managed_integration_id"]
    # The first sighting is the fact; a re-registration refreshes, never resets.
    assert first["first_seen_at"] == second["first_seen_at"]

    records = _run(
        get_admission_record_repository().list(
            tenant_id=TENANT, environment_id="production"
        )
    )
    assert len([r for r in records if r["managed_integration_ref"] == SITE]) == 1


def test_a_site_without_identity_is_refused_rather_than_guessed(plane_on):
    """A guessed key is how one tenant's install lands on another's surface."""
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
    )

    assert _run(register_site_install(_site(id=None))) is None
    assert _run(register_site_install(_site(tenant_id=None))) is None

    repo = get_managed_integration_repository()
    assert _run(repo.list(tenant_id=TENANT)) == []


def test_a_control_plane_failure_never_fails_the_install_path(plane_on, monkeypatch):
    """The site record is durable before this runs. A dropped registration is
    recoverable on the next signal; a 5xx on the caller's request is not."""
    async def _boom(*args, **kwargs):
        raise RuntimeError("plane store unavailable")

    monkeypatch.setattr(
        "services.managed_integrations.repository."
        "ManagedIntegrationRepository.register",
        _boom,
    )
    assert _run(register_site_install(_site())) is None
