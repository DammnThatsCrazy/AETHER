"""enqueue_sync_change — the single producer entrypoint other code calls.

Best-effort and flag-gated: when ``settings.client_sync.enabled`` is off this is a
no-op (no runtime behavior change), and any repository error is swallowed so a
change-feed append can never break the mutation it accompanies.
"""
from __future__ import annotations

from typing import Optional

from config.settings import settings
from shared.logger.logger import get_logger

from repositories.client_sync_repo import get_client_sync_repository

logger = get_logger("aether.service.client_sync.emitter")


async def enqueue_sync_change(
    *,
    scope_key: str,
    principal_id: str,
    change_type: str,
    resource_kind: Optional[str] = None,
    resource_id: Optional[str] = None,
    revision: Optional[str] = None,
    source_event_id: Optional[str] = None,
    device_id: Optional[str] = None,
) -> None:
    if not settings.client_sync.enabled:
        return
    try:
        await get_client_sync_repository().enqueue(
            scope_key=scope_key,
            principal_id=principal_id,
            change_type=change_type,
            resource_kind=resource_kind,
            resource_id=resource_id,
            revision=revision,
            source_event_id=source_event_id,
            device_id=device_id,
        )
    except Exception:  # never break the mutation path on a feed append
        logger.warning("client-sync enqueue failed (change_type=%s)", change_type, exc_info=True)
