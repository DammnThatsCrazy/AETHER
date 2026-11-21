"""Close every data source a tenant owns when the tenant is deleted.

Tenant deletion already revokes API keys and erases tenant data. Its sources
must close too, so nothing can acquire or retain data for a tenant that no
longer exists: every active DataRightsGrant is revoked (the revocation fence
then denies any in-flight raw write), and every provider connection loses its
stored credential and is closed (revoked, else disabled).
"""

from __future__ import annotations

from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.provider_runtime.tenant_offboarding")


async def close_tenant_sources(
    tenant_id: str, *, actor: str, reason: str = "tenant_deleted",
    grant_service: Any = None, orchestrator: Any = None,
) -> dict[str, int]:
    from connectors.integrations.data_rights.models import DataRightsGrantRevoke, GrantStatus
    from shared.integration_contracts.lifecycle import ConnectionState, can_transition

    if grant_service is None:
        from connectors.integrations.data_rights.service import data_rights_service as grant_service
    if orchestrator is None:
        from connectors.provider_runtime.connection import ConnectionOrchestrator
        orchestrator = ConnectionOrchestrator()

    counts = {"grants_revoked": 0, "connections_closed": 0, "credentials_deleted": 0}
    for grant in await grant_service.list_grants(tenant_id=tenant_id, status=GrantStatus.ACTIVE):
        if grant.revoked_at is not None:
            continue
        await grant_service.revoke_grant(
            grant.data_rights_grant_id,
            DataRightsGrantRevoke(revocation_reason=reason, revoked_by_user_id=actor),
            tenant_id=tenant_id,
        )
        counts["grants_revoked"] += 1

    connections = [
        c for c in await orchestrator.connections.list_for_tenant(tenant_id, limit=10_000)
        if c.tenant_id == tenant_id
    ]
    # A broker secret may be shared by several rows; every row is closing, so
    # release the extra references and delete each secret exactly once.
    by_ref: dict[str, list[Any]] = {}
    for connection in connections:
        if connection.credential_ref:
            by_ref.setdefault(str(connection.credential_ref), []).append(connection)
    for holders in by_ref.values():
        for extra in holders[:-1]:
            extra.credential_ref = ""
            await orchestrator.connections.upsert(extra)
        await orchestrator.delete_credential(holders[-1])
        counts["credentials_deleted"] += 1

    for connection in connections:
        for target in (ConnectionState.REVOKED, ConnectionState.DISABLED):
            if can_transition(connection.state, target):
                connection = orchestrator.transition(connection, target)
                await orchestrator.connections.upsert(connection)
                counts["connections_closed"] += 1
                break
    logger.info("tenant sources closed tenant=%s %s", tenant_id, counts)
    return counts


__all__ = ["close_tenant_sources"]
