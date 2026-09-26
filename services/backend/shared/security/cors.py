"""Cross-origin allowances: the request headers browsers may send, and per-PR
frontend preview origins.

A preview of the Aether app for pull request N is served at
``https://pr-N.<suffix>`` (an Amplify branch of the preview app). The API
sends credentials cross-origin, so the allowance is built here from a host
suffix rather than accepted as a free-form regex from configuration: only
``https://pr-<digits>.<suffix>`` can ever match, and production never
honors it.
"""

from __future__ import annotations

import re
from typing import Optional

# Request headers the first-party browser apps send on every API call
# (frontend/aether and frontend/kyber REST clients). A header missing here
# fails the CORS preflight with 400 "Disallowed CORS headers", which the
# browser reports as "Failed to fetch" for every request, sign-in included.
CORS_ALLOW_HEADERS: tuple[str, ...] = (
    "Authorization",
    "Content-Type",
    "X-API-Key",
    "X-Request-ID",
    "X-Correlation-ID",
    "X-Aether-Environment",
    "X-Kyber-Environment",
)

# One DNS label at a time: letters, digits and inner hyphens; at least two
# labels (e.g. "d1abc.amplifyapp.com").
_HOST_SUFFIX = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def preview_origin_regex(suffix: str, environment: str) -> Optional[str]:
    """The allowed-origin regex for previews, or None when previews are off.

    Raises ValueError for a malformed suffix or when set in production, so a
    misconfiguration fails at startup instead of widening CORS.
    """
    suffix = (suffix or "").strip().lower()
    if not suffix:
        return None
    if environment == "production":
        raise ValueError("CORS_PREVIEW_ORIGIN_SUFFIX must not be set in production")
    if not _HOST_SUFFIX.fullmatch(suffix):
        raise ValueError(f"CORS_PREVIEW_ORIGIN_SUFFIX is not a host name: {suffix!r}")
    return rf"https://pr-[0-9]{{1,7}}\.{re.escape(suffix)}"


__all__ = ["preview_origin_regex"]
