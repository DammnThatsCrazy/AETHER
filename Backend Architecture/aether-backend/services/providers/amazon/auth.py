"""Amazon Selling Partner API credential validation (:class:`AuthAdapter`).

The credential is ``{'client_id': str, 'client_secret': str, 'refresh_token':
str, 'seller_id': str}`` — the LWA (Login with Amazon) material plus the seller
marketplace identifier. Authentication is LWA ``client_credentials`` yielding
an access token, and requests are signed with AWS SigV4. The API host is FIXED
to the regional SP-API allowlist
``sellingpartnerapi-{na,eu,fe}.amazon.com`` and routed through
:func:`validated_https_host <shared.security.ssrf.validated_https_host>` — a
tenant value never selects the host (the ``region`` config only picks between
allowlisted entries).

This build is STRUCTURAL ONLY in CI: ``validate_credentials`` and ``test`` make
no network calls — the live LWA exchange and the SigV4 request-signing
round-trip are certification-level follow-ons and are NOT claimed as build
facts. No secret material is ever included in an error message or result
``detail``.
"""

from __future__ import annotations

from typing import Any

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import AdapterResult, AdapterStatus
from shared.security.ssrf import validated_https_host

REQUIRED_CREDENTIAL_FIELDS = ("client_id", "client_secret", "refresh_token", "seller_id")
# Fixed regional SP-API hosts — never tenant-selected. Region picks between
# these allowlisted entries only.
API_HOST_ALLOWLIST: tuple[str, ...] = (
    "sellingpartnerapi-na.amazon.com",
    "sellingpartnerapi-eu.amazon.com",
    "sellingpartnerapi-fe.amazon.com",
)
# The default region (config `region` overrides). A tenant value can never
# reach beyond this allowlist — `validated_https_host` rejects anything else.
DEFAULT_REGION = "na"
_REGION_TO_HOST: dict[str, str] = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}


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
    # A MultiCredential nests named sub-credentials under ``credentials``;
    # flatten them so the four-field Amazon material (client_id/client_secret/
    # refresh_token/seller_id) is read wherever the runtime stored it. Fields
    # on the outer shape win — never the other way round.
    sources: list[dict[str, Any]] = [plain]
    nested = plain.get("credentials")
    if isinstance(nested, dict):
        for sub in nested.values():
            if isinstance(sub, dict):
                sources.append(sub)
    out: dict[str, Any] = {}
    for key in ("client_id", "client_secret", "refresh_token", "seller_id", "access_token"):
        for source in sources:
            value = source.get(key)
            if value is not None:
                out[key] = value
                break
    # ``seller_id`` is non-secret (manifest ``secret=False``) — the runtime
    # stores non-secret identifiers in ``connection.config`` (like ``region``),
    # so fall back to config when the credential shape has no home for it.
    if "seller_id" not in out:
        config_seller = context.config.get("seller_id")
        if config_seller is not None:
            out["seller_id"] = str(config_seller)
    if "access_token" not in out:
        for source in sources:
            if source.get("token") is not None:
                out["access_token"] = source["token"]
                break
    return out


def _region(context: AcquisitionContext) -> str:
    """Resolve the region config; anything outside the known set falls back."""
    region = str(context.config.get("region") or DEFAULT_REGION).strip().lower()
    return region if region in _REGION_TO_HOST else DEFAULT_REGION


def _base_url(context: AcquisitionContext) -> str:
    """The SSRF-validated SP-API base for the resolved region.

    The host is chosen from the fixed regional allowlist and validated through
    ``validated_https_host`` before it is ever used to build a URL — a tenant
    value never reaches the outbound host.
    """
    host = validated_https_host(
        _REGION_TO_HOST[_region(context)], allow_suffixes=API_HOST_ALLOWLIST
    )
    if not host:
        return ""
    return f"https://{host}"


def _missing_fields(context: AcquisitionContext) -> list[str]:
    cred = _credential_dict(context)
    return [
        name for name in REQUIRED_CREDENTIAL_FIELDS
        if not str(cred.get(name) or "").strip()
    ]


class AmazonAuthAdapter:
    """AuthAdapter: structural credential + regional-base check (no live LWA)."""

    async def validate_credentials(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural check: required keys present + regional base resolves."""
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
                data={"detail": "amazon SP-API base failed SSRF allowlist validation"},
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural-only test: no live LWA/SigV4 exchange is claimed this build."""
        result = await self.validate_credentials(context)
        if not result.success:
            return result
        return AdapterResult.ok(
            {
                "detail": "amazon credential structure valid; live LWA exchange and "
                "AWS SigV4 signing are a certification-level follow-on "
                "(not claimed this build)",
                "base_url": _base_url(context),
                "status": "structural_ok",
            }
        )


__all__ = [
    "API_HOST_ALLOWLIST",
    "AmazonAuthAdapter",
    "DEFAULT_REGION",
    "REQUIRED_CREDENTIAL_FIELDS",
    "_base_url",
    "_credential_dict",
    "_region",
]
