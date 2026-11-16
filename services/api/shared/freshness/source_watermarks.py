"""Per-tenant, per-source pipeline watermarks.

A watermark records the latest instant at which an owning writer or processor
successfully handled data for one canonical authority of one tenant. It answers
"how current is this tenant's copy of that source", which the age of the newest
record cannot: a person with no recent activity is not stale data.

Writers call :func:`advance_source_watermark` after a successful write or a
completed processing pass (including a pass that found nothing new). Advances
are monotonic, throttled per process, and never raise into the write path.
Readers call :func:`read_source_watermarks`; an authority nobody has advanced
reads as ``None`` and must be treated as unknown freshness, never as fresh.
"""

from __future__ import annotations

import functools
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, Optional, TypeVar

from shared.logger.logger import get_logger, metrics
from shared.store import DurableStore, get_store

logger = get_logger("aether.freshness.watermarks")

#: Canonical authorities whose writers advance a watermark. A slot's freshness
#: can only be evaluated against authorities listed here.
WATERMARKED_AUTHORITIES = frozenset(
    {
        "agent_access",
        "ai_execution_facts",
        "analytics_events",
        "communication_facts",
        "economic_facts",
        "geo_observations",
        "relationship_facts",
        "risk_outputs",
    }
)

#: Skip re-advancing the same (tenant, authority) more often than this from
#: one process; a busy writer would otherwise add a store write per record.
ADVANCE_THROTTLE_SECONDS = 15.0

_store: Optional[DurableStore] = None
_last_advanced: dict[tuple[str, str], float] = {}


def _get_store() -> DurableStore:
    global _store
    if _store is None:
        _store = get_store("source_watermarks")
    return _store


def reset_for_tests(store: Optional[DurableStore] = None) -> None:
    """Swap the backing store and clear the throttle (tests only)."""
    global _store
    _store = store
    _last_advanced.clear()


def watermark_key(tenant_id: str, authority: str) -> str:
    return f"wm:{tenant_id}\x1f{authority}"


def _parse(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


async def advance_source_watermark(
    tenant_id: str,
    authority: str,
    *,
    at: Optional[datetime] = None,
    source: str = "",
    force: bool = False,
) -> None:
    """Move the watermark for ``(tenant_id, authority)`` forward to ``at``.

    ``at`` defaults to now. An older instant never moves the watermark back.
    Failures are logged and counted; they never propagate to the caller.
    """
    if not tenant_id or authority not in WATERMARKED_AUTHORITIES:
        return
    instant = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    throttle_key = (tenant_id, authority)
    now_mono = time.monotonic()
    if not force:
        last = _last_advanced.get(throttle_key)
        if last is not None and now_mono - last < ADVANCE_THROTTLE_SECONDS:
            return
    _last_advanced[throttle_key] = now_mono
    iso = instant.isoformat()

    def _advance(current: Optional[dict]) -> dict:
        previous = _parse((current or {}).get("watermark_at"))
        if previous is not None and previous >= instant:
            return current  # type: ignore[return-value]
        return {
            "tenant_id": tenant_id,
            "authority": authority,
            "watermark_at": iso,
            "advanced_by": source or "unspecified",
        }

    try:
        await _get_store().atomic_update(watermark_key(tenant_id, authority), _advance)
    except Exception:  # noqa: BLE001 - freshness bookkeeping never fails a write
        _last_advanced.pop(throttle_key, None)
        metrics.increment("source_watermark_advance_failed", labels={"authority": authority})
        logger.warning("source watermark advance failed", extra={"authority": authority})


async def read_source_watermarks(
    tenant_id: str, authorities: Iterable[str],
) -> dict[str, Optional[str]]:
    """Return each authority's watermark instant (ISO-8601) or ``None``."""
    result: dict[str, Optional[str]] = {}
    for authority in sorted(set(authorities)):
        if authority not in WATERMARKED_AUTHORITIES:
            result[authority] = None
            continue
        try:
            row = await _get_store().get(watermark_key(tenant_id, authority))
        except Exception:  # noqa: BLE001 - an unreadable watermark is unknown
            row = None
        parsed = _parse((row or {}).get("watermark_at"))
        if row and row.get("tenant_id") != tenant_id:
            parsed = None
        result[authority] = parsed.isoformat() if parsed else None
    return result


_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def _tenant_of(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        tenant = value.get("tenant_id")
    else:
        tenant = getattr(value, "tenant_id", None)
    return tenant if isinstance(tenant, str) and tenant else None


def _find_tenant(args: tuple, kwargs: dict, result: Any) -> Optional[str]:
    tenant = kwargs.get("tenant_id")
    if isinstance(tenant, str) and tenant:
        return tenant
    results = list(result) if isinstance(result, (tuple, list)) else [result]
    # All positional arguments: a repository ``self`` carries no tenant_id, and
    # module-level writers take the record as their first argument.
    for candidate in (*results, *args, *kwargs.values()):
        tenant = _tenant_of(candidate)
        if tenant:
            return tenant
    return None


def advances_watermark(authority: str) -> Callable[[_F], _F]:
    """Advance ``authority``'s watermark for the written tenant after success.

    The tenant comes from a ``tenant_id`` keyword, the returned record, or an
    argument record carrying ``tenant_id``. An exception from the write
    propagates unchanged and advances nothing; watermark bookkeeping itself
    never raises.
    """
    if authority not in WATERMARKED_AUTHORITIES:
        raise ValueError(f"{authority!r} is not a watermarked authority")

    def decorate(fn: _F) -> _F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            try:
                tenant = _find_tenant(args, kwargs, result)
            except Exception:  # noqa: BLE001
                tenant = None
            if tenant:
                await advance_source_watermark(tenant, authority, source=fn.__qualname__)
            return result

        return wrapper  # type: ignore[return-value]

    return decorate
