"""Walmart Marketplace credential validation and base-URL resolution (:class:`AuthAdapter`).

The credential is ``{'consumer_id': str, 'private_key': str}`` — the Walmart
Marketplace seller application consumer id and the private key used to sign the
OAuth 2.0 client_credentials grant. The API base is FIXED at
``https://marketplace.walmartapis.com`` and routed through
:func:`validated_https_host <shared.security.ssrf.validated_https_host>` with a
fixed ``marketplace.walmartapis.com`` allowlist, so no tenant value can steer
the outbound host.

This build is STRUCTURAL ONLY in CI: ``validate_credentials`` and ``test`` make
no network calls — the live OAuth client_credentials exchange (signed with the
private key) is a certification-level follow-on and is NOT claimed as a build
fact. No secret material is ever included in an error message or detail.
"""

from __future__ import annotations

from typing import Any

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import AdapterResult, AdapterStatus
from shared.security.ssrf import validated_https_host

REQUIRED_CREDENTIAL_FIELDS = ("consumer_id", "private_key")
# Fixed API host — never tenant-selected. The allowlist is the SSRF gate.
API_HOST = "https://marketplace.walmartapis.com"
API_HOST_ALLOWLIST: tuple[str, ...] = ("marketplace.walmartapis.com",)
API_BASE_PATH = ""


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
    for key in ("consumer_id", "private_key", "access_token"):
        value = plain.get(key)
        if value is not None:
            out[key] = value
    if "access_token" not in out and plain.get("token") is not None:
        out["access_token"] = plain["token"]
    return out


def _base_url(context: AcquisitionContext) -> str:
    """The SSRF-validated Walmart Marketplace API base."""
    host = validated_https_host(API_HOST, allow_suffixes=API_HOST_ALLOWLIST)
    if not host:
        return ""
    return f"https://{host}{API_BASE_PATH}"


def _missing_fields(context: AcquisitionContext) -> list[str]:
    cred = _credential_dict(context)
    return [
        name for name in REQUIRED_CREDENTIAL_FIELDS
        if not str(cred.get(name) or "").strip()
    ]


class WalmartAuthAdapter:
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
                data={"detail": "walmart api base failed SSRF allowlist validation"},
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural-only test: no live OAuth client_credentials exchange claimed."""
        result = await self.validate_credentials(context)
        if not result.success:
            return result
        return AdapterResult.ok(
            {
                "detail": "walmart credential structure valid; live OAuth "
                "client_credentials exchange (signed with the private key) is a "
                "certification-level follow-on (not claimed this build)",
                "base_url": _base_url(context),
                "status": "structural_ok",
            }
        )


__all__ = [
    "API_BASE_PATH",
    "API_HOST",
    "API_HOST_ALLOWLIST",
    "WalmartAuthAdapter",
    "REQUIRED_CREDENTIAL_FIELDS",
    "_base_url",
    "_credential_dict",
]
