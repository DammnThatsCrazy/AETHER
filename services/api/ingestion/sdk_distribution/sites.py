"""The site registry.

A *site* is one property the SDK is installed on — a marketing site, an app
shell, a docs domain, a native iOS or Android app — identified by the ``site_id`` that travels in the
snippet's ``data-site`` attribute and in every request's ``X-Aether-Site``
header.

Sites exist because a publishable key ships inside page HTML, where anyone can
read it out of View Source. Without a bound unit, that key would be a
tenant-wide credential that anyone could lift off one customer's page and
replay against every other property the tenant owns. The site is the unit that
makes the binding mean something, so it is a durable record rather than a
string in a config file.
"""

from __future__ import annotations

import re
import secrets
from typing import Optional
from urllib.parse import urlsplit

from repositories.repos import BaseRepository

SITE_ID_PREFIX = "site_"

# Lifecycle. A revoked site is kept, not deleted: installations and events
# already attributed to it are historical fact, and a registry that forgot the
# site would leave that history unattributable.
STATUS_ACTIVE = "active"
STATUS_REVOKED = "revoked"

_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


# Where a site's SDK runs. A web site is bound to the origins its snippet is
# served on; a native app has no origin (iOS and Android send none), so it is
# bound to its application identifier instead: the iOS bundle ID or the Android
# package name. React Native apps declare the identifiers of both builds.
PLATFORM_WEB = "web"
NATIVE_PLATFORMS = ("ios", "android", "react_native")
SITE_PLATFORMS = (PLATFORM_WEB, *NATIVE_PLATFORMS)

# Reverse-DNS application identifier: at least two dot-separated segments,
# each starting with a letter or digit. Covers iOS bundle IDs
# (``com.example.App``) and Android application IDs (``com.example.app``).
_APP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9][A-Za-z0-9_-]*)+$")
_APP_ID_MAX_LENGTH = 255


class SiteOriginError(ValueError):
    """An origin a snippet must never be installed on."""


class SiteAppIdError(ValueError):
    """An application identifier a native site cannot be bound to."""


def new_site_id() -> str:
    """A site id that is unguessable as well as unique.

    Random rather than sequential: site ids appear in page HTML and in request
    headers, so a sequential id would let anyone enumerate a tenant's other
    properties from a single page.
    """
    return f"{SITE_ID_PREFIX}{secrets.token_hex(8)}"


def normalize_origin(origin: str) -> str:
    """Return the canonical ``scheme://host[:port]`` for one declared origin.

    Mirrors the loader's endpoint rule (``src/loader/auto-init.ts``) and for the
    same reason: cleartext would put the publishable key on the wire in the
    clear for anyone on the path. Bare hosts are accepted and read as https,
    because that is what an operator pastes and guessing is only unsafe in the
    direction of *less* transport security.
    """
    raw = (origin or "").strip()
    if not raw:
        raise SiteOriginError("origin must not be empty")
    if "://" not in raw:
        raw = f"https://{raw}"

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise SiteOriginError(f"origin must be http or https, got {parts.scheme!r}")
    if not parts.hostname:
        raise SiteOriginError(f"origin has no host: {origin!r}")

    localhost = parts.hostname in _LOCALHOST_HOSTS
    if parts.scheme == "http" and not localhost:
        raise SiteOriginError(
            f"origin must use https (got {parts.scheme}://{parts.hostname}) — the "
            "snippet carries a publishable key, which must not travel in cleartext"
        )
    # A wildcard host would have to mean "any subdomain", and nothing downstream
    # implements that. Refusing it here keeps the registry from holding a claim
    # that is not enforced.
    if "*" in parts.hostname:
        raise SiteOriginError(
            f"origin must name a host, not a wildcard ({parts.hostname!r}); list "
            "each subdomain the snippet is installed on"
        )

    host = parts.hostname.lower()
    if not localhost and not _HOST_RE.match(host):
        raise SiteOriginError(f"origin host is not a valid hostname: {host!r}")

    port = ""
    if parts.port and not (
        (parts.scheme == "https" and parts.port == 443)
        or (parts.scheme == "http" and parts.port == 80)
    ):
        port = f":{parts.port}"
    return f"{parts.scheme}://{host}{port}"


def normalize_origins(origins: list[str]) -> list[str]:
    """Normalize a declared origin list, preserving order and dropping repeats."""
    seen: list[str] = []
    for origin in origins:
        normalized = normalize_origin(origin)
        if normalized not in seen:
            seen.append(normalized)
    return seen


def normalize_app_id(app_id: str) -> str:
    """Validate one iOS bundle ID or Android application ID.

    Case is kept: iOS bundle IDs are case-sensitive in practice (App Store
    Connect treats ``com.Example.App`` and ``com.example.app`` as different
    apps), so folding case would merge two distinct registrations.

    The identifier is a declaration, not proof. A native app sends no origin a
    browser vouches for, and anyone can put any bundle ID in a request, so this
    binding scopes a publishable key's blast radius to one site; it does not
    authenticate the app. Wildcards are refused for the same reason as on web
    origins: nothing downstream implements them.
    """
    raw = (app_id or "").strip()
    if not raw:
        raise SiteAppIdError("app id must not be empty")
    if "*" in raw:
        raise SiteAppIdError(
            f"app id must name one app, not a wildcard ({raw!r}); list each "
            "bundle ID or package name"
        )
    if len(raw) > _APP_ID_MAX_LENGTH or not _APP_ID_RE.match(raw):
        raise SiteAppIdError(
            f"app id must be a reverse-DNS bundle ID or package name such as "
            f"com.example.app, got {raw!r}"
        )
    return raw


def normalize_app_ids(app_ids: list[str]) -> list[str]:
    """Normalize a declared app-id list, preserving order and dropping repeats."""
    seen: list[str] = []
    for app_id in app_ids:
        normalized = normalize_app_id(app_id)
        if normalized not in seen:
            seen.append(normalized)
    return seen


class SDKSiteRepository(BaseRepository):
    """Durable site registry, one row per site, keyed by the public site id."""

    def __init__(self) -> None:
        super().__init__("sdk_sites")

    async def get(self, tenant_id: str, site_id: str) -> Optional[dict]:
        """A site, but only for the tenant that owns it.

        A site id from another tenant resolves to ``None`` — the caller gets a
        404, not a 403, so the response cannot be used to confirm that someone
        else's site exists.
        """
        record = await self.find_by_id(site_id)
        if record is None or record.get("tenant_id") != tenant_id:
            return None
        return record

    async def list_for_tenant(
        self, tenant_id: str, limit: int = 100, include_revoked: bool = False
    ) -> list[dict]:
        records = await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)
        if include_revoked:
            return records
        return [r for r in records if r.get("status") != STATUS_REVOKED]
