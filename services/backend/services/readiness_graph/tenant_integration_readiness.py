"""Tenant-contextual integration readiness — honest joined projection (WS-4).

R1 pinned the boundary that this projection sits on:

* ``/v1/integration-readiness`` (catalog_endpoints) projects the *provider
  catalog*'s CredentialReadiness matrix — capability truth, tenant-agnostic.
* ``/v1/tenant-integrations`` projects *tenant record facts* (``connected`` is a
  record fact, NEVER a readiness claim).
* The joined "Connected ≠ Ready" tenant graph was declared a **later
  workstream** — this module is that workstream.

What is emitted, and the evidence each state requires (the honesty law):

``tenant_state`` is a *connection/attention* label for one tenant<->provider
pairing. It is NOT a CredentialReadiness token — provider/capability truth is
always carried separately in ``readiness`` (the manifest's canonical catalog
baseline). Every ``tenant_state`` below is derived ONLY from the tenant record
facts + the manifest's catalog token; a state is never inferred from a parallel
readiness word.

==================  ==========================================================
tenant_state        Evidence required
==================  ==========================================================
available           No stored tenant record (or a residual record with no
                    connection fact) for a provider the catalog still exposes.
connected           A connection record fact exists (enabled OR credential
                    configured OR ever synced) AND no attention/disabled
                    evidence. ``connected`` is a fact — it never claims
                    provider readiness.
connection_disabled The tenant's connection is turned off (sync_status
                    ``disabled``) while a connection fact still exists on the
                    record.
needs_attention     At least one concrete attention signal: provider catalog is
                    on an off-ramp (revoked/suspended/disabled/degraded), sync
                    is failing/degraded, or a credential-requiring provider has
                    no configured credential while the connection is enabled.
ready               The ONE claim that requires proof on BOTH axes: the
                    provider's catalog readiness is sandbox-validated or better
                    (rank >= 60, level >= 4) AND the tenant connection is
                    currently healthy. With every connectable manifest at
                    ``credential_waiting`` today this state is unreachable —
                    which is the honest, intended posture: nothing live may
                    read green.
==================  ==========================================================

The join is deliberately a **cap**: the connection-derived CredentialReadiness
rung (``connection_state_to_readiness``) can never lift an integration above
its manifest's certified catalog token. A healthy tenant sync against a
``credential_waiting`` adapter therefore reads ``tenant_state=connected`` with
``readiness.state=credential_waiting`` — connected, but not capability-ready.
"""

from __future__ import annotations

import enum
from typing import Any, Optional

from shared.certification.readiness import CredentialReadiness, readiness_rank
from shared.integration_contracts.lifecycle import (
    ConnectionState,
    from_connector_sync_status,
)
from shared.integration_contracts.manifest import ProviderManifest

# ── Tenant-contextual state vocabulary ──────────────────────────────────────
# Deliberately NOT a CredentialReadiness token and NOT a ConnectionState member:
# it is a coarse, evidence-labelled projection a tenant surface can render. The
# canonical tokens it derives from are carried alongside (readiness +
# connection.state) so nothing is lost.


class TenantIntegrationState(str, enum.Enum):
    """Coarse tenant-contextual state for one tenant<->provider pairing.

    ``available`` < ``connected`` < ``ready``; ``connection_disabled`` and
    ``needs_attention`` are off-ramps a tenant must act on (ranked below the
    forward progression, mirroring CredentialReadiness' off-ramp discipline).

    Every value is deliberately DISTINCT from every CredentialReadiness wire
    token (a test asserts the sets are disjoint): a tenant_state must never be
    confused with a capability-readiness word.
    """

    AVAILABLE = "available"
    CONNECTED = "connected"
    READY = "ready"
    CONNECTION_DISABLED = "connection_disabled"
    NEEDS_ATTENTION = "needs_attention"


# Off-ramp catalog tokens: the provider itself is revoked/suspended/disabled/
# degraded, so any tenant connection to it needs the tenant's attention.
_CATALOG_OFF_RAMPS: frozenset[CredentialReadiness] = frozenset(
    {
        CredentialReadiness.REVOKED,
        CredentialReadiness.SUSPENDED,
        CredentialReadiness.DISABLED,
        CredentialReadiness.DEGRADED,
    }
)

#: Provider catalog readiness rung (rank) that can justify a ``ready`` claim.
#: Mirrors catalog.py's coarse level: level >= 4 is only ever emitted at or above
#: sandbox-validated. ``ready`` requires the provider to be sandbox-validated or
#: better (never scaffolded/credential-waiting/replay-validated material).
READY_MIN_RANK = readiness_rank(CredentialReadiness.SANDBOX_VALIDATED)

#: Manifest ``authentication.type`` values that require a configured credential
#: before the connection can deliver value. ``none`` requires nothing.
_CREDENTIAL_BEARING_AUTH = frozenset(
    {"api_key", "oauth2", "webhook_only", "composite"}
)

#: Attention-reason wire tokens (the concrete signal(s) behind needs_attention).
REASON_PROVIDER_OFF_RAMP = "provider_off_ramp"
REASON_SYNC_FAILED = "sync_failed"
REASON_SYNC_DEGRADED = "sync_degraded"
REASON_CREDENTIAL_MISSING = "credential_missing"


def _connection_fact(row: dict[str, Any]) -> bool:
    """The R1 record-fact definition of ``connected`` — never a readiness claim."""
    return bool(
        row.get("enabled")
        or row.get("secret_configured")
        or (row.get("sync_status") or "never_synced") != "never_synced"
    )


def _sync_status(row: dict[str, Any]) -> str:
    return row.get("sync_status") or "never_synced"


def connection_state_for(row: dict[str, Any]) -> ConnectionState:
    """Project tenant record facts onto the canonical ConnectionState machine.

    Uses the lifecycle's own ``from_connector_sync_status`` mapping (single
    source), with one refinement: a residual record that holds no connection
    fact (nothing enabled, no credential, never synced) reads ``AVAILABLE`` —
    the tenant has not, in fact, connected anything.
    """
    if not _connection_fact(row):
        return ConnectionState.AVAILABLE
    return from_connector_sync_status(_sync_status(row))


def _catalog_readiness_view(
    manifest: Optional[ProviderManifest],
) -> Optional[dict[str, Any]]:
    """The manifest's canonical catalog baseline, or None when no manifest.

    Shape matches the R1 read-model ``readiness`` facet (state/rank/level) so FE
    zod schemas are reused, never reinvented.
    """
    if manifest is None:
        return None
    state = manifest.readiness.state
    return {
        "state": state.value,
        "rank": readiness_rank(state),
        "level": manifest.readiness.level,
    }


def _attention_reasons(
    row: dict[str, Any],
    manifest: Optional[ProviderManifest],
) -> list[str]:
    """Concrete attention signals, each traceable to a record/manifest fact."""
    reasons: list[str] = []
    sync = _sync_status(row)
    if manifest is not None and manifest.readiness.state in _CATALOG_OFF_RAMPS:
        reasons.append(REASON_PROVIDER_OFF_RAMP)
    if sync == "failed":
        reasons.append(REASON_SYNC_FAILED)
    elif sync == "degraded":
        reasons.append(REASON_SYNC_DEGRADED)
    # An enabled connection on a credential-bearing provider with no credential
    # cannot run — that is "readiness is missing a credential", never a green.
    if (
        bool(row.get("enabled"))
        and manifest is not None
        and manifest.authentication.type in _CREDENTIAL_BEARING_AUTH
        and not row.get("secret_configured")
    ):
        reasons.append(REASON_CREDENTIAL_MISSING)
    return reasons


def tenant_state_for(
    row: Optional[dict[str, Any]],
    manifest: Optional[ProviderManifest],
) -> tuple[TenantIntegrationState, list[str]]:
    """Derive the tenant-contextual state + attention reasons for one pairing.

    Order of precedence (first match wins) is the honest ladder:
    1. no effective record        -> available
    2. catalog/provider off-ramp  -> needs_attention (provider pulled)
    3. failing/degraded sync      -> needs_attention
    4. credential missing on live -> needs_attention
    5. tenant disabled            -> disabled
    6. healthy + certified live   -> ready   (BOTH axes proven)
    7. connection fact present    -> connected
    """
    if row is None:
        return TenantIntegrationState.AVAILABLE, []
    reasons = _attention_reasons(row, manifest)
    if not _connection_fact(row):
        # Residual record (created, then nothing enabled/configured/synced).
        return TenantIntegrationState.AVAILABLE, []
    sync = _sync_status(row)
    if reasons:
        return TenantIntegrationState.NEEDS_ATTENTION, reasons
    if sync == "disabled":
        return TenantIntegrationState.CONNECTION_DISABLED, []
    # Ready requires proof on BOTH axes: a connection that is actually healthy
    # AND a provider catalog token at sandbox-validated or better. A healthy
    # sync can never lift a credential_waiting adapter above its certified rung.
    if (
        sync == "healthy"
        and manifest is not None
        and manifest.readiness.state is not None
        and readiness_rank(manifest.readiness.state) >= READY_MIN_RANK
    ):
        return TenantIntegrationState.READY, []
    return TenantIntegrationState.CONNECTED, []


def project_tenant_integration(
    manifest: Optional[ProviderManifest],
    row: Optional[dict[str, Any]],
    *,
    family: Optional[str] = None,
    display_name: Optional[str] = None,
    source: Optional[str] = None,
) -> dict[str, Any]:
    """Project one (manifest, tenant-record) pairing onto the joined wire shape.

    ``manifest`` is the provider's canonical catalog identity/readiness truth;
    ``row`` is the tenant's stored ConnectorConfig-shaped record (or None).
    The joined honesty contract: ``readiness`` is ALWAYS the manifest catalog
    baseline (never re-derived from the tenant row), and ``tenant_state`` is a
    connection/attention label derived only from record facts — the projection
    never claims provider readiness from tenant evidence, and never lets tenant
    evidence exceed the manifest's certified token.
    """
    state, reasons = tenant_state_for(row, manifest)
    has_row = row is not None
    connection_state = (
        connection_state_for(row).value if has_row else None
    )
    connected_fact = _connection_fact(row) if has_row else False
    family_key = (
        manifest.provider_family
        if manifest is not None
        else (family or (row or {}).get("connector_type") or "")
    )
    item: dict[str, Any] = {
        "key": (
            manifest.identity_key
            if manifest is not None
            else family_key
        ),
        "family": family_key,
        "display_name": (
            manifest.display_name
            if manifest is not None
            else (display_name or (row or {}).get("name") or family_key)
        ),
        "experience_category": (
            _experience_value(manifest) if manifest is not None else None
        ),
        "source": source or _source_for(manifest),
        # Canonical provider/capability truth — manifest catalog baseline only.
        "readiness": _catalog_readiness_view(manifest),
        # Tenant-contextual derived state + its evidence trail.
        "tenant_state": state.value,
        "attention_reasons": reasons,
        "connection": {
            "configured": has_row,
            "connected": connected_fact,
            "state": connection_state,
            "enabled": bool(row.get("enabled")) if has_row else False,
            "secret_configured": bool(row.get("secret_configured")) if has_row else False,
            "sync_status": _sync_status(row) if has_row else "never_synced",
            "last_synced_at": row.get("last_synced_at") if has_row else None,
            "error_count": int(row.get("error_count", 0)) if has_row else 0,
            "last_error_at": row.get("last_error_at") if has_row else None,
        },
    }
    return item


def _experience_value(manifest: ProviderManifest) -> Optional[str]:
    from shared.integration_contracts.experience import experience_category_for

    category = experience_category_for(manifest)
    return category.value if category is not None else None


def _source_for(manifest: Optional[ProviderManifest]) -> str:
    """Catalog source group token (mirrors catalog_endpoints' four-group map)."""
    if manifest is None:
        return "unknown"
    if manifest.product_id == "ads":
        return "ad_platform"
    if manifest.product_id == "payment_rails":
        return "payment_rail"
    if manifest.product_id == "ingestion":
        return "byod_connector"
    return manifest.product_id


#: Tenant-state display ordering (available -> ... ; off-ramps sink last).
_TENANT_STATE_ORDER: dict[TenantIntegrationState, int] = {
    TenantIntegrationState.AVAILABLE: 0,
    TenantIntegrationState.CONNECTED: 1,
    TenantIntegrationState.READY: 2,
    TenantIntegrationState.CONNECTION_DISABLED: 3,
    TenantIntegrationState.NEEDS_ATTENTION: 4,
}


def state_sort_key(state: str) -> int:
    """Stable sort key over the tenant-contextual state vocabulary."""
    try:
        return _TENANT_STATE_ORDER[TenantIntegrationState(state)]
    except (KeyError, ValueError):  # pragma: no cover - defensive
        return 99


__all__ = [
    "READY_MIN_RANK",
    "REASON_CREDENTIAL_MISSING",
    "REASON_PROVIDER_OFF_RAMP",
    "REASON_SYNC_DEGRADED",
    "REASON_SYNC_FAILED",
    "TenantIntegrationState",
    "connection_state_for",
    "project_tenant_integration",
    "state_sort_key",
    "tenant_state_for",
]
