"""Shared security seams for the Aether backend.

Currently exposes the fail-closed server-side request forgery (SSRF) host gate
:func:`shared.security.ssrf.validated_https_host`. The package is additive:
other security helpers may be added here without disturbing existing callers.
"""

from __future__ import annotations

from shared.security.ssrf import validated_https_host

__all__ = [
    "validated_https_host",
]
