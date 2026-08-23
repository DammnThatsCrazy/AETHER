"""Operator-safe cross-tenant credential slot views (never secrets).

The only surface that reads credential state across tenants for the Kyber
operator plane. Every view is built from :data:`CredentialAuthority._SAFE_FIELDS`
via :meth:`CredentialAuthority._safe_view` — the exact same filter every
tenant-facing read already applies — so a secret value can never appear: no
plaintext, no ciphertext, no data key, no raw fingerprint material.

These helpers are read-only and side-effect free. The operator gate lives in
the routers that call them (:mod:`services.providers.credentials.routes`,
:mod:`services.kyber_operator.routes`, :mod:`services.kyber.aggregate`).
"""

from __future__ import annotations

from typing import Any

from services.providers.credentials.authority import CredentialAuthority
from services.providers.credentials.repository import CredentialVersionRepo
from services.providers.credentials.schema import CredentialState


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
    "tenant_credential_slot_states",
]
