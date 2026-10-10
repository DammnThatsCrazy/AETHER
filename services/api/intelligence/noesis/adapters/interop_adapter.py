"""Noesis Interoperability Intelligence adapter — read-only message traces.

Answers `interop_message_trace` (message + append-only lifecycle timeline
by correlation key or message id) and `interop_path_reliability` (delivery
outcome distribution per path). Observation-only: Noesis never relays,
retries, or recovers cross-chain messages.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.noesis.adapters.interop")

_FAILURE_STATUSES = frozenset({
    "failed", "verification_failed", "delivery_failed", "application_failed",
    "timed_out", "expired", "cancelled", "refunded",
})
_DELIVERED_STATUSES = frozenset({"delivered", "executed", "settled", "recovered"})


def _stringify(row: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()}


class InteropNoesisAdapter:
    """Deterministic lookups over interop_messages and the append-only
    interop_message_events transition log."""

    async def message_trace(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from repositories.interop_repos import (
            InteropMessageEventRepo,
            InteropMessageRepo,
        )

        message_repo = InteropMessageRepo()
        if target:
            message = await message_repo.find_one(
                {"tenant_id": tenant_id, "correlation_key": target},
            ) or await message_repo.find_one(
                {"tenant_id": tenant_id, "interop_message_id": target},
            )
            if message is None:
                return {
                    "answer": f"No cross-chain message found for '{target}' in this tenant.",
                    "results": [],
                    "sources": ["interop_messages"],
                    "sufficient": False,
                }
            timeline = await InteropMessageEventRepo().find_many(
                {
                    "tenant_id": tenant_id,
                    "interop_message_id": message["interop_message_id"],
                },
                limit=200,
            )
            timeline.sort(key=lambda t: str(t.get("observed_at") or ""))
            return {
                "answer": (
                    f"Message {message['interop_message_id']} is '{message.get('status')}' "
                    f"with {len(timeline)} observed lifecycle transition(s)."
                ),
                "results": [_stringify(message)] + [_stringify(t) for t in timeline],
                "sources": ["interop_messages", "interop_message_events"],
                "sufficient": True,
            }

        messages = await message_repo.find_many({"tenant_id": tenant_id}, limit=limit)
        by_status = Counter(str(m.get("status")) for m in messages)
        summary = ", ".join(f"{count} {status}" for status, count in by_status.most_common())
        return {
            "answer": (
                f"{len(messages)} cross-chain message(s) observed"
                + (f" ({summary})" if summary else "")
                + "."
            ),
            "results": [_stringify(m) for m in messages],
            "sources": ["interop_messages"],
            "sufficient": bool(messages),
        }

    async def path_reliability(
        self,
        tenant_id: str,
        target: Optional[str] = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        from repositories.interop_repos import InteropMessageRepo

        filters: dict[str, Any] = {"tenant_id": tenant_id}
        if target:
            filters["path_id"] = target
        messages = await InteropMessageRepo().find_many(filters, limit=2000)

        per_path: dict[str, Counter] = {}
        for message in messages:
            path_id = str(message.get("path_id") or "unknown")
            bucket = per_path.setdefault(path_id, Counter())
            status = str(message.get("status"))
            if status in _DELIVERED_STATUSES:
                bucket["delivered"] += 1
            elif status in _FAILURE_STATUSES:
                bucket["failed"] += 1
            else:
                bucket["in_flight"] += 1

        rows = [
            {
                "path_id": path_id,
                "delivered": bucket["delivered"],
                "failed": bucket["failed"],
                "in_flight": bucket["in_flight"],
                "total": sum(bucket.values()),
            }
            for path_id, bucket in sorted(per_path.items())
        ]
        degraded = [r for r in rows if r["failed"] > 0]
        parts = [f"{len(rows)} path(s) with observed traffic"]
        if degraded:
            parts.append(
                f"{len(degraded)} path(s) have failure-state messages: "
                + ", ".join(r["path_id"] for r in degraded[:5])
            )
        return {
            "answer": "Path reliability: " + "; ".join(parts) + ".",
            "results": rows[:limit],
            "sources": ["interop_messages"],
            "sufficient": bool(rows),
        }
