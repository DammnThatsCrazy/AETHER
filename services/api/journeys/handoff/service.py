"""Server-owned cross-device journey handoff.

A source device (for example the mobile SDK) asks the backend for a short-lived,
single-use handoff token bound to its tenant, app namespace, journey and
session. The destination device (for example the web SDK) redeems it. A
successful redemption is *explicit* evidence that one party controlled both
sessions at that moment, so the journey continues on the destination with
``link_basis = "explicit_handoff"``.

What a handoff is not: it does not merge identities, assert a user ID, or make
the anonymous IDs one subject. Identity resolution still decides that from its
own evidence; the handoff is recorded as a distinguishable link so inferred
stitching (fingerprint, timing, campaign) is never confused with it.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta
from typing import Any, Optional

from repositories.journey_handoff_repo import get_journey_handoff_repository
from shared.common.common import utc_now

TOKEN_PREFIX = "hnd_"
DEFAULT_TTL_SECONDS = 600
MAX_TTL_SECONDS = 900
LINK_BASIS_EXPLICIT = "explicit_handoff"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean(value: Optional[str], limit: int = 256) -> str:
    return (value or "").strip()[:limit]


async def issue_handoff(
    *,
    tenant_id: str,
    app_namespace: str,
    journey_id: str,
    session_id: str,
    anonymous_id: str,
    platform: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    journey_id, session_id, anonymous_id = (
        _clean(journey_id), _clean(session_id), _clean(anonymous_id),
    )
    if not (journey_id and session_id and anonymous_id):
        raise ValueError("journey_id, session_id and anonymous_id are required")
    ttl = max(30, min(int(ttl_seconds), MAX_TTL_SECONDS))
    now = utc_now()
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    record = await get_journey_handoff_repository().issue({
        "token_hash": hash_token(token),
        "handoff_id": f"hof_{uuid.uuid4().hex}",
        "tenant_id": tenant_id,
        "app_namespace": app_namespace,
        "journey_id": journey_id,
        "source_session_id": session_id,
        "source_anonymous_id": anonymous_id,
        "source_platform": _clean(platform, 32) or "unknown",
        "created_at": now,
        "expires_at": now + timedelta(seconds=ttl),
    })
    # The raw token is returned exactly once and never stored.
    return {"token": token, "handoff_id": record["handoff_id"], "expires_at": record["expires_at"]}


async def redeem_handoff(
    *,
    tenant_id: str,
    app_namespace: str,
    token: str,
    session_id: str,
    anonymous_id: str,
    platform: str,
) -> tuple[Optional[dict[str, Any]], str]:
    """Redeem a token. Returns (link, "") or (None, reason) — reason is internal."""
    session_id, anonymous_id = _clean(session_id), _clean(anonymous_id)
    if not token.startswith(TOKEN_PREFIX) or not (session_id and anonymous_id):
        return None, "invalid_request"
    record, reason = await get_journey_handoff_repository().redeem(
        tenant_id=tenant_id,
        app_namespace=app_namespace,
        token_hash=hash_token(token),
        session_id=session_id,
        anonymous_id=anonymous_id,
        platform=_clean(platform, 32) or "unknown",
    )
    if record is None:
        return None, reason
    if record["source_session_id"] == session_id:
        # Same session on both ends proves nothing new; the token is already
        # spent, which is the safe outcome.
        return None, "same_session"
    return {
        "handoff_id": record["handoff_id"],
        "journey_id": record["journey_id"],
        "link_basis": LINK_BASIS_EXPLICIT,
        "evidence_status": "server_verified_token",
        "identity_merge": "not_performed",
        "from": {
            "session_id": record["source_session_id"],
            "anonymous_id": record["source_anonymous_id"],
            "platform": record["source_platform"],
        },
        "to": {
            "session_id": record["redeemed_session_id"],
            "anonymous_id": record["redeemed_anonymous_id"],
            "platform": record["redeemed_platform"],
        },
        "redeemed_at": record["redeemed_at"],
    }, ""


async def list_handoffs(tenant_id: str, journey_id: str) -> list[dict[str, Any]]:
    rows = await get_journey_handoff_repository().list_for_journey(tenant_id, journey_id)
    return [
        {
            "handoff_id": r["handoff_id"],
            "journey_id": r["journey_id"],
            "state": r["state"],
            "link_basis": LINK_BASIS_EXPLICIT if r["state"] == "redeemed" else None,
            "from_session_id": r["source_session_id"],
            "from_platform": r["source_platform"],
            "to_session_id": r.get("redeemed_session_id"),
            "to_platform": r.get("redeemed_platform"),
            "created_at": r["created_at"],
            "redeemed_at": r.get("redeemed_at"),
        }
        for r in rows
    ]
