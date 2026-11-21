"""Organization-system grants for tenant-owned provider accounts.

When a tenant connects its own system (a Shopify store, a CRM, an ad account)
and selects an account, that account becomes a source the tenant owns:
``source_relationship = organization_system``, ``raw_data_owner = tenant``,
source id ``provider-account:<connection>:<account>``. Selecting the account
creates that grant (contract basis: the tenant's own data under its Aether
agreement) so provider raw admission can admit the first sync without a
hand-made grant. Shopify is the reference path.

Never for the reserved Olympus scope (Olympus sources are operator-onboarded in
Kyber) and never twice: an existing active or ambiguous grant is left alone.
Lookup and creation run under a short per-source claim in the shared cache, so
two overlapping account selections on different API processes cannot both
create a grant (which would leave the source ambiguous and refuse its syncs).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.provider_runtime.organization_grants")

ORGANIZATION_RIGHTS_CLASS = "tenant_byod_data"


GRANT_LOCK_TTL_SECONDS = 15
GRANT_LOCK_WAIT_SECONDS = 5.0


class GrantProvisioningBusy(Exception):
    """Another request is provisioning this account's grant; retry shortly."""


def _shared_cache() -> Any:
    try:
        from dependencies.providers import get_cache
        return get_cache()
    except Exception:  # noqa: BLE001 - no platform registry (local tooling)
        return None


@asynccontextmanager
async def _source_claim(cache: Any, tenant_id: str, source_id: str):
    """Serialise get-or-create for one tenant/source across API processes."""
    if cache is None:
        yield
        return
    key = f"provider:org-grant:{tenant_id}:{source_id}"
    deadline = time.monotonic() + GRANT_LOCK_WAIT_SECONDS
    while not await cache.set_nx(key, "1", GRANT_LOCK_TTL_SECONDS):
        if time.monotonic() >= deadline:
            raise GrantProvisioningBusy(source_id)
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        await cache.delete(key)


def _data_category(provider_identity: str) -> str:
    family = (provider_identity or "").split(".", 1)[0]
    return {"shopify": "commerce"}.get(family, "tenant_system")


async def ensure_organization_system_grant(
    connection: Any,
    account_id: str,
    *,
    actor: str,
    grant_service: Any = None,
    cache: Any = None,
) -> Optional[str]:
    """Return the grant id governing this account, creating it when absent."""
    from connectors.integrations.data_rights.models import GrantStatus
    from connectors.provider_runtime.rights_admission import provider_account_source_id

    tenant_id = str(getattr(connection, "tenant_id", "") or "")
    if not tenant_id or tenant_id == OLYMPUS_SOURCE_TENANT_ID or not account_id:
        return None
    if grant_service is None:
        from connectors.integrations.data_rights.service import data_rights_service as grant_service

    source_id = provider_account_source_id(connection.connection_id, account_id)
    async with _source_claim(cache if cache is not None else _shared_cache(), tenant_id, source_id):
        existing = await grant_service._repository.list(  # noqa: SLF001 - same-domain read
            tenant_id=tenant_id, source_id=source_id, status=GrantStatus.ACTIVE,
        )
        live = [g for g in existing if getattr(g, "revoked_at", None) is None]
        if live:
            return live[0].data_rights_grant_id if len(live) == 1 else None
        return await _create(grant_service, connection, tenant_id, source_id, actor)


async def _create(grant_service: Any, connection: Any, tenant_id: str, source_id: str, actor: str) -> str:
    from connectors.integrations.data_rights.models import DataRightsGrantCreate, LegalBasis

    grant = await grant_service.create_grant(DataRightsGrantCreate(
        tenant_id=tenant_id,
        source_id=source_id,
        connector_id=connection.provider_identity,
        connector_class=ORGANIZATION_RIGHTS_CLASS,
        source_manifest_id=connection.provider_identity,
        data_category=_data_category(connection.provider_identity),
        data_sensitivity="confidential",
        raw_data_owner="tenant",
        source_relationship="organization_system",
        tenant_lake_allowed=True,
        tenant_graph_allowed=True,
        tenant_insights_allowed=True,
        legal_basis=LegalBasis.CONTRACT.value,
    ), granted_by_user_id=actor)
    metrics.increment("provider_organization_grants_created_total",
                      labels={"provider": connection.provider_identity.split(".", 1)[0]})
    logger.info("organization_system grant created tenant=%s source=%s", tenant_id, source_id)
    return grant.data_rights_grant_id


__all__ = ["GrantProvisioningBusy", "ensure_organization_system_grant"]
