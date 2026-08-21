"""Provider runtime usage metering (best-effort, never breaks the flow).

Mirrors ``services/integrations/connectors/service.py::_meter`` exactly: the
same import path, the same swallow-with-warning semantics. Metering is a side
effect, never a gate — an unavailable billing backend (or an event type the
billing schema does not yet accept) must never break a sync or webhook.
"""

from __future__ import annotations

from shared.logger.logger import get_logger
from services.integrations.connectors.base import now_iso

logger = get_logger("aether.provider_runtime.metering")


async def meter(tenant_id: str, event_type: str, source_id: str | None, source_type: str) -> None:
    """Mirror services/integrations/connectors/service.py _meter EXACTLY (same imports,
    same try/except swallow-with-warning). Metering must never break the flow."""
    try:
        from services.billing.revops import (
            MeteringService, UsageMeteringEvent, UsageMeteringEventRepository,
        )
        svc = MeteringService(UsageMeteringEventRepository())
        await svc.record_event(UsageMeteringEvent(
            tenant_id=tenant_id, event_type=event_type, source_id=source_id,
            source_type=source_type, occurred_at=now_iso(),
        ))
    except Exception as exc:  # pragma: no cover - metering must never break flow
        logger.warning(f"provider_runtime metering failed: {exc}")


__all__ = ["meter"]
