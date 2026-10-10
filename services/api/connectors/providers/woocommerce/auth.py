"""WooCommerce credential validation and live connectivity test (:class:`AuthAdapter`).

The credential is ``{'consumer_key': str, 'consumer_secret': str}`` presented
as HTTP Basic auth against the site's WooCommerce REST root. The tenant-supplied
``site_url`` is carried in ``context.config`` (non-secret) and is the SSRF
choke point: it is passed through :func:`validated_https_host
<shared.security.ssrf.validated_https_host>` with an EMPTY allowlist (the
program's WooCommerce exception), which returns the normalized public FQDN or
``None``. Every outbound request in this plugin is built from the RESOLVED host
with the API path pinned to ``/wp-json/wc/v3`` — a raw tenant value never
reaches ``httpx``.

.. warning::

   The structural gate is INERT against DNS-rebinding names
   (``169.254.169.254.nip.io``) and resolver-IP spellings. A resolver-level
   check (resolve -> validate address -> no-rebinding) is REQUIRED at live-auth
   time. This build implements only the structural gate and does NOT claim the
   resolver-level defense.

No secret material is ever included in an error message or result ``detail``.
The credential is read defensively because ``AcquisitionContext.credential`` may
be a plain dict, a ``StructuredCredential`` (revealed via
``shared.credentials.types.to_plaintext_dict``), or ``None``.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
)
from shared.security.ssrf import validated_https_host

REQUIRED_CREDENTIAL_FIELDS = ("consumer_key", "consumer_secret")
# The WooCommerce REST API path is pinned in code — never tenant input.
WOOCOMMERCE_API_PATH = "/wp-json/wc/v3"
_REQUEST_TIMEOUT_SECONDS = 10.0


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
    for key in ("consumer_key", "consumer_secret", "webhook_secret"):
        value = plain.get(key)
        if value is not None:
            out[key] = value
    return out


def _raw_site_url(context: AcquisitionContext) -> str:
    """Raw, UNVALIDATED tenant-supplied store origin (config or credential)."""
    from_config = context.config.get("site_url")
    if from_config:
        return str(from_config).strip()
    cred = _credential_dict(context)
    return str(cred.get("site_url") or "").strip()


def _site_host(context: AcquisitionContext) -> str:
    """Resolved AND validated store host — the single SSRF choke point.

    ``validated_https_host`` with an empty allowlist returns the normalized
    public FQDN of ``site_url`` (https-forced) or ``None``; loopback, private,
    link-local, IP-literal, metadata, port, userinfo, path, and control-character
    tricks are all rejected fail-closed. Returns ``""`` when absent/invalid so
    every consumer builds URLs from the allowlisted host or bails out.
    """
    raw = _raw_site_url(context)
    if not raw:
        return ""
    return validated_https_host(raw, allow_suffixes=()) or ""


def _base_url(context: AcquisitionContext) -> str:
    """``https://<validated host>/wp-json/wc/v3`` — the path is pinned in code."""
    host = _site_host(context)
    if not host:
        return ""
    return f"https://{host}{WOOCOMMERCE_API_PATH}"


def _missing_fields(context: AcquisitionContext) -> list[str]:
    cred = _credential_dict(context)
    return [
        name for name in REQUIRED_CREDENTIAL_FIELDS
        if not str(cred.get(name) or "").strip()
    ]


def _http_client():
    """Lazy httpx client factory (backend pattern). Tests patch this seam."""
    import httpx

    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)


def _safe_json(response) -> dict[str, Any]:
    """Best-effort JSON body parse; never raises (adapter must return AdapterResult)."""
    if not getattr(response, "content", None):
        return {}
    try:
        parsed = response.json()
    except Exception:  # noqa: BLE001 - malformed body degrades to an empty dict
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _retry_after_ms(headers) -> Optional[float]:
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw) * 1000.0
    except (TypeError, ValueError):
        return None


class WooCommerceAuthAdapter:
    """AuthAdapter: structural credential + site_url check, then a live probe.

    ``validate_credentials`` is STRUCTURAL ONLY (no network): missing fields and
    a non-conforming ``site_url`` are permanent errors decided without a call. A
    bad host is never probed. ``test`` additionally performs a live ``GET`` of
    the pinned REST root with HTTP Basic auth.
    """

    async def validate_credentials(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural check: required keys present + site_url conforms."""
        missing = _missing_fields(context)
        if missing:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )
        host = _site_host(context)
        if not host:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_invalid",
                retryable=False,
                data={
                    "detail": "site_url is not a valid public https host "
                    "(structural gate; resolver-level check required at live-auth time)"
                },
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Live GET ``{base}`` (the pinned WooCommerce REST root) with Basic auth."""
        import time

        cred = _credential_dict(context)
        missing = _missing_fields(context)
        if missing:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )
        base = _base_url(context)
        if not base:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="site_url_invalid",
                retryable=False,
                data={
                    "detail": "site_url is not a valid public https host "
                    "(structural gate; resolver-level check required at live-auth time)"
                },
            )

        import httpx

        start = time.perf_counter()
        try:
            async with _http_client() as client:
                response = await client.get(
                    base,
                    headers={"Accept": "application/json"},
                    auth=httpx.BasicAuth(cred["consumer_key"], cred["consumer_secret"]),
                )
        except Exception as exc:  # noqa: BLE001 - network failures are classified
            latency_ms = (time.perf_counter() - start) * 1000.0
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code="connection_failed",
                retryable=True,
                latency_ms=latency_ms,
                data={"detail": f"connection failed: {type(exc).__name__}"},
            )
        latency_ms = (time.perf_counter() - start) * 1000.0

        if response.status_code == 200:
            namespace = _safe_json(response).get("namespace")
            return AdapterResult.ok(
                {"detail": f"site reachable: {base}", "namespace": namespace, "status": "ok"},
                latency_ms=latency_ms,
            )
        if response.status_code in (401, 403):
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                latency_ms=latency_ms,
                data={"detail": f"site rejected the consumer credential (HTTP {response.status_code})"},
            )
        if response.status_code == 429:
            retry_after = _retry_after_ms(response.headers)
            return AdapterResult(
                success=False,
                status=AdapterStatus.RATE_LIMITED,
                error_code="rate_limited",
                retryable=True,
                latency_ms=latency_ms,
                rate_limit=RateLimitInfo(retry_after_ms=retry_after),
                data={"detail": f"site rate-limited (HTTP 429)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                latency_ms=latency_ms,
                data={"detail": f"site returned HTTP {response.status_code}"},
            )
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code=f"http_{response.status_code}",
            retryable=False,
            latency_ms=latency_ms,
            data={"detail": f"site returned HTTP {response.status_code}"},
        )


__all__ = [
    "REQUIRED_CREDENTIAL_FIELDS",
    "WOOCOMMERCE_API_PATH",
    "WooCommerceAuthAdapter",
    "_base_url",
    "_credential_dict",
    "_raw_site_url",
    "_site_host",
]
