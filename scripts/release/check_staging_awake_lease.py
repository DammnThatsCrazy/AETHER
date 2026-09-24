#!/usr/bin/env python3
"""Fail closed unless the staging awake lease is valid and within its TTL."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"staging awake lease has no valid {field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"staging awake lease has no valid {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def lease_errors(raw: str, now: datetime | None = None) -> list[str]:
    """Validate the canonical lease bounds without exposing its contents."""
    try:
        lease = json.loads(raw)
    except (TypeError, ValueError):
        return ["staging awake lease is missing or malformed"]
    if not isinstance(lease, dict):
        return ["staging awake lease is missing or malformed"]

    errors: list[str] = []
    try:
        since = _timestamp(lease.get("awake_since"), "awake_since")
        until = _timestamp(lease.get("awake_until"), "awake_until")
    except ValueError as exc:
        return [str(exc)]

    extensions = lease.get("extensions", 0)
    if isinstance(extensions, bool) or not isinstance(extensions, int) or extensions < 0:
        return ["staging awake lease has an invalid extension count"]

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    max_hours = 12 if extensions > 0 else 8
    if until <= current:
        errors.append("staging awake lease has expired")
    if since > current:
        errors.append("staging awake lease begins in the future")
    if until <= since:
        errors.append("staging awake lease deadline does not follow its start")
    if until - since > timedelta(hours=max_hours):
        errors.append("staging awake lease exceeds its per-lease TTL")
    if current - since > timedelta(hours=40):
        errors.append("staging awake lease exceeds the total-awake ceiling")
    return errors


def main() -> int:
    errors = lease_errors(os.environ.get("STAGING_AWAKE_LEASE_JSON", ""))
    if errors:
        for error in errors:
            print(f"::error::{error}; refusing staging mutation", file=sys.stderr)
        return 1
    print("staging awake lease valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
