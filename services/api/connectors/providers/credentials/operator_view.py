"""Operator-safe cross-tenant credential slot views (never secrets).

The only surface that reads credential state across tenants for the Kyber
operator plane. Every view is built from :data:`CredentialAuthority._SAFE_FIELDS`
via :meth:`CredentialAuthority._safe_view` — the exact same filter every
tenant-facing read already applies — so a secret value can never appear: no
plaintext, no ciphertext, no data key, no raw fingerprint material.

These helpers are read-only and side-effect free. The operator gate lives in
the routers that call them (:mod:`connectors.providers.credentials.routes`,
:mod:`governance.kyber_operator.routes`, :mod:`governance.kyber.aggregate`).
"""

from __future__ import annotations

from typing import Any, Iterable

from connectors.providers.credentials.authority import CredentialAuthority
from connectors.providers.credentials.repository import CredentialVersionRepo
from connectors.providers.credentials.schema import CredentialState
from connectors.providers.credentials.slot_registry import slots_for


def safe_credential_view(row: dict[str, Any]) -> dict[str, Any]:
    """The non-secret, operator-safe view of one credential-version row.

    Delegates to the authority's static safe-field filter so the operator view
    can never drift from what tenant-facing reads already permit. Callers must
    not pass already-decrypted rows here; this module never decrypts.
    """
    return CredentialAuthority._safe_view(row)


def _slot_key(view: dict[str, Any]) -> tuple[Any, ...]:
    """Deterministic sort key: provider, environment, slot, then version."""
    return (
        view.get("provider") or "",
        view.get("environment") or "",
        view.get("slot_name") or "",
        int(view.get("credential_version") or 0),
    )


async def collect_credential_slot_states(limit: int = 1000) -> dict[str, Any]:
    """Cross-tenant credential slot states (safe views only, deterministic).

    Enumerates every non-tombstoned credential version across tenants and
    returns per-tenant slot states built strictly from the safe-field filter.
    ``by_state`` gives the operator a fleet-wide lifecycle-state rollup;
    individual items carry environment, lifecycle state, credential version,
    last test outcome, and activation/revocation timestamps — never secrets.
    """
    repo = CredentialVersionRepo()
    rows = await repo.find_many(limit=limit)
    tenants: dict[str, list[dict[str, Any]]] = {}
    by_state: dict[str, int] = {}
    total = 0
    for row in rows:
        tenant_id = row.get("tenant_id")
        if not tenant_id or row.get("state") == CredentialState.TOMBSTONED:
            continue
        view = safe_credential_view(row)
        tenants.setdefault(tenant_id, []).append(view)
        total += 1
        state = view.get("state") or "unknown"
        by_state[state] = by_state.get(state, 0) + 1
    items = [
        {"tenant_id": tenant_id, "slot_states": sorted(views, key=_slot_key)}
        for tenant_id, views in sorted(tenants.items())
    ]
    return {
        "items": items,
        "tenant_count": len(items),
        "slot_count": total,
        "by_state": by_state,
    }


async def collect_payment_rail_configured_tenants(
    providers: Iterable[str], *, page_size: int = 1000
) -> dict[str, set[str]]:
    """Authoritative cross-tenant payment-rail credential coverage.

    A tenant is configured for a provider when every required credential slot is
    ``active`` for at least one credential environment (sandbox or live). This is
    the same required-slot rule the adapters use for ``is_configured``; it never
    treats a pending, previous-only, revoked, or failed version as configured.

    Reads only :func:`safe_credential_view` rows, never decrypting a secret. Pages
    the durable credential-version table so a large fleet cannot silently truncate
    configured tenants at the default query limit.
    """
    provider_set = {p for p in providers}
    required = {
        provider: {slot.slot_name for slot in slots_for(provider) if slot.required}
        for provider in provider_set
    }
    slots_by_scope: dict[tuple[str, str, str], set[str]] = {}
    repo = CredentialVersionRepo()
    offset = 0
    while True:
        rows = await repo.find_many(limit=page_size, offset=offset)
        for row in rows:
            tenant_id = row.get("tenant_id")
            view = safe_credential_view(row)
            provider = view.get("provider")
            environment = view.get("environment")
            slot_name = view.get("slot_name")
            if (
                provider not in provider_set
                or not tenant_id
                or not environment
                or not slot_name
                or view.get("state") != CredentialState.ACTIVE
            ):
                continue
            key = (provider, tenant_id, environment)
            slots_by_scope.setdefault(key, set()).add(slot_name)
        if len(rows) < page_size:
            break
        offset += len(rows)

    configured: dict[str, set[str]] = {provider: set() for provider in provider_set}
    for (provider, tenant_id, _environment), active_slots in slots_by_scope.items():
        if required[provider] <= active_slots:
            configured[provider].add(tenant_id)
    return configured


async def tenant_credential_slot_states(tenant_id: str) -> dict[str, Any]:
    """One tenant's credential slot states (safe views only, deterministic).

    Groups the tenant's non-tombstoned versions by environment and lifecycle
    state. Used by the per-tenant operational envelope; the tenant-scoped
    credential API itself continues to serve the tenant through the authority.
    """
    rows = await CredentialVersionRepo().for_tenant(tenant_id)
    views = sorted((safe_credential_view(row) for row in rows), key=_slot_key)
    by_state: dict[str, int] = {}
    by_environment: dict[str, list[dict[str, Any]]] = {}
    for view in views:
        state = view.get("state") or "unknown"
        by_state[state] = by_state.get(state, 0) + 1
        env = view.get("environment") or "unknown"
        by_environment.setdefault(env, []).append(view)
    return {
        "tenant_id": tenant_id,
        "slot_count": len(views),
        "by_state": by_state,
        "by_environment": by_environment,
    }


__all__ = [
    "safe_credential_view",
    "collect_credential_slot_states",
    "collect_payment_rail_configured_tenants",
    "tenant_credential_slot_states",
]
