"""Bounded public xAI Marketplace catalog observation.

Only the public JSON-LD listing index is captured. Bot instructions,
descriptions, skills, memories, integrations, and other template configuration
are deliberately excluded from storage and graph projection.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlsplit

import httpx

from shared.logger.logger import get_logger, metrics
from shared.store import DurableStore, get_store

logger = get_logger("aether.agent_marketplace.catalog")

MARKETPLACE_URL = "https://x.ai/bot/marketplace"
SOURCE_NAMESPACE = "xai_marketplace"
CATALOG_STORE_NAME = "agent_marketplace_public_catalog"
CATALOG_STATUS_KEY = "source_status:xai_marketplace"
PLATFORM_TENANT_ID = "platform"
MAX_RESPONSE_BYTES = 3 * 1024 * 1024
MAX_LISTINGS = 250
MAX_LISTING_NAME = 160
DEFAULT_POLL_INTERVAL_SECONDS = 21_600
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _JsonLdScriptParser(HTMLParser):
    """Collect only JSON-LD script bodies from the bounded HTML response."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.documents: list[str] = []
        self._inside_jsonld = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "script":
            return
        values = {key.lower(): (value or "").lower() for key, value in attrs}
        if values.get("type", "").split(";")[0].strip() == "application/ld+json":
            self._inside_jsonld = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_jsonld:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._inside_jsonld:
            self.documents.append("".join(self._parts))
            self._inside_jsonld = False
            self._parts = []


class MarketplaceCatalogParseError(ValueError):
    """The public page no longer contains the expected bounded catalog shape."""


def _walk_jsonld(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_jsonld(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_jsonld(child)


def _safe_listing_url(value: Any) -> Optional[tuple[str, str]]:
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"x.ai", "www.x.ai"}
        or parsed.username
        or parsed.password
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
    ):
        return None
    parts = parsed.path.split("/")
    if len(parts) != 5 or parts[:4] != ["", "bot", "marketplace", "bots"]:
        return None
    slug = parts[4]
    if not _SLUG_RE.fullmatch(slug):
        return None
    return slug, f"https://{parsed.hostname}{parsed.path}"


def parse_public_marketplace_catalog(html: str) -> list[dict[str, Any]]:
    """Extract bounded listing labels and canonical public URLs from JSON-LD."""
    parser = _JsonLdScriptParser()
    parser.feed(html)
    records: dict[str, dict[str, Any]] = {}
    found_item_list = False

    for document in parser.documents:
        try:
            root = json.loads(document)
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk_jsonld(root):
            node_type = node.get("@type")
            if node_type == "ItemList" or (
                isinstance(node_type, list) and "ItemList" in node_type
            ):
                found_item_list = True
                items = node.get("itemListElement")
                if not isinstance(items, list):
                    raise MarketplaceCatalogParseError("public catalog ItemList has no item list")
                if len(items) > MAX_LISTINGS:
                    raise MarketplaceCatalogParseError("public catalog ItemList exceeds the safe listing limit")
                for element in items:
                    if not isinstance(element, dict):
                        raise MarketplaceCatalogParseError("public catalog contains an invalid list item")
                    item = element.get("item", element)
                    if not isinstance(item, dict):
                        raise MarketplaceCatalogParseError("public catalog contains an invalid listing record")
                    safe_url = _safe_listing_url(item.get("url") or item.get("@id"))
                    if safe_url is None:
                        raise MarketplaceCatalogParseError("public catalog listing URL is outside the supported source shape")
                    slug, source_url = safe_url
                    raw_name = item.get("name")
                    if not isinstance(raw_name, str):
                        raise MarketplaceCatalogParseError("public catalog listing is missing its name")
                    name = " ".join(raw_name.split())[:MAX_LISTING_NAME]
                    if not name or any(ord(char) < 32 or ord(char) == 127 for char in name):
                        raise MarketplaceCatalogParseError("public catalog listing name is invalid")
                    raw_position = element.get("position")
                    position = raw_position if isinstance(raw_position, int) and raw_position > 0 else None
                    content_hash = _digest({
                        "name": name,
                        "source_url": source_url,
                        "source_position": position,
                    })
                    records.setdefault(slug, {
                        "source_namespace": SOURCE_NAMESPACE,
                        "listing_ref": slug,
                        "name": name,
                        "source_url": source_url,
                        "source_position": position,
                        "content_hash": content_hash,
                        "assertion": "public_source_observed",
                    })

    if not found_item_list:
        raise MarketplaceCatalogParseError("public catalog ItemList was not found")
    return list(records.values())[:MAX_LISTINGS]


class MarketplaceCatalogRepository:
    """Durable source records and poll status, partitioned by provider namespace."""

    def __init__(self, store: DurableStore | None = None) -> None:
        self._store = store or get_store(CATALOG_STORE_NAME)

    @staticmethod
    def record_id(listing_ref: str) -> str:
        return f"listing:{_digest([SOURCE_NAMESPACE, listing_ref])}"

    @staticmethod
    def observation_record_id(listing_ref: str, content_hash: str,
                              listing_status: str, observed_at: str) -> str:
        return "observation:" + _digest([
            SOURCE_NAMESPACE, listing_ref, content_hash, listing_status, observed_at,
        ])

    async def status(self) -> dict[str, Any]:
        return await self._store.get(CATALOG_STATUS_KEY) or {
            "source_namespace": SOURCE_NAMESPACE,
            "source_status": "never_observed",
            "last_success_at": None,
            "listing_count": 0,
        }

    async def list_listings(self, limit: int = MAX_LISTINGS) -> list[dict[str, Any]]:
        rows = await self._store.find(
            record_type="listing", source_namespace=SOURCE_NAMESPACE,
        )
        rows = [row for row in rows if row.get("listing_status") == "listed"]
        rows.sort(key=lambda row: (
            row.get("source_position") is None,
            row.get("source_position") or 0,
            row.get("name") or "",
        ))
        return rows[:max(0, min(limit, MAX_LISTINGS))]

    async def list_projection_rows(self, limit: int = MAX_LISTINGS) -> list[dict[str, Any]]:
        """Return each listing's latest state, including current absences."""
        rows = await self._store.find(
            record_type="listing", source_namespace=SOURCE_NAMESPACE,
        )
        rows.sort(key=lambda row: row.get("listing_ref") or "")
        return rows[:max(0, min(limit, MAX_LISTINGS))]

    async def list_projection_observations(
        self, *, limit: int, cursor: Optional[str] = None,
    ) -> tuple[list[dict[str, Any]], Optional[str], bool]:
        """Read one bounded storage page of immutable listing transitions."""
        rows, next_cursor, truncated = await self._store.find_page(
            limit=max(1, limit),
            cursor=cursor,
            key_prefix="observation:",
            record_type="listing_observation", source_namespace=SOURCE_NAMESPACE,
        )
        return rows, next_cursor, truncated

    async def snapshot(self, listings: list[dict[str, Any]], *, observed_at: str,
                       etag: Optional[str], last_modified: Optional[str]) -> list[dict[str, Any]]:
        current_refs = {str(item["listing_ref"]) for item in listings}
        previous = await self._store.find(
            record_type="listing", source_namespace=SOURCE_NAMESPACE,
        )
        transitioned: list[dict[str, Any]] = []
        previous_by_ref = {str(row.get("listing_ref")): row for row in previous}

        for item in listings:
            listing_ref = str(item["listing_ref"])
            old = previous_by_ref.get(listing_ref) or {}
            row = {
                "id": self.record_id(listing_ref),
                "record_type": "listing",
                **item,
                "listing_status": "listed",
                "first_seen_at": old.get("first_seen_at") or observed_at,
                "last_seen_at": observed_at,
                "last_observed_catalog_at": observed_at,
                "observation_id": old.get("observation_id"),
            }
            if (
                old.get("content_hash") != row.get("content_hash")
                or old.get("listing_status") != "listed"
                or not old.get("observation_id")
            ):
                observation_id = self.observation_record_id(
                    listing_ref, str(row["content_hash"]), "listed", observed_at,
                )
                row["observation_id"] = observation_id
                await self._store.set(observation_id, {
                    **row,
                    "id": observation_id,
                    "record_type": "listing_observation",
                    "listing_status": "listed",
                    "observed_at": observed_at,
                })
                transitioned.append(row)
            await self._store.set(self.record_id(listing_ref), row)

        for old in previous:
            listing_ref = str(old.get("listing_ref") or "")
            if not listing_ref or listing_ref in current_refs:
                continue
            if old.get("listing_status") != "listed" and old.get("observation_id"):
                continue
            row = {
                **old,
                "listing_status": "not_currently_listed",
                "last_observed_catalog_at": observed_at,
            }
            observation_id = self.observation_record_id(
                listing_ref,
                str(row.get("content_hash") or ""),
                "not_currently_listed",
                observed_at,
            )
            row["listing_status"] = "not_currently_listed"
            row["observation_id"] = observation_id
            await self._store.set(observation_id, {
                **row,
                "id": observation_id,
                "record_type": "listing_observation",
                "observed_at": observed_at,
            })
            await self._store.set(self.record_id(listing_ref), row)
            transitioned.append(row)

        old_status = await self.status()
        await self._store.set(CATALOG_STATUS_KEY, {
            "source_namespace": SOURCE_NAMESPACE,
            "source_status": "available" if listings else "empty",
            "last_attempt_at": observed_at,
            "last_success_at": observed_at,
            "observed_at": observed_at,
            "listing_count": len(listings),
            "catalog_hash": _digest([
                [row["listing_ref"], row["content_hash"]]
                for row in sorted(listings, key=lambda row: row["listing_ref"])
            ]),
            "etag": etag or old_status.get("etag"),
            "last_modified": last_modified or old_status.get("last_modified"),
            "last_error_category": None,
            "graph_projection_status": old_status.get("graph_projection_status", "not_started"),
        })
        return transitioned

    async def mark_unavailable(self, *, attempted_at: str, error_category: str) -> None:
        old = await self.status()
        await self._store.set(CATALOG_STATUS_KEY, {
            **old,
            "source_namespace": SOURCE_NAMESPACE,
            "source_status": "unavailable",
            "last_attempt_at": attempted_at,
            "last_error_category": error_category,
        })

    async def mark_not_modified(self, *, checked_at: str) -> None:
        old = await self.status()
        await self._store.set(CATALOG_STATUS_KEY, {
            **old,
            "source_namespace": SOURCE_NAMESPACE,
            "source_status": "available" if old.get("last_success_at") else "never_observed",
            "last_attempt_at": checked_at,
            "last_error_category": None,
        })

    async def mark_graph_projection(self, *, status: str,
                                    error_category: Optional[str] = None) -> None:
        old = await self.status()
        await self._store.set(CATALOG_STATUS_KEY, {
            **old,
            "graph_projection_status": status,
            "graph_projection_error_category": error_category,
        })


class PublicMarketplaceCatalogObserver:
    """Fetch the fixed public index, persist minimal observations, queue graph writes."""

    def __init__(self, repository: MarketplaceCatalogRepository | None = None,
                 *, poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
                 fetcher: Optional[Callable[[dict[str, str]], Awaitable[tuple[int, bytes, dict[str, str]]]]] = None) -> None:
        self.repository = repository or MarketplaceCatalogRepository()
        self.poll_interval_seconds = max(900, min(int(poll_interval_seconds), 86_400))
        self._fetcher = fetcher
        self._poll_lock = asyncio.Lock()

    async def _fetch(self, headers: dict[str, str]) -> tuple[int, bytes, dict[str, str]]:
        if self._fetcher is not None:
            return await self._fetcher(headers)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0),
            follow_redirects=False,
            headers={"User-Agent": "AetherPublicCatalogObserver/1.0 (+https://aether.app)"},
        ) as client:
            async with client.stream("GET", MARKETPLACE_URL, headers=headers) as response:
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                if response.status_code == 304:
                    return 304, b"", response_headers
                if response.status_code != 200:
                    raise RuntimeError(f"http_status_{response.status_code}")
                parts: list[bytes] = []
                length = 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_RESPONSE_BYTES:
                        raise RuntimeError("response_too_large")
                    parts.append(chunk)
                return response.status_code, b"".join(parts), response_headers

    async def observe_once(self) -> dict[str, Any]:
        if self._poll_lock.locked():
            return {"status": "skipped", "reason": "poll_already_running"}
        async with self._poll_lock:
            attempted_at = _now_iso()
            old_status = await self.repository.status()
            request_headers: dict[str, str] = {}
            if old_status.get("etag"):
                request_headers["If-None-Match"] = str(old_status["etag"])
            if old_status.get("last_modified"):
                request_headers["If-Modified-Since"] = str(old_status["last_modified"])

            try:
                status_code, body, response_headers = await self._fetch(request_headers)
                if status_code == 304:
                    await self.repository.mark_not_modified(checked_at=attempted_at)
                    metrics.increment("agent_marketplace_catalog_not_modified_total")
                    return {"status": "not_modified", "observed_at": old_status.get("observed_at")}
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RuntimeError("response_too_large")
                listings = parse_public_marketplace_catalog(body.decode("utf-8", errors="replace"))
                transitioned = await self.repository.snapshot(
                    listings,
                    observed_at=attempted_at,
                    etag=response_headers.get("etag"),
                    last_modified=response_headers.get("last-modified"),
                )
            except Exception as exc:
                category = str(exc)[:80] or type(exc).__name__
                await self.repository.mark_unavailable(
                    attempted_at=attempted_at,
                    error_category=category,
                )
                logger.warning("public marketplace observation failed: %s", category)
                metrics.increment("agent_marketplace_catalog_unavailable_total")
                return {"status": "unavailable", "error_category": category}

            graph_rows = 0
            try:
                from config.settings import settings
                if settings.external_agent_telemetry.graph_enabled:
                    from actions.agent_marketplace.lineage import (
                        build_public_marketplace_listing_mutations,
                    )
                    from actions.agent_marketplace.projection import AgentMarketplaceGraphProjectionOutbox
                    outbox = AgentMarketplaceGraphProjectionOutbox()
                    projection_states: list[str] = []
                    for row in transitioned:
                        summary = await outbox.enqueue_mutations(
                            PLATFORM_TENANT_ID,
                            f"marketplace_catalog:{row['source_namespace']}:{row['observation_id']}",
                            build_public_marketplace_listing_mutations(row),
                        )
                        graph_rows += int(summary.get("queued", 0))
                        projection_states.append(
                            str(summary.get("graph_projection_status") or "unknown")
                        )
                    if graph_rows or "queued" in projection_states:
                        projection_status = "queued"
                    elif any(state in {"failed", "partial"} for state in projection_states):
                        projection_status = "failed"
                    elif projection_states and all(
                        state == "persisted" for state in projection_states
                    ):
                        projection_status = "persisted"
                    else:
                        projection_status = "current"
                else:
                    projection_status = "disabled"
                await self.repository.mark_graph_projection(status=projection_status)
            except Exception as exc:
                category = type(exc).__name__
                await self.repository.mark_graph_projection(
                    status="failed",
                    error_category=category,
                )
                logger.warning("public marketplace graph projection enqueue failed: %s", category)
                metrics.increment("agent_marketplace_catalog_projection_failed_total")

            metrics.increment("agent_marketplace_catalog_observed_total")
            return {
                "status": "available" if listings else "empty",
                "listing_count": len(listings),
                "changed_listing_count": len(transitioned),
                "graph_mutations_queued": graph_rows,
                "observed_at": attempted_at,
            }

    async def run(self) -> None:
        while True:
            await self.observe_once()
            await asyncio.sleep(self.poll_interval_seconds)


def build_public_marketplace_catalog_loop():
    """Worker entrypoint; configuration stays OFF unless explicitly enabled."""
    from config.settings import settings

    return PublicMarketplaceCatalogObserver(
        poll_interval_seconds=settings.external_agent_telemetry.catalog_poll_interval_seconds,
    ).run()
