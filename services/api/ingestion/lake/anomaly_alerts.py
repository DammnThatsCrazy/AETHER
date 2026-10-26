"""Exact RiskSignal evidence binding for tenant-submitted Gold anomaly alerts.

The lake materialization API records a selected alert. Selection remains the
caller's assertion; this helper only establishes that its source-event pointer
belongs to one persisted, exact-subject canonical RiskSignal. It does not infer
an anomaly from an arbitrary risk signal or attest detector coverage.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from pydantic import ValidationError

from intelligence.risk360.contracts import RiskSignal
from intelligence.risk360.store import RiskSignalRepository
from shared.common.common import BadRequestError


def _nonempty(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def verified_anomaly_alert_dimensions(
    *,
    tenant_id: str,
    subject_kind: str,
    subject_id: str,
    dimensions: Mapping[str, Any],
    signal_repository: Optional[RiskSignalRepository] = None,
) -> dict[str, Any]:
    """Return caller dimensions with a verified signal/event evidence triplet.

    An alert may select an event ref explicitly, or omit the event keys when
    its signal has exactly one usable event ref. Ambiguous or inconsistent
    references fail closed. The canonical signal is read using the authenticated
    tenant and must independently name the requested typed subject.
    """
    if not all(_nonempty(value) for value in (tenant_id, subject_kind, subject_id)):
        raise BadRequestError("Anomaly alerts require an exact tenant and typed subject")
    signal_id = _nonempty(dimensions.get("risk_signal_id"))
    if signal_id is None:
        raise BadRequestError("Anomaly alerts require risk_signal_id")

    event_id = _nonempty(dimensions.get("source_event_id"))
    event_source = _nonempty(dimensions.get("source_event_source"))
    if ("source_event_id" in dimensions or "source_event_source" in dimensions) and (
        event_id is None or event_source is None
    ):
        raise BadRequestError("Anomaly source event ID and source must be supplied together")

    repo = signal_repository or RiskSignalRepository()
    record = await repo.get_scoped(tenant_id, signal_id)
    if not isinstance(record, dict):
        raise BadRequestError("Anomaly risk signal is unavailable for this tenant")
    try:
        signal = RiskSignal.model_validate(record)
    except ValidationError as exc:
        raise BadRequestError("Anomaly risk signal is invalid") from exc
    if (
        signal.tenant_id != tenant_id
        or signal.subject_kind != subject_kind
        or signal.subject_id != subject_id
        or signal.signal_id != signal_id
        or _nonempty(signal.source) is None
    ):
        raise BadRequestError("Anomaly risk signal does not match the exact subject")

    event_refs = [
        (ref.id, ref.source)
        for ref in signal.evidence_refs
        if ref.type == "event" and _nonempty(ref.id) and _nonempty(ref.source)
    ]
    if event_id is not None and event_source is not None:
        if event_refs.count((event_id, event_source)) != 1:
            raise BadRequestError("Anomaly source event must match one risk signal evidence ref")
    elif len(event_refs) == 1:
        event_id, event_source = next(iter(event_refs))
    else:
        raise BadRequestError("Anomaly risk signal requires one selected event evidence ref")

    return {
        **dimensions,
        "risk_signal_id": signal_id,
        "source_event_id": event_id,
        "source_event_source": event_source,
    }
