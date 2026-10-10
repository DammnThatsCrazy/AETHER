"""Etsy credential validation and base-URL resolution (:class:`AuthAdapter`).

The credential is ``{'shop_id': str, 'client_id': str, 'access_token': str,
'refresh_token': str}`` — the OAuth 2.0 material for the ``openapi.etsy.com``
API. The API base is FIXED at ``https://openapi.etsy.com/v3`` and is routed
through :func:`validated_https_host <shared.security.ssrf.validated_https_host>`
with a fixed ``openapi.etsy.com`` allowlist, so no tenant value can steer the
outbound host.

This build is STRUCTURAL ONLY in CI: ``validate_credentials`` and ``test`` make
no network calls — a real OAuth exchange (PKCE + refresh round-trip, token
replay) is a certification-level follow-on and is NOT claimed as a build fact.
No secret material is ever included in an error message or result ``detail``.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import AdapterResult, AdapterStatus
from shared.security.ssrf import validated_https_host

REQUIRED_CREDENTIAL_FIELDS = ("shop_id", "client_id", "access_token")
# Fixed API host — never tenant-selected. The allowlist is the SSRF gate.
API_HOST = "https://openapi.etsy.com/v3"
API_HOST_ALLOWLIST: tuple[str, ...] = ("openapi.etsy.com",)
API_BASE_PATH = "/v3"


def _credential_dict(context: AcquisitionContext) -> dict[str, Any]:
    """Read the credential defensively as a plain dict (never raises)."""
    cred = context.credential
    if cred is None:
        return {}
    if isinstance(cred, dict):
        return dict(cred)
    try:
        plain: dict[str, Any] = to_plaintext_dict(cred)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover - defensive: unknown credential object
        plain = getattr(cred, "model_dump", lambda: {})()
    out: dict[str, Any] = {}
    for key in ("shop_id", "client_id", "access_token", "refresh_token"):
        value = plain.get(key)
        if value is not None:
            out[key] = value
    if "access_token" not in out and plain.get("token") is not None:
        out["access_token"] = plain["token"]
    return out


def _base_url(context: AcquisitionContext) -> str:
    """The SSRF-validated Etsy API base (``https://openapi.etsy.com/v3``)."""
    host = validated_https_host(API_HOST, allow_suffixes=API_HOST_ALLOWLIST)
    if not host:
        return ""
    return f"https://{host}{API_BASE_PATH}"


def _safe_json(response) -> dict[str, Any]:
    """Best-effort JSON body parse; never raises (adapter must return AdapterResult)."""
    if not getattr(response, "content", None):
        return {}
    try:
        parsed = response.json()
    except Exception:  # noqa: BLE001 - malformed body degrades to an empty dict
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _missing_fields(context: AcquisitionContext) -> list[str]:
    cred = _credential_dict(context)
    return [
        name for name in REQUIRED_CREDENTIAL_FIELDS
        if not str(cred.get(name) or "").strip()
    ]


class EtsyAuthAdapter:
    """AuthAdapter: structural credential + fixed-base check (no live exchange)."""

    async def validate_credentials(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural check: required keys present + fixed base resolves."""
        missing = _missing_fields(context)
        if missing:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )
        if not _base_url(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="api_base_invalid",
                retryable=False,
                data={"detail": "etsy api base failed SSRF allowlist validation"},
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural-only test: no live OAuth exchange is claimed this build.

        A real PKCE/refresh round-trip is a certification-level follow-on. The
        detail says exactly that — a structural pass is never presented as a
        live-verified result.
        """
        result = await self.validate_credentials(context)
        if not result.success:
            return result
        return AdapterResult.ok(
            {
                "detail": "etsy credential structure valid; live OAuth exchange "
                "is a certification-level follow-on (not claimed this build)",
                "base_url": _base_url(context),
                "status": "structural_ok",
            }
        )


__all__ = [
    "API_BASE_PATH",
    "API_HOST",
    "API_HOST_ALLOWLIST",
    "EtsyAuthAdapter",
    "REQUIRED_CREDENTIAL_FIELDS",
    "_base_url",
    "_credential_dict",
    "_safe_json",
]
