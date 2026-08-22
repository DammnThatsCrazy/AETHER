"""Acquisition context and account discovery types.

:class:`AcquisitionContext` is the immutable-in-shape request every acquisition
adapter (auth, account, pull, webhook, report, stream, reconciliation) receives:
the tenant, the per-capability identity, the connection/account scoping, the
non-secret configuration, and — when present — the structured credential.

:class:`ProviderAccount` is the discovery result: the provider-side account
identity plus display metadata. ``extra="allow"`` here is deliberate — provider
account objects routinely carry fields we do not model (timezone, locale,
owner, ...) and dropping them would lose lineage.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.credentials.types import StructuredCredential


class AcquisitionContext(BaseModel):
    """Scoped request context handed to a capability adapter."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    provider_identity: str
    connection_id: str = ""
    account_id: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    credential: Optional[StructuredCredential] = None


class ProviderAccount(BaseModel):
    """A provider-side account discovered by an :class:`AccountAdapter`.

    Unknown provider-specific fields are preserved (``extra="allow"``) rather
    than dropped, so account lineage survives normalization.
    """

    model_config = ConfigDict(extra="allow")

    account_id: str
    display_name: str = ""
    external_id: Optional[str] = None
    currency: Optional[str] = None
    region: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AcquisitionContext",
    "ProviderAccount",
]
