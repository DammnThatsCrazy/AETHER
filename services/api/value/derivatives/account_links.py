"""Tenant venue account links: which read-only venue account belongs to which subject.

Account-level venue data (fills, positions, outcome trades) is private to the
tenant that holds the link. A link binds one ``(tenant_id, subject_id)`` to one
``(venue, account_ref)`` and records how the binding was established:

* ``wallet_proof`` — the subject signed a server-issued wallet challenge
  (``identity.identity.verification.WalletVerificationService``). The link
  must cite the resulting ``wallet_ownership_verified`` evidence; the evidence
  must be active, belong to this tenant, hash to this address and namespace,
  and be bound to this same subject.
* ``read_only_api_key`` / ``oauth`` — the subject provided a credential that is
  stored elsewhere; the link keeps only its reference and rejects any mutating
  scope (trade, transfer, withdraw, write).
* ``tenant_push`` — the tenant attests that it already holds this account's
  activity for its own user (for example a broker forwarding its users' data).

Every link requires a consent receipt. Revocation is a status change so later
propagation runs exclude the account; DSR erasure deletes the rows.

No secret is ever persisted here and no venue is ever written to.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Optional

from shared.common.common import utc_now
from value.derivatives.models import DerivativesValidationError, validate_read_only_scopes


LINK_SCAN_LIMIT = 1000


class LinkMethod(StrEnum):
    WALLET_PROOF = "wallet_proof"
    READ_ONLY_API_KEY = "read_only_api_key"
    OAUTH = "oauth"
    TENANT_PUSH = "tenant_push"


class LinkStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class AccountLinkError(DerivativesValidationError):
    """A link request cannot be accepted (reason is machine-readable)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VenueAccountLink:
    link_id: str
    tenant_id: str
    subject_id: str
    venue: str
    account_ref: str
    method: LinkMethod
    consent_receipt_id: str
    status: LinkStatus = LinkStatus.ACTIVE
    chain_namespace: Optional[str] = None
    proof_evidence_id: Optional[str] = None
    credential_ref: Optional[str] = None
    linked_at: str = ""
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None

    def to_record(self) -> dict[str, Any]:
        return {
            "link_id": self.link_id,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "venue": self.venue,
            "account_ref": self.account_ref,
            "method": self.method.value,
            "consent_receipt_id": self.consent_receipt_id,
            "status": self.status.value,
            "chain_namespace": self.chain_namespace,
            "proof_evidence_id": self.proof_evidence_id,
            "credential_ref": self.credential_ref,
            "linked_at": self.linked_at,
            "revoked_at": self.revoked_at,
            "revocation_reason": self.revocation_reason,
            "execution_by_aether": False,
        }

    @classmethod
    def from_record(cls, row: dict[str, Any]) -> "VenueAccountLink":
        return cls(
            link_id=row["link_id"],
            tenant_id=row["tenant_id"],
            subject_id=row["subject_id"],
            venue=row["venue"],
            account_ref=row["account_ref"],
            method=LinkMethod(row["method"]),
            consent_receipt_id=row["consent_receipt_id"],
            status=LinkStatus(row.get("status") or LinkStatus.ACTIVE.value),
            chain_namespace=row.get("chain_namespace"),
            proof_evidence_id=row.get("proof_evidence_id"),
            credential_ref=row.get("credential_ref"),
            linked_at=row.get("linked_at") or "",
            revoked_at=row.get("revoked_at"),
            revocation_reason=row.get("revocation_reason"),
        )


def link_id_for(tenant_id: str, subject_id: str, venue: str, account_ref: str) -> str:
    material = "\x1f".join([tenant_id, subject_id, venue, account_ref])
    return "val_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def _required(value: Optional[str], reason: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AccountLinkError(reason)
    return text


def _known_venue(venue: str) -> str:
    from value.derivatives.adapters import VENUE_ADAPTERS

    key = _required(venue, "venue_required").lower()
    if key not in VENUE_ADAPTERS:
        raise AccountLinkError("venue_not_registered")
    return key


class VenueAccountLinkService:
    """Create, read, revoke, and erase tenant venue account links."""

    def __init__(self, repo: Any = None, evidence_repo: Any = None) -> None:
        if repo is None:
            from repositories.repos import VenueAccountLinkRepository

            repo = VenueAccountLinkRepository()
        self._repo = repo
        self._evidence_repo = evidence_repo
        self.last_ambiguous_accounts: list[tuple[str, str]] = []

    def _evidence(self) -> Any:
        if self._evidence_repo is None:
            from identity.identity.verification_repository import VerificationEvidenceRepository

            self._evidence_repo = VerificationEvidenceRepository()
        return self._evidence_repo

    async def link_wallet(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        venue: str,
        wallet_address: str,
        chain_namespace: str,
        proof_evidence_id: str,
        consent_receipt_id: str,
    ) -> VenueAccountLink:
        from identity.identity.hashing import (
            decrypt_wallet_subject_binding,
            hash_wallet,
            normalize_wallet,
        )
        from identity.identity.models import (
            VerificationEvidenceStatus,
            VerificationEvidenceType,
        )

        tenant_id = _required(tenant_id, "tenant_id_required")
        subject_id = _required(subject_id, "subject_id_required")
        venue = _known_venue(venue)
        consent = _required(consent_receipt_id, "consent_receipt_required")
        namespace = _required(chain_namespace, "chain_namespace_required").lower()
        address = normalize_wallet(_required(wallet_address, "wallet_address_required"), namespace)
        if not address:
            raise AccountLinkError("wallet_address_invalid")
        evidence_id = _required(proof_evidence_id, "wallet_proof_evidence_required")

        row = await self._evidence().get_for_tenant(tenant_id, evidence_id)
        if row is None:
            raise AccountLinkError("wallet_proof_evidence_not_found")
        if row.get("evidence_type") != VerificationEvidenceType.WALLET_OWNERSHIP_VERIFIED.value:
            raise AccountLinkError("wallet_proof_evidence_wrong_type")
        if row.get("status") != VerificationEvidenceStatus.ACTIVE.value:
            raise AccountLinkError("wallet_proof_evidence_inactive")
        if row.get("identifier_hash") != hash_wallet(address, namespace):
            raise AccountLinkError("wallet_proof_address_mismatch")
        ciphertext = str(row.get("subject_hint_ciphertext") or "")
        bound_subject = decrypt_wallet_subject_binding(ciphertext, tenant_id) if ciphertext else ""
        if not bound_subject:
            raise AccountLinkError("wallet_proof_subject_unbound")
        if bound_subject != subject_id:
            raise AccountLinkError("wallet_proof_subject_mismatch")

        return await self._upsert(VenueAccountLink(
            link_id=link_id_for(tenant_id, subject_id, venue, address),
            tenant_id=tenant_id,
            subject_id=subject_id,
            venue=venue,
            account_ref=address,
            method=LinkMethod.WALLET_PROOF,
            consent_receipt_id=consent,
            chain_namespace=namespace,
            proof_evidence_id=evidence_id,
            linked_at=utc_now().isoformat(),
        ))

    async def link_credential(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        venue: str,
        account_ref: str,
        method: LinkMethod,
        credential_ref: str,
        scopes: list[str],
        consent_receipt_id: str,
    ) -> VenueAccountLink:
        if method not in (LinkMethod.READ_ONLY_API_KEY, LinkMethod.OAUTH):
            raise AccountLinkError("credential_link_method_invalid")
        tenant_id = _required(tenant_id, "tenant_id_required")
        subject_id = _required(subject_id, "subject_id_required")
        venue = _known_venue(venue)
        account = _required(account_ref, "account_ref_required")
        consent = _required(consent_receipt_id, "consent_receipt_required")
        ref = _required(credential_ref, "credential_ref_required")
        if not scopes:
            raise AccountLinkError("credential_scopes_required")
        validate_read_only_scopes(list(scopes))
        return await self._upsert(VenueAccountLink(
            link_id=link_id_for(tenant_id, subject_id, venue, account),
            tenant_id=tenant_id,
            subject_id=subject_id,
            venue=venue,
            account_ref=account,
            method=method,
            consent_receipt_id=consent,
            credential_ref=ref,
            linked_at=utc_now().isoformat(),
        ))

    async def link_tenant_push(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        venue: str,
        account_ref: str,
        consent_receipt_id: str,
    ) -> VenueAccountLink:
        tenant_id = _required(tenant_id, "tenant_id_required")
        subject_id = _required(subject_id, "subject_id_required")
        venue = _known_venue(venue)
        account = _required(account_ref, "account_ref_required")
        consent = _required(consent_receipt_id, "consent_receipt_required")
        return await self._upsert(VenueAccountLink(
            link_id=link_id_for(tenant_id, subject_id, venue, account),
            tenant_id=tenant_id,
            subject_id=subject_id,
            venue=venue,
            account_ref=account,
            method=LinkMethod.TENANT_PUSH,
            consent_receipt_id=consent,
            linked_at=utc_now().isoformat(),
        ))

    async def _upsert(self, link: VenueAccountLink) -> VenueAccountLink:
        # One venue account belongs to at most one subject per tenant: a second
        # active owner would make fill attribution ambiguous.
        others = await self._repo.list_for_tenant(
            link.tenant_id, venue=link.venue, status=LinkStatus.ACTIVE.value, limit=LINK_SCAN_LIMIT,
        )
        if any(
            r.get("account_ref") == link.account_ref and r.get("subject_id") != link.subject_id
            for r in others
        ):
            raise AccountLinkError("account_already_linked_to_another_subject")
        record = link.to_record()
        existing = await self._repo.get_for_tenant(link.tenant_id, link.link_id)
        if existing is None:
            await self._repo.insert(link.link_id, record)
        else:
            await self._repo.update(link.link_id, {**existing, **record})
        return link

    async def revoke(self, *, tenant_id: str, link_id: str, reason: str = "") -> Optional[VenueAccountLink]:
        existing = await self._repo.get_for_tenant(_required(tenant_id, "tenant_id_required"), link_id)
        if existing is None:
            return None
        updated = {
            **existing,
            "status": LinkStatus.REVOKED.value,
            "revoked_at": existing.get("revoked_at") or utc_now().isoformat(),
            "revocation_reason": (reason or existing.get("revocation_reason") or "subject_request")[:200],
        }
        await self._repo.update(link_id, updated)
        return VenueAccountLink.from_record(updated)

    async def list_links(
        self,
        tenant_id: str,
        *,
        venue: Optional[str] = None,
        subject_id: Optional[str] = None,
        active_only: bool = True,
    ) -> list[VenueAccountLink]:
        rows = await self._repo.list_for_tenant(
            _required(tenant_id, "tenant_id_required"),
            venue=venue,
            subject_id=subject_id,
            status=LinkStatus.ACTIVE.value if active_only else None,
        )
        return sorted(
            (VenueAccountLink.from_record(r) for r in rows if r.get("tenant_id") == tenant_id),
            key=lambda link: (link.venue, link.subject_id, link.account_ref),
        )

    async def subjects_by_account(self, tenant_id: str, venue: Optional[str] = None) -> dict[tuple[str, str], str]:
        """Active ``(venue, account_ref) -> subject_id`` map for one tenant."""
        mapping, _truncated = await self.subjects_by_account_bounded(tenant_id, venue=venue)
        return mapping

    async def subjects_by_account_bounded(
        self, tenant_id: str, venue: Optional[str] = None, *, limit: int = LINK_SCAN_LIMIT,
    ) -> tuple[dict[tuple[str, str], str], bool]:
        """Active account map plus whether the read hit ``limit``.

        Reads ``limit + 1`` rows so a capped read is reported instead of being
        presented as the tenant's complete linked population.
        """
        rows = await self._repo.list_for_tenant(
            _required(tenant_id, "tenant_id_required"),
            venue=venue,
            status=LinkStatus.ACTIVE.value,
            limit=limit + 1,
        )
        links = sorted(
            (VenueAccountLink.from_record(r) for r in rows if r.get("tenant_id") == tenant_id),
            key=lambda link: (link.venue, link.subject_id, link.account_ref),
        )
        truncated = len(links) > limit
        owners: dict[tuple[str, str], set[str]] = {}
        for link in links[:limit]:
            owners.setdefault((link.venue, link.account_ref), set()).add(link.subject_id)
        # Accounts with more than one active owner (rows written before the
        # single-owner rule) are excluded rather than assigned to one subject.
        self.last_ambiguous_accounts = sorted(k for k, v in owners.items() if len(v) > 1)
        mapping = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}
        return mapping, truncated

    async def erase_subject(self, tenant_id: str, subject_id: str) -> int:
        return await self._repo.delete_by_principal(
            _required(tenant_id, "tenant_id_required"), _required(subject_id, "subject_id_required"),
        )


__all__ = [
    "AccountLinkError",
    "LinkMethod",
    "LinkStatus",
    "VenueAccountLink",
    "VenueAccountLinkService",
    "link_id_for",
]
