"""Shopify credential validation and live connectivity test (:class:`AuthAdapter`).

The REST pull-only credential is ``api_key`` + ``password`` + ``shop_domain``.
REST webhook mode also requires ``webhook_secret``. The opt-in GraphQL orders
mode uses ``shop_access_token`` and ``shop_domain`` and remains poll-only.
No secret material is ever included in an error message or result ``detail``.

The credential is read defensively because ``AcquisitionContext.credential`` may
be a plain dict (broker-revealed / test contexts) or a ``StructuredCredential``
(Team D's broker reveals it via ``shared.credentials.types.to_plaintext_dict``)
or ``None`` (credential-less certification contexts).
"""

from __future__ import annotations

import ipaddress
import re
import urllib.parse
from typing import Any, Optional

from shared.credentials.types import to_plaintext_dict
from shared.integration_contracts.acquisition import AcquisitionContext
from shared.integration_contracts.results import (
    AdapterResult,
    AdapterStatus,
    RateLimitInfo,
)

DEFAULT_API_VERSION = "2024-10"
REQUIRED_CREDENTIAL_FIELDS = ("api_key", "password", "shop_domain")
ORDERS_API_MODES = frozenset({"rest", "rest_webhook", "graphql"})
_REQUEST_TIMEOUT_SECONDS = 10.0

# SSRF gate: real Shopify admin API hosts are always ``{shop}.myshopify.com``.
# A tenant-supplied shop_domain that does not match this allowlist is rejected —
# the runtime must never issue an authenticated server-side request to an
# attacker-chosen host (loopback, link-local, private ranges, cloud metadata).
_SHOPIFY_HOST_RE = re.compile(r"(?i)^[a-z0-9][a-z0-9\-]{1,62}\.myshopify\.com$")
# Defense-in-depth for the api_version config: only word-ish path segments.
_API_VERSION_RE = re.compile(r"^[\w.\-]+$")


def _credential_dict(context: AcquisitionContext) -> dict[str, Any]:
    """Read the credential defensively as a plain dict.

    Handles ``None`` (no credential), a plain dict (broker-revealed / test
    contexts), and a ``StructuredCredential`` (revealed through the auditable
    ``to_plaintext_dict`` seam). ``webhook_secret`` is surfaced as its OWN field
    — it is a distinct credential (the ``X-Shopify-Hmac-SHA256`` HMAC secret),
    NEVER a stand-in for the Basic-auth API ``password``. Field-name aliases on
    the structured shapes (``token``/``username``) are mapped onto the Shopify
    field names so a compatible structured shape still works.
    """
    credential = context.credential
    if credential is None:
        return {}
    if isinstance(credential, dict):
        plain = dict(credential)
    else:
        try:
            plain = to_plaintext_dict(credential)  # type: ignore[arg-type]
        except Exception:  # pragma: no cover - defensive: unknown credential object
            plain = getattr(credential, "model_dump", lambda: {})()
    if plain.get("type") == "multi":
        components = plain.get("credentials")
        if not isinstance(components, dict):
            return {}
        # The structured platform has no provider-specific secret bag. A
        # MultiCredential stores each Shopify secret as a named ApiKeyCredential;
        # unwrap only the exact components this adapter understands.
        return {
            name: component["api_key"]
            for name in ("api_key", "password", "shop_access_token", "webhook_secret")
            if isinstance((component := components.get(name)), dict)
            and component.get("type") == "api_key"
            and isinstance(component.get("api_key"), str)
            and component["api_key"]
        }
    out: dict[str, Any] = {}
    for key in (
        "api_key",
        "password",
        "shop_domain",
        "shop_access_token",
        "webhook_secret",
    ):
        value = plain.get(key)
        if value is not None:
            out[key] = value
    # Tolerate alternate field names on structured credential shapes. Note:
    # ``webhook_secret`` is intentionally NOT mapped onto ``password`` — the
    # webhook HMAC secret must never be used as the Basic-auth API credential.
    if "api_key" not in out and plain.get("token") is not None:
        out["api_key"] = plain["token"]
    if "shop_domain" not in out and plain.get("username") is not None:
        out["shop_domain"] = plain["username"]
    return out


def _source_account_realm(context: AcquisitionContext) -> Optional[str]:
    """Require an explicit identity namespace for GraphQL source objects.

    Shopify's Admin API does not label a shop's data as live or test. This
    tenant choice must be explicit so a development shop is never silently
    mapped into the live canonical-object namespace.
    """
    value = context.config.get("source_account_realm")
    return value if value in ("live", "test") else None


def _orders_api_mode(context: AcquisitionContext) -> str:
    """Return the configured Shopify order acquisition mode."""
    return str(context.config.get("orders_api") or "rest").lower()


def _validated_shop_domain(shop_domain: str) -> Optional[str]:
    """Validate a tenant-supplied shop domain; return the normalized host or None.

    The SSRF gate. Rejects anything that is not a bare ``{shop}.myshopify.com``
    hostname:

    * empty / whitespace;
    * a scheme, userinfo, explicit port, path, query, fragment, or trailing dot
      (must be a bare hostname — ``urlsplit("//" + host)`` must round-trip);
    * bare IPs and IP literals (IPv4 + IPv6), including loopback, link-local,
      and private ranges whenever the value parses as an IP;
    * anything outside the ``(?i)^[a-z0-9][a-z0-9-]{1,62}\\.myshopify\\.com$``
      allowlist (real Shopify admin API hosts are always ``{shop}.myshopify.com``).

    Returns the normalized lowercase hostname, or ``None`` when invalid.
    """
    if not shop_domain or not shop_domain.strip():
        return None
    host = shop_domain.strip().lower()

    # Bare-hostname structural gate: scheme/userinfo/port/path/trailing-dot.
    try:
        parts = urllib.parse.urlsplit("//" + host)
    except ValueError:
        return None
    if parts.hostname is None or parts.hostname != host:
        return None
    if parts.port is not None or parts.username is not None or parts.password is not None:
        return None
    if parts.path or parts.query or parts.fragment:
        return None

    # IP literal gate — never reach an IP server-side.
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    # Backstop for literals the first pass rejects on the first try (trailing
    # dot / brackets): any value that normalizes to an IP is still blocked.
    try:
        ipaddress.ip_address(host.rstrip(".").strip("[]"))
        return None
    except ValueError:
        pass

    # Shopify allowlist: only {shop}.myshopify.com admin hosts.
    if not _SHOPIFY_HOST_RE.fullmatch(host):
        return None
    return host


def _raw_shop_domain(context: AcquisitionContext) -> str:
    """Raw, UNVALIDATED tenant-supplied shop domain (credential or config)."""
    cred = _credential_dict(context)
    return str(cred.get("shop_domain") or context.config.get("shop_domain") or "").strip()


def _shop_domain(context: AcquisitionContext) -> str:
    """Resolved AND validated shop domain (the single SSRF choke point).

    Returns the normalized lowercase host, or ``""`` when absent/invalid — so
    every consumer (auth.test, pull.fetch, account.discover_accounts) gets the
    allowlisted host for free and never constructs a URL from a raw tenant value.
    """
    return _validated_shop_domain(_raw_shop_domain(context)) or ""


def _api_version(context: AcquisitionContext) -> str:
    """Resolve api_version, rejecting path-shape injection (defense-in-depth)."""
    version = str(context.config.get("api_version") or DEFAULT_API_VERSION)
    if not _API_VERSION_RE.fullmatch(version):
        return DEFAULT_API_VERSION
    return version


def _missing_fields(context: AcquisitionContext) -> list[str]:
    cred = _credential_dict(context)
    orders_api = _orders_api_mode(context)
    if orders_api == "graphql":
        return [
            name
            for name in ("shop_access_token", "shop_domain")
            if not str(
                (cred.get(name) if name != "shop_domain" else _raw_shop_domain(context)) or ""
            ).strip()
        ]
    required_fields = REQUIRED_CREDENTIAL_FIELDS + (
        ("webhook_secret",) if orders_api == "rest_webhook" else ()
    )
    return [
        name
        for name in required_fields
        if not str(
            (cred.get(name) if name != "shop_domain" else _raw_shop_domain(context)) or ""
        ).strip()
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


class ShopifyAuthAdapter:
    """AuthAdapter: structural credential check + live shop-identity probe.

    REST uses the legacy ``/shop.json`` Basic-auth probe. GraphQL mode uses a
    version-pinned Admin API query and its ``X-Shopify-Access-Token`` credential.
    """

    async def validate_credentials(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Structural check: required keys present + shop_domain conforms.

        A non-conforming shop_domain is a PERMANENT_ERROR (``shop_domain_invalid``)
        checked WITHOUT a network call — a bad host must never be probed.
        """
        orders_api = _orders_api_mode(context)
        if orders_api not in ORDERS_API_MODES:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="orders_api_invalid",
                retryable=False,
                data={"detail": "orders_api must be rest, rest_webhook, or graphql"},
            )
        if orders_api == "graphql" and not _source_account_realm(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="source_account_realm_invalid",
                retryable=False,
                data={"detail": "GraphQL source_account_realm must be explicitly live or test"},
            )
        missing = _missing_fields(context)
        if missing:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="credential_missing_fields",
                retryable=False,
                data={"detail": f"missing credential fields: {', '.join(missing)}"},
            )
        if not _shop_domain(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_invalid",
                retryable=False,
                data={"detail": "shop_domain is not a valid *.myshopify.com host"},
            )
        return AdapterResult.ok({})

    async def test(self, context: AcquisitionContext) -> AdapterResult[Any]:
        """Probe the shop over the configured REST or GraphQL Admin API.

        Returns ``AdapterResult`` following ``from_connection_test`` semantics:
        success + latency_ms; failures are classified (401 -> UNAUTHORIZED,
        429 -> RATE_LIMITED, 5xx/network -> RETRYABLE_ERROR, else PERMANENT_ERROR)
        with safe detail only (no secrets).
        """
        import time

        orders_api = _orders_api_mode(context)
        if orders_api not in ORDERS_API_MODES:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="orders_api_invalid",
                retryable=False,
                data={"detail": "orders_api must be rest, rest_webhook, or graphql"},
            )
        if orders_api == "graphql" and not _source_account_realm(context):
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="source_account_realm_invalid",
                retryable=False,
                data={"detail": "GraphQL source_account_realm must be explicitly live or test"},
            )
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
        # The validated host (allowlisted *.myshopify.com) — never a raw tenant value.
        shop_domain = _shop_domain(context)
        if not shop_domain:
            return AdapterResult(
                success=False,
                status=AdapterStatus.PERMANENT_ERROR,
                error_code="shop_domain_invalid",
                retryable=False,
                data={"detail": "shop_domain is not a valid *.myshopify.com host"},
            )
        if orders_api == "graphql":
            from services.providers.shopify.graphql_pull import (
                GRAPHQL_API_VERSION,
                _GraphQLFailure,
                _SHOP_GID_RE,
                _post,
            )

            start = time.perf_counter()
            url = f"https://{shop_domain}/admin/api/{GRAPHQL_API_VERSION}/graphql.json"
            try:
                async with _http_client() as client:
                    body = await _post(
                        client,
                        url,
                        str(cred["shop_access_token"]),
                        "query AetherShopProbe { shop { id } currentAppInstallation { accessScopes { handle } } }",
                        {},
                    )
                shop = body["data"].get("shop")
                if (
                    not isinstance(shop, dict)
                    or not isinstance(shop.get("id"), str)
                    or not _SHOP_GID_RE.fullmatch(shop["id"])
                ):
                    raise _GraphQLFailure(AdapterStatus.RETRYABLE_ERROR, "shop_identity_missing")
                installation = body["data"].get("currentAppInstallation")
                scopes = (
                    installation.get("accessScopes") if isinstance(installation, dict) else None
                )
                if not isinstance(scopes, list) or any(
                    not isinstance(scope, dict) or not isinstance(scope.get("handle"), str)
                    for scope in scopes
                ):
                    raise _GraphQLFailure(
                        AdapterStatus.RETRYABLE_ERROR, "order_scope_evidence_missing"
                    )
                scope_handles = {scope["handle"] for scope in scopes}
                if "read_orders" not in scope_handles:
                    raise _GraphQLFailure(AdapterStatus.PERMANENT_ERROR, "read_orders_required")
            except _GraphQLFailure as exc:
                return AdapterResult(
                    success=False,
                    status=exc.status,
                    error_code=exc.code,
                    retryable=exc.status
                    in (AdapterStatus.RETRYABLE_ERROR, AdapterStatus.RATE_LIMITED),
                    latency_ms=(time.perf_counter() - start) * 1000.0,
                    rate_limit=RateLimitInfo(retry_after_ms=exc.retry_after_ms)
                    if exc.retry_after_ms is not None
                    else None,
                    data={"detail": exc.code.replace("_", " ")},
                )
            return AdapterResult.ok(
                {
                    "detail": "shop reachable via GraphQL",
                    "status": "ok",
                    "read_orders": True,
                    "historical_backfill_available": "read_all_orders" in scope_handles,
                },
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )
        api_version = _api_version(context)
        url = f"https://{shop_domain}/admin/api/{api_version}/shop.json"

        import httpx

        start = time.perf_counter()
        try:
            async with _http_client() as client:
                response = await client.get(
                    url,
                    headers={"Accept": "application/json"},
                    auth=httpx.BasicAuth(cred["api_key"], cred["password"]),
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
            shop = _safe_json(response).get("shop") or {}
            return AdapterResult.ok(
                {"detail": f"shop reachable: {shop.get('name', shop_domain)}", "status": "ok"},
                latency_ms=latency_ms,
            )
        if response.status_code in (401, 403):
            return AdapterResult(
                success=False,
                status=AdapterStatus.UNAUTHORIZED,
                error_code="unauthorized",
                retryable=False,
                latency_ms=latency_ms,
                data={
                    "detail": f"shop {shop_domain} rejected the credential (HTTP {response.status_code})"
                },
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
                data={"detail": f"shop {shop_domain} rate-limited (HTTP 429)"},
            )
        if 500 <= response.status_code < 600:
            return AdapterResult(
                success=False,
                status=AdapterStatus.RETRYABLE_ERROR,
                error_code=f"http_{response.status_code}",
                retryable=True,
                latency_ms=latency_ms,
                data={"detail": f"shop {shop_domain} returned HTTP {response.status_code}"},
            )
        return AdapterResult(
            success=False,
            status=AdapterStatus.PERMANENT_ERROR,
            error_code=f"http_{response.status_code}",
            retryable=False,
            latency_ms=latency_ms,
            data={"detail": f"shop {shop_domain} returned HTTP {response.status_code}"},
        )


__all__ = [
    "DEFAULT_API_VERSION",
    "REQUIRED_CREDENTIAL_FIELDS",
    "ShopifyAuthAdapter",
    "_credential_dict",
    "_raw_shop_domain",
    "_shop_domain",
    "_validated_shop_domain",
]
