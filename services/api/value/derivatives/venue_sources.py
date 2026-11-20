"""Venue account sources on the canonical source authorities.

A venue account link binds a tenant subject to one venue account. It is not a
rights record. Behind every link this module provisions the same objects the
provider runtime uses for any other source:

* a :class:`ProviderConnection` for the venue's *account* capability
  (``<venue>.account.<capability>``), holding only a credential reference;
* a :class:`DataRightsGrant` for the source scope
  ``provider-account:<connection_id>:<account_ref>``, classified as
  ``personal_account`` (the subject's own account: wallet proof, read-only key,
  OAuth) or ``organization_system`` (tenant push), with rights-source class
  ``tenant_byod_data``.

Account raw records are then admitted through ``ProviderRawRightsAdmission``
like any provider record, so a revoked link blocks the next write.

Market data is a separate capability (``<venue>.markets.market_data``). Olympus
Labs holds market-data credentials under the reserved ``olympus`` scope and
uses them as reference context only; a tenant may also connect its own
market-data subscription as an ``organization_system`` source. Neither is an
account source and neither is provisioned here.

``SourceRelationship`` is descriptive. It never grants a use; the grant, the
consent receipt and the Rights Authority decide.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

ACCOUNT_PRODUCT = "account"
MARKETS_PRODUCT = "markets"
MARKET_DATA_CAPABILITY = "market_data"
VENUE_RIGHTS_CLASS = "tenant_byod_data"
VENUE_DATA_CATEGORY = "derivatives_account_activity"
VENUE_DATA_SENSITIVITY = "financial"

# How a venue's account data is reached. A wallet venue serves account activity
# from public chain or API data keyed by address, so ownership is proved by a
# wallet signature and no credential exists. A credential venue needs the
# account holder's read-only key or an OAuth token.
WALLET_ACCESS = "public_wallet_address"
API_KEY_ACCESS = "read_only_api_key"
OAUTH_ACCESS = "oauth"


class VenueSourceError(ValueError):
    """A venue source cannot be provisioned (reason is machine-readable)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class VenueSourceProfile:
    venue: str
    display_name: str
    account_capability: str
    account_access: tuple[str, ...]
    market_data: bool = True

    @property
    def account_identity(self) -> str:
        return f"{self.venue}.{ACCOUNT_PRODUCT}.{self.account_capability}"

    @property
    def market_identity(self) -> Optional[str]:
        return f"{self.venue}.{MARKETS_PRODUCT}.{MARKET_DATA_CAPABILITY}" if self.market_data else None

    def accepts(self, access: str) -> bool:
        return access in self.account_access


# One profile per registered venue adapter that can serve account data. Each
# capability names what the account read actually returns.
VENUE_SOURCE_PROFILES: dict[str, VenueSourceProfile] = {
    profile.venue: profile
    for profile in (
        VenueSourceProfile("hyperliquid", "Hyperliquid", "fills_read", (WALLET_ACCESS,)),
        VenueSourceProfile("polymarket", "Polymarket", "activity_read", (WALLET_ACCESS,)),
        VenueSourceProfile("dydx", "dYdX v4", "fills_read", (WALLET_ACCESS,)),
        VenueSourceProfile("gmx", "GMX", "positions_read", (WALLET_ACCESS,)),
        VenueSourceProfile("drift", "Drift", "fills_read", (WALLET_ACCESS,)),
    )
}


def venue_profile(venue: str) -> VenueSourceProfile:
    profile = VENUE_SOURCE_PROFILES.get(str(venue or "").strip().lower())
    if profile is None:
        raise VenueSourceError("venue_not_registered")
    return profile


def relationship_for_method(method: str) -> tuple[str, str]:
    """``(source_relationship, raw_data_owner)`` for a link method."""
    if method == "tenant_push":
        return "organization_system", "tenant"
    if method in ("wallet_proof", "read_only_api_key", "oauth"):
        return "personal_account", "subject"
    raise VenueSourceError("link_method_invalid")


def access_for_method(method: str) -> Optional[str]:
    return {
        "wallet_proof": WALLET_ACCESS,
        "read_only_api_key": API_KEY_ACCESS,
        "oauth": OAUTH_ACCESS,
    }.get(method)


@dataclass(frozen=True)
class VenueSource:
    connection_id: str
    provider_identity: str
    source_id: str
    grant_id: str
    source_relationship: str
    credential_ref: Optional[str] = None


class VenueSourceProvisioner:
    """Create, revoke and erase the connection and grant behind a venue link."""

    def __init__(self, *, orchestrator: Any = None, grant_service: Any = None) -> None:
        self._orchestrator = orchestrator
        self._grants = grant_service

    def _orch(self) -> Any:
        if self._orchestrator is None:
            from connectors.provider_runtime.connection import ConnectionOrchestrator

            self._orchestrator = ConnectionOrchestrator()
        return self._orchestrator

    def _grant_service(self) -> Any:
        if self._grants is None:
            from connectors.integrations.data_rights.service import data_rights_service

            self._grants = data_rights_service
        return self._grants

    async def provision(
        self,
        *,
        tenant_id: str,
        subject_id: str,
        venue: str,
        account_ref: str,
        method: str,
        consent_receipt_id: str,
        actor: str,
        credential: Any = None,
    ) -> VenueSource:
        from connectors.integrations.data_rights.models import DataRightsGrantCreate, LegalBasis
        from connectors.integrations.data_rights.service import GrantClassificationError
        from connectors.provider_runtime.rights_admission import provider_account_source_id

        if tenant_id == OLYMPUS_SOURCE_TENANT_ID:
            # Olympus sources are operator-onboarded; a venue link is tenant data.
            raise VenueSourceError("olympus_scope_not_linkable")
        profile = venue_profile(venue)
        access = access_for_method(method)
        if access is not None and not profile.accepts(access):
            raise VenueSourceError(f"venue_does_not_accept_{access}")
        relationship, owner = relationship_for_method(method)
        if access in (API_KEY_ACCESS, OAUTH_ACCESS) and credential is None:
            raise VenueSourceError("credential_required")
        if access == WALLET_ACCESS and credential is not None:
            raise VenueSourceError("wallet_link_takes_no_credential")

        orchestrator = self._orch()
        connection = await orchestrator.create_connection(
            tenant_id=tenant_id,
            provider_identity=profile.account_identity,
            display_name=f"{profile.display_name} account",
            config={"venue": profile.venue, "link_method": method},
        )
        if credential is not None:
            connection = await orchestrator.store_credential(connection, credential)
        connection.selected_accounts = [account_ref]
        if access == WALLET_ACCESS:
            # The wallet signature already proved control of the account, which
            # is this connection's verification. Credential links stay at
            # credentials_received until their first read succeeds; tenant push
            # links never pull, so they stay available.
            connection = self._advance(connection, ("verifying", "verified", "connected"))
        await orchestrator.connections.upsert(connection)

        source_id = provider_account_source_id(connection.connection_id, account_ref)
        personal = relationship == "personal_account"
        body = DataRightsGrantCreate(
            tenant_id=tenant_id,
            source_id=source_id,
            connector_id=profile.account_identity,
            connector_class=VENUE_RIGHTS_CLASS,
            source_manifest_id=profile.account_identity,
            data_category=VENUE_DATA_CATEGORY,
            data_sensitivity=VENUE_DATA_SENSITIVITY,
            raw_data_owner=owner,
            source_relationship=relationship,
            tenant_lake_allowed=True,
            tenant_graph_allowed=True,
            tenant_insights_allowed=True,
            legal_basis=LegalBasis.CONSENT.value,
            consent_basis=consent_receipt_id,
            subject_ref=subject_id if personal else None,
        )
        try:
            grant = await self._grant_service().create_grant(body, granted_by_user_id=actor)
        except GrantClassificationError as exc:
            await self._discard_connection(connection)
            raise VenueSourceError(exc.reason) from exc
        except Exception:
            await self._discard_connection(connection)
            raise
        return VenueSource(
            connection_id=connection.connection_id,
            provider_identity=profile.account_identity,
            source_id=source_id,
            grant_id=grant.data_rights_grant_id,
            source_relationship=relationship,
            credential_ref=connection.credential_ref or None,
        )

    def _advance(self, connection: Any, states: tuple[str, ...]) -> Any:
        from shared.integration_contracts.lifecycle import ConnectionState

        for state in states:
            connection = self._orch().transition(connection, ConnectionState(state))
        return connection

    async def mark_verified(self, *, tenant_id: str, connection_id: str) -> None:
        """First successful read of a credential link verifies its connection."""
        from shared.integration_contracts.lifecycle import ConnectionState

        connection = await self._orch().connections.find(connection_id)
        if connection is None or connection.tenant_id != tenant_id:
            return
        if connection.state == ConnectionState.CREDENTIALS_RECEIVED:
            connection = self._advance(connection, ("verifying", "verified", "connected"))
            await self._orch().connections.upsert(connection)

    async def rotate_credential(self, *, tenant_id: str, connection_id: Optional[str], credential: Any) -> str:
        """Replace the credential on a link's existing connection."""
        connection = await self._orch().connections.find(connection_id) if connection_id else None
        if connection is None or connection.tenant_id != tenant_id:
            raise VenueSourceError("link_connection_missing")
        if not connection.credential_ref:
            raise VenueSourceError("wallet_link_takes_no_credential")
        from shared.credentials.service import credential_service

        # rotate keeps the ref and replaces the stored version.
        await credential_service.rotate(tenant_id, connection.credential_ref, credential)
        return connection.credential_ref

    async def _discard_connection(self, connection: Any) -> None:
        orchestrator = self._orch()
        try:
            if connection.credential_ref:
                await orchestrator.delete_credential(connection)
        finally:
            await self._close(connection)

    async def _close(self, connection: Any) -> None:
        from shared.integration_contracts.lifecycle import ConnectionState, can_transition

        orchestrator = self._orch()
        for target in (ConnectionState.REVOKED, ConnectionState.DISABLED):
            if can_transition(connection.state, target):
                connection = orchestrator.transition(connection, target)
                break
        await orchestrator.connections.upsert(connection)

    async def revoke(
        self, *, tenant_id: str, connection_id: Optional[str], grant_id: Optional[str],
        actor: str, reason: str,
    ) -> None:
        """Stop new raw writes (grant revoked) and drop the credential."""
        from connectors.integrations.data_rights.models import DataRightsGrantRevoke

        if grant_id:
            grant = await self._grant_service().get_grant(grant_id, tenant_id=tenant_id)
            if grant is not None and getattr(grant, "revoked_at", None) is None:
                await self._grant_service().revoke_grant(
                    grant_id,
                    DataRightsGrantRevoke(revocation_reason=reason or "link_revoked", revoked_by_user_id=actor),
                    tenant_id=tenant_id,
                )
        if connection_id:
            connection = await self._orch().connections.find(connection_id)
            if connection is not None and connection.tenant_id == tenant_id:
                if connection.credential_ref:
                    await self._orch().delete_credential(connection)
                await self._close(connection)


__all__ = [
    "API_KEY_ACCESS",
    "OAUTH_ACCESS",
    "VENUE_SOURCE_PROFILES",
    "VenueSource",
    "VenueSourceError",
    "VenueSourceProfile",
    "VenueSourceProvisioner",
    "WALLET_ACCESS",
    "access_for_method",
    "relationship_for_method",
    "venue_profile",
]
