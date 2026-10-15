"""TikTok Shop credential validation and request signing (:class:`AuthAdapter`).

The credential is ``{'app_key': str, 'app_secret': str, 'shop_id': str}``. Every
TikTok Shop request is HMAC-signed: the query/body parameters plus a
``timestamp`` and ``nonce`` are sorted and concatenated, then signed with
``HMAC-SHA256(app_secret, material)``. :func:`sign_request` implements this
deterministically (timestamp/nonce are inputs, never wall-clock reads).

The API base is FIXED at ``https://open-api.tiktokglobalshop.com`` and routed
through :func:`validated_https_host <shared.security.ssrf.validated_https_host>`
with a fixed ``open-api.tiktokglobalshop.com`` allowlist, so no tenant value can
steer the outbound host.

This build is STRUCTURAL ONLY in CI: ``validate_credentials`` and ``test`` make
no network calls and exercise the signing path offline with a FIXED reference
timestamp — a live signed request is a certification-level follow-on and is NOT
claimed as a build fact. No secret material is ever included in an error message
or result ``detail``.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import AdapterResult, AdapterStatus
from shared.security.ssrf import validated_https_host

REQUIRED_CREDENTIAL_FIELDS = ("app_key", "app_secret", "shop_id")
# Fixed API host — never tenant-selected. The allowlist is the SSRF gate.
API_HOST = "https://open-api.tiktokglobalshop.com"
API_HOST_ALLOWLIST: tuple[str, ...] = ("open-api.tiktokglobalshop.com",)
API_BASE_PATH = ""

# The test() offline signing exercise uses a FIXED reference timestamp so the
# signature is byte-identical across runs (deterministic, no wall-clock).
_STRUCTURAL_REFERENCE_TIMESTAMP = 1783468800  # 2026-08-08T00:00:00Z
_STRUCTURAL_REFERENCE_NONCE = "synth-nonce"


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
    for key in ("app_key", "app_secret", "shop_id", "shop_cipher"):
        value = plain.get(key)
        if value is not None:
            out[key] = value
    return out


def _base_url(context: AcquisitionContext) -> str:
    """The SSRF-validated TikTok Shop API base."""
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


def sign_request(
    *,
    app_secret: str,
    params: dict[str, Any],
    timestamp: int,
    nonce: str,
) -> str:
    """Deterministically sign a TikTok Shop request; return the hex HMAC-SHA256.

    The material is the sorted ``k=v`` pairs of ``params`` (joined with ``&``)
    plus ``timestamp`` and ``nonce`` appended as ``&timestamp=<t>&nonce=<n>``,
    signed with ``HMAC-SHA256(app_secret, material)``. Identical inputs produce
    byte-identical output — no wall-clock or randomness.
    """
    ordered = "&".join(
        f"{str(k)}={str(params[k])}" for k in sorted(params)
    )
    material = f"{ordered}&timestamp={timestamp}&nonce={nonce}"
    return hmac.new(app_secret.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).hexdigest()


class TikTokAuthAdapter:
    """AuthAdapter: structural credential + fixed-base check + offline signing."""

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
                data={"detail": "tiktok api base failed SSRF allowlist validation"},
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural-only test: exercises request signing OFFLINE.

        The signature uses a FIXED reference timestamp/nonce and is a structural
        demonstration — it is never presented as a live-verifiable signature. A
        live signed call is a certification-level follow-on (not claimed).
        """
        result = await self.validate_credentials(context)
        if not result.success:
            return result
        cred = _credential_dict(context)
        try:
            signature = sign_request(
                app_secret=cred["app_secret"],
                params={"shop_id": cred["shop_id"], "path": "/order/search"},
                timestamp=_STRUCTURAL_REFERENCE_TIMESTAMP,
                nonce=_STRUCTURAL_REFERENCE_NONCE,
            )
        except Exception as exc:  # noqa: BLE001 - a signing failure is a visible error
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="signing_failed",
                retryable=False,
                data={"detail": f"tiktok request signing failed offline: {type(exc).__name__}"},
            )
        return AdapterResult.ok(
            {
                "detail": "tiktok credential structure valid; request signing path "
                "exercised offline with a fixed timestamp (no live call). Live "
                "signed-request verification is a certification-level follow-on "
                "(not claimed this build)",
                "base_url": _base_url(context),
                "signature_exercised": len(signature) == 64,
                "status": "structural_ok",
            }
        )


__all__ = [
    "API_BASE_PATH",
    "API_HOST",
    "API_HOST_ALLOWLIST",
    "TikTokAuthAdapter",
    "REQUIRED_CREDENTIAL_FIELDS",
    "sign_request",
    "_base_url",
    "_credential_dict",
    "_safe_json",
]
