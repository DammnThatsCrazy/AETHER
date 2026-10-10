"""
Aether Service — Tenant Signer Reference Repository

Durable store for tenant-scoped signer references (table ``commerce_signer_refs``).
This repository is the persistence half of the observation-only signer authority:
it stores public references only, never private key material.

Auto-selects PostgreSQL (staging/production) or in-memory dicts (local/test) via
``BaseRepository`` — identical to the other commerce repositories.
"""

from __future__ import annotations

from repositories.repos import BaseRepository


class SignerRefsRepository(BaseRepository):
    """Tenant-scoped signer references (public addresses only)."""

    def __init__(self) -> None:
        super().__init__("commerce_signer_refs")


__all__ = ["SignerRefsRepository"]
