"""Registering a site install with the Reconciled Control Plane.

The SDK distribution layer and the Reconciled Control Plane were built to meet
here and did not. A *site* — one property the SDK is installed on — is a managed
integration by the control plane's own definition: a durable thing a tenant owns,
with a desired version, an observed version, and a lifecycle that can drift out
of support. The control plane could already observe an *installed SDK* through
its health agent (``sensors.observed_from_sdk_health``), but a one-tag site
install produced no heartbeat to observe and so was invisible: a tenant whose
snippet was blocked by a CSP header, or whose loader never resolved a bundle,
appeared in the control plane's view exactly as a tenant who had never installed
anything at all.

This module is the whole of that integration, in the direction the layering
requires:

  * **it depends on the control plane, never the reverse.** The control plane
    owns ``ObservedStateSnapshot`` and the §16 admission vocabulary; nothing
    under ``services/managed_integrations`` imports this module or the SDK
    distribution layer, so the plane can be reasoned about — and shipped —
    without an SDK install path existing.
  * **it registers and observes; it never reconciles or mutates.** Nothing here
    builds a ChangeSet, drives an actuator, or writes a site's desired state.
    That is the plane's own governed path, behind the plane's own flags, and the
    CP-08 boundary is the reason the SDK distribution layer does not extend it.
  * **it is off unless the plane is on.** Registration creates rows in the
    plane's stores, so it is gated on the plane's master switch: with
    ``AETHER_RECONCILED_CONTROL_PLANE_ENABLED`` unset (the default) nothing here
    writes anything, and a deploy that has not adopted the plane accumulates no
    control-plane state from tenants installing the SDK.

The three functions are separable on purpose. ``site_integration_facts`` is pure
and answers "what integration is this site?"; ``site_install_observation`` is
pure and answers "what does its install handshake say?"; ``register_site_install``
is the only one that writes, and it writes only lifecycle facts (§16 admission
is explicitly not authorization — CP-03).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.sdk_distribution.control_plane")

#: §6 managed-integration kind for a browser site install. ``sdk_web`` is the
#: declared kind for the web SDK; a site is the web SDK's unit of installation,
#: so nothing new is invented for it.
INTEGRATION_KIND_SITE = "sdk_web"

#: §16 source origin and owner. A site belongs to the tenant whose property it
#: is — the control plane's other origins (``provider``, ``olympus``,
#: ``shared_system``) would each be a claim that someone else owns the install.
SOURCE_ORIGIN_SITE = "tenant"
SOURCE_OWNER_SITE = "tenant"


def site_integration_ref(site_id: str) -> str:
    """The §6 managed-integration id for one site.

    The public ``site_id`` is already the canonical key every SDK authority
    keys a site by — the snippet's ``data-site``, the request's ``X-Aether-Site``,
    the ``sdk_installations`` row — so the control plane reuses it rather than
    minting a second identifier that would need its own mapping table. Site ids
    are prefixed (``site_``) and unguessable, so they cannot collide with a
    fleet installation id.
    """
    return f"site_{site_id}" if not site_id.startswith("site_") else site_id


def site_install_observation(
    *,
    site: Mapping[str, Any],
    site_install: Optional[Mapping[str, Any]] = None,
    observed_at: Any = None,
):
    """The observed-state snapshot for one site's install handshake.

    A thin composition, deliberately: the mapping from an install record to
    CP-12 availability is the control plane's own vocabulary and lives in
    ``sensors`` beside the fleet adapter. Duplicating a line of it here would
    create a second place for the two to disagree about what ``failed`` means.
    """
    from services.managed_integrations.sensors import observed_from_site_install

    site_id = str(site.get("id") or site.get("site_id") or "")
    return observed_from_site_install(
        managed_integration_ref=site_integration_ref(site_id),
        tenant_id=str(site["tenant_id"]),
        environment_id=_environment_of(site),
        site_install=site_install,
        site_id=site_id,
        observed_at=observed_at,
    )


def _environment_of(site: Mapping[str, Any]) -> str:
    """The control plane's ``environment_id`` for a site.

    A site's ``environment`` is which of the *tenant's own* environments it
    belongs to (``production``/``staging``/``development``) — the same axis the
    plane scopes registrations and reconciles by, so it is used as-is. An
    unreadable value resolves to ``unknown`` rather than being invented, so a
    malformed site cannot be filed under a real environment.
    """
    environment = site.get("environment")
    return str(environment) if environment else "unknown"


async def register_site_install(
    site: Mapping[str, Any],
    *,
    release_channel: Optional[str] = None,
) -> Optional[dict]:
    """Register one site with the control plane and open its §16 admission.

    Idempotent in both halves — a site installed on two pages is one site, and
    the plane's registration and admission are keyed, so re-running this on
    every install signal is safe and is what the callers do.

    Returns the registration row, or ``None`` when the plane is switched off or
    registration fails. **Never raises.** The callers run after ingestion has
    already made the tenant's events durable, and a control-plane write must not
    turn a working install into a failed request; a dropped registration is
    recoverable on the next signal, a 502 on ``/v1/batch`` is not. The same
    reasoning governs ``install_verifier.record_install_signals``.
    """
    from services.managed_integrations import flags

    if not flags.enabled():
        # Default path. The plane is not deployed, so an install must not
        # accumulate control-plane rows for a plane nobody is running.
        return None

    site_id = str(site.get("id") or site.get("site_id") or "")
    tenant_id = str(site.get("tenant_id") or "")
    if not site_id or not tenant_id:
        # Fail closed and loudly: a site record without identity could only be
        # registered under a guessed key, which is how one tenant's install ends
        # up on another tenant's control-plane surface.
        logger.warning(
            "Refusing to register a site with the control plane without tenant "
            "and site identity (site=%r tenant=%r)",
            site_id or None,
            tenant_id or None,
        )
        return None

    environment_id = _environment_of(site)
    integration_ref = site_integration_ref(site_id)
    try:
        registration = await _register(
            site=site,
            site_id=site_id,
            tenant_id=tenant_id,
            environment_id=environment_id,
            integration_ref=integration_ref,
            release_channel=release_channel,
        )
        await _admit(
            site_id=site_id,
            tenant_id=tenant_id,
            environment_id=environment_id,
            integration_ref=integration_ref,
        )
    except Exception as exc:  # noqa: BLE001 - see the never-raises contract
        logger.warning(
            "Control-plane registration failed tenant=%s site=%s: %s",
            tenant_id,
            site_id,
            exc,
            exc_info=True,
        )
        metrics.increment(
            "sdk_site_control_plane_registration_failed_total",
            labels={"tenant_id": tenant_id},
        )
        return None

    metrics.increment(
        "sdk_sites_registered_with_control_plane", labels={"tenant_id": tenant_id}
    )
    return registration


async def _register(
    *,
    site: Mapping[str, Any],
    site_id: str,
    tenant_id: str,
    environment_id: str,
    integration_ref: str,
    release_channel: Optional[str],
) -> dict:
    """Create-or-refresh the registration row for one site."""
    from services.managed_integrations.contracts import (
        DEFAULT_MANAGED_RELEASE_CHANNEL,
    )
    from services.managed_integrations.repository import (
        get_managed_integration_repository,
    )

    return await get_managed_integration_repository().register(
        managed_integration_id=integration_ref,
        tenant_id=tenant_id,
        environment_id=environment_id,
        integration_kind=INTEGRATION_KIND_SITE,
        # The §16 evidence pointer: the site's own registry row, which is the
        # record that says the site exists and which origins it may be
        # installed on. The install handshake is a different record and is
        # carried by the observation, not by the admission fact.
        source_ref=site_id,
        source_origin=SOURCE_ORIGIN_SITE,
        source_owner=SOURCE_OWNER_SITE,
        # The channel is the tenant's update policy, which this module does not
        # own and must not invent. Absent an explicit policy the contracted
        # default applies — and `managed_stable` deliberately does NOT mean
        # "follow the newest published build" (§28).
        release_channel=release_channel or DEFAULT_MANAGED_RELEASE_CHANNEL,
        lifecycle_state="unknown",
        schema_fingerprint=None,
    )


async def _admit(
    *,
    site_id: str,
    tenant_id: str,
    environment_id: str,
    integration_ref: str,
) -> None:
    """Open the §16 admission record for one site.

    Registration is "the plane knows this integration exists"; admission is
    "this integration has a lifecycle". They are separate surfaces by design,
    and admission grants nothing (CP-03) — the walk from ``discover`` to
    ``observe`` is the plane's own, driven by its own engine.
    """
    from services.managed_integrations.admission import (
        IntegrationAdmissionFacts,
        admit,
    )

    await admit(
        IntegrationAdmissionFacts(
            managed_integration_ref=integration_ref,
            tenant_id=tenant_id,
            environment_id=environment_id,
            source_ref=site_id,
            integration_kind=INTEGRATION_KIND_SITE,
            source_origin=SOURCE_ORIGIN_SITE,
        ),
        # Attribution for the append-only audit surface a later phase adds. The
        # actor is the install itself, not an operator: nobody clicked anything.
        actor="sdk-site-install",
    )


__all__ = [
    "INTEGRATION_KIND_SITE",
    "SOURCE_ORIGIN_SITE",
    "SOURCE_OWNER_SITE",
    "site_integration_ref",
    "site_install_observation",
    "register_site_install",
]
