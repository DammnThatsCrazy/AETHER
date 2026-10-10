"""
Aether Service — Tenant Signer Authority (observation-only)

Binds a tenant to the signer *references* (public addresses) that are authorized
to present payment proofs and sign x402 challenges on its behalf.

This module is strictly observation-only:
    - it records and resolves tenant-scoped signer references, and
    - it answers "is this address a tenant-authorized signer?" queries.
It NEVER holds private key material, NEVER signs anything, and NEVER mutates the
commerce lifecycle (no authorizations, no settlements, no entitlements). All
mutation of commerce state remains in the control plane.

Tenant-scoping is enforced at the collection boundary: ``register_signer`` and
``is_authorized_signer`` always carry a tenant_id, and the store collection is
tenant-keyed in both the in-memory and repo-backed backends.

A tenant with zero signer refs resolves to ``False`` for any address — the
authority never "invents" an authorized signer. This is fail-closed: an
unregistered signer cannot present a payment proof as tenant-authorized.
"""

from __future__ import annotations

from typing import Optional

from shared.logger.logger import get_logger

from .commerce_models import SignerRef
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.signer_authority")


def _norm_address(address: str) -> str:
    return (address or "").strip().lower()


class SignerAuthority:
    """Observation-only tenant signer-reference registry."""

    def __init__(self) -> None:
        self._store = get_commerce_store()

    async def register_signer(
        self,
        tenant_id: str,
        address: str,
        chain: str = "eip155:8453",
        label: str = "",
        role: str = "payment",
        added_by: str = "operator",
    ) -> SignerRef:
        """Record a tenant-authorized signer reference (public address only)."""
        if not address or not address.strip():
            raise ValueError("signer address is required")
        ref = SignerRef(
            tenant_id=tenant_id,
            address=_norm_address(address),
            chain=chain,
            label=label,
            role=role,
            added_by=added_by,
        )
        await self._store.put_signer_ref(ref)
        logger.info(
            "signer ref registered tenant=%s address=%s... chain=%s role=%s",
            tenant_id, _norm_address(address)[:8], chain, role,
        )
        return ref

    async def list_signers(
        self, tenant_id: str, active: Optional[bool] = None, role: Optional[str] = None
    ) -> list[SignerRef]:
        """List the tenant's signer references (optionally active/role filtered)."""
        refs = await self._store.list_signer_refs(tenant_id, active=active)
        if role:
            refs = [r for r in refs if r.role == role]
        return refs

    async def is_authorized_signer(
        self, tenant_id: str, address: str, role: Optional[str] = None
    ) -> bool:
        """Fail-closed: True only when the address is an active tenant signer ref."""
        if not address:
            return False
        wanted = _norm_address(address)
        refs = await self._store.list_signer_refs(tenant_id, active=True)
        for ref in refs:
            if ref.address == wanted:
                if role and ref.role != role:
                    continue
                return True
        return False

    async def deactivate_signer(self, tenant_id: str, signer_ref_id: str) -> Optional[SignerRef]:
        """Deactivate a signer reference (revocation; the row is retained for audit)."""
        updated = await self._store.deactivate_signer_ref(tenant_id, signer_ref_id)
        if updated is not None:
            logger.info(
                "signer ref deactivated tenant=%s ref=%s", tenant_id, signer_ref_id
            )
        return updated

    async def count_active(self, tenant_id: str) -> int:
        """Number of active signer refs for the tenant (for audit/diagnostics)."""
        return len(await self._store.list_signer_refs(tenant_id, active=True))

    async def has_configured_signers(self, tenant_id: str) -> bool:
        """True when the tenant has EVER registered a signer reference.

        Counts active AND inactive rows: a revoked registry (all references
        deactivated) still counts as "configured", so the payer gate stays
        enforced rather than reopening when the last active signer is revoked.
        """
        return len(await self._store.list_signer_refs(tenant_id)) > 0

    async def is_payer_authorized(
        self, tenant_id: str, address: str
    ) -> tuple[bool, Optional[str]]:
        """Fail-closed signer gate for the payment proof-verification boundary.

        Returns ``(authorized, reason)``. A tenant that has NEVER registered any
        signer reference (the default for every fresh tenant) is UNAFFECTED:
        the gate returns ``(True, None)`` — the authority never "invents" an
        authorized signer, so a tenant with no signer registry keeps the
        existing verification path untouched. When the tenant HAS configured
        signer references, an address that is not an active, tenant-authorized
        signer (unregistered, or a deactivated reference) is rejected
        fail-closed with a clear reason — even when chain/facilitator
        verification would otherwise succeed. Deactivating the last (or only)
        active signer does NOT reopen the gate: a configured registry with zero
        active signers rejects EVERY payer fail-closed.
        """
        if not await self.has_configured_signers(tenant_id):
            return True, None
        if await self.is_authorized_signer(tenant_id, address):
            return True, None
        if await self.count_active(tenant_id) == 0:
            return (
                False,
                f"tenant {tenant_id!r} has no active signer references (all "
                f"configured signers are deactivated); rejecting all payers "
                f"fail-closed",
            )
        return (
            False,
            f"payer {_norm_address(address)} is not an active tenant-authorized signer",
        )


# ── Module-level singleton ──────────────────────────────────────────────

_authority: Optional[SignerAuthority] = None


def get_signer_authority() -> SignerAuthority:
    global _authority
    if _authority is None:
        _authority = SignerAuthority()
    return _authority


def reset_signer_authority() -> None:
    """Reset the authority — for tests only."""
    global _authority
    _authority = None


__all__ = [
    "SignerAuthority",
    "SignerRef",
    "get_signer_authority",
    "reset_signer_authority",
]
