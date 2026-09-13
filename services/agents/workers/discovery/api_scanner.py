"""
Aether Agent Layer — API Scanner Discovery Worker
Discovers and probes public API endpoints for tracked entities.

Capabilities:
  - Detect REST / GraphQL / WebSocket endpoints from docs pages
  - Extract OpenAPI/Swagger schemas when available
  - Monitor for schema changes between scans
  - Catalogue rate-limit headers and authentication requirements
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from config.settings import WorkerType
from models.core import AgentTask, TaskResult

from workers.base import BaseWorker

logger = logging.getLogger("aether.worker.api_scanner")

# Common paths to probe for API docs
_WELL_KNOWN_PATHS = (
    "/.well-known/openapi.json",
    "/openapi.json",
    "/openapi.yaml",
    "/swagger.json",
    "/swagger/v1/swagger.json",
    "/api-docs",
    "/api-docs.json",
    "/graphql",
    "/.well-known/openapi",
    "/docs",
    "/redoc",
    "/api/v1",
    "/api/v2",
    "/api/v3",
    "/api/health",
    "/health",
    "/healthz",
    "/api/status",
    "/v1/api-docs",
)

# HTTP timeout for each probe (shorter since we're doing many)
_PROBE_TIMEOUT = 15

# User-agent for polite scanning
_USER_AGENT = "AetherBot/1.0 (+https://aether.dev/bot)"

# Rate-limit header names to look for
_RATE_LIMIT_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-rate-limit-limit",
    "x-rate-limit-remaining",
    "ratelimit-limit",
    "ratelimit-remaining",
    "retry-after",
)


class ApiScannerWorker(BaseWorker):
    """
    Discovery worker that scans a target domain for public API surface.

    Payload contract:
        target_domain : str   -- e.g. "api.example.com"
        entity_id     : str   -- graph entity this relates to
        probe_paths   : list  -- (optional) extra paths to check
        deep_scan     : bool  -- (optional) follow links in docs pages
    """

    worker_type = WorkerType.API_SCANNER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        domain = task.payload.get("target_domain", "")
        entity_id = task.payload.get("entity_id", "")
        extra_paths = task.payload.get("probe_paths", [])
        deep_scan = task.payload.get("deep_scan", False)

        if not domain:
            return TaskResult(
                task_id=task.task_id,
                worker_type=self.worker_type,
                success=False,
                error="No target_domain provided in payload",
                confidence=0.0,
            )

        paths_to_check = list(_WELL_KNOWN_PATHS) + list(extra_paths)
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique_paths: list[str] = []
        for p in paths_to_check:
            if p not in seen:
                seen.add(p)
                unique_paths.append(p)

        logger.info(
            f"Scanning API surface for {domain} "
            f"({len(unique_paths)} paths, deep={deep_scan})"
        )

        base_url = f"https://{domain}"
        endpoints: list[dict[str, Any]] = []
        total_probed = 0
        successful_probes = 0
        openapi_schema: dict[str, Any] | None = None

        client = httpx.Client(
            base_url=base_url,
            timeout=_PROBE_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        )

        try:
            for path in unique_paths:
                total_probed += 1
                endpoint_info = self._probe_endpoint(client, path)
                if endpoint_info is not None:
                    successful_probes += 1
                    endpoints.append(endpoint_info)

                    # If this is an OpenAPI/Swagger doc, try to parse it
                    if (
                        endpoint_info.get("is_openapi")
                        and openapi_schema is None
                    ):
                        openapi_schema = endpoint_info.get("schema_preview")

            # Deep scan: if we found a docs page, try to extract additional
            # API paths from its content
            if deep_scan:
                discovered_paths = self._deep_scan_docs(client, endpoints)
                for dp in discovered_paths:
                    if dp not in seen:
                        seen.add(dp)
                        total_probed += 1
                        endpoint_info = self._probe_endpoint(client, dp)
                        if endpoint_info is not None:
                            successful_probes += 1
                            endpoints.append(endpoint_info)
        except Exception as exc:
            logger.warning(f"Error during API scan of {domain}: {exc}")
        finally:
            client.close()

        # Determine if we found an OpenAPI spec
        has_openapi = any(e.get("is_openapi") for e in endpoints)

        schema_snapshot = {
            "domain": domain,
            "entity_id": entity_id,
            "endpoints_discovered": len(endpoints),
            "total_probed": total_probed,
            "endpoints": endpoints,
            "has_openapi": has_openapi,
            "openapi_schema_preview": openapi_schema,
        }

        # Confidence based on how many endpoints actually responded
        if total_probed == 0:
            confidence = 0.1
        else:
            response_ratio = successful_probes / total_probed
            # Base confidence from response ratio, boosted if we found OpenAPI
            confidence = response_ratio * 0.7
            if has_openapi:
                confidence += 0.25
            if successful_probes >= 3:
                confidence += 0.05
            confidence = max(0.0, min(1.0, round(confidence, 4)))

        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            data=schema_snapshot,
            confidence=confidence,
            source_attribution=f"https://{domain}",
        )

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _probe_endpoint(
        client: httpx.Client, path: str
    ) -> dict[str, Any] | None:
        """
        Probe a single endpoint path. Returns endpoint info dict if the
        server responds (any status), or None if the request fails entirely.
        """
        try:
            resp = client.get(path)
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            logger.debug(f"Probe failed for {path}: {exc}")
            return None

        status = resp.status_code
        content_type = resp.headers.get("content-type", "")

        # Detect auth requirements
        auth_required = status in (401, 403)

        # Detect if this is a real endpoint vs a generic 404 page
        # We consider anything that isn't a 404/405/502/503 as a valid endpoint
        if status in (404, 405, 502, 503):
            return None

        # Extract rate-limit headers
        rate_limit_info: dict[str, str] = {}
        for hdr in _RATE_LIMIT_HEADERS:
            val = resp.headers.get(hdr)
            if val:
                rate_limit_info[hdr] = val

        # Compute content hash for change detection
        content_hash = hashlib.sha256(resp.content).hexdigest()[:16]

        # Check if this is an OpenAPI/Swagger spec
        is_openapi = False
        schema_preview: dict[str, Any] | None = None
        if "json" in content_type and status == 200:
            try:
                body = resp.json()
                if isinstance(body, dict):
                    # OpenAPI 3.x
                    if "openapi" in body or "swagger" in body:
                        is_openapi = True
                        schema_preview = {
                            "version": body.get("openapi") or body.get("swagger"),
                            "title": body.get("info", {}).get("title", ""),
                            "paths_count": len(body.get("paths", {})),
                            "paths_sample": list(body.get("paths", {}).keys())[:10],
                        }
            except (json.JSONDecodeError, ValueError):
                pass

        # Detect GraphQL endpoint
        is_graphql = False
        if "graphql" in path.lower() and status == 200:
            is_graphql = True
        # GraphQL endpoints often return 400 on GET without a query
        if "graphql" in path.lower() and status == 400:
            is_graphql = True

        endpoint_data: dict[str, Any] = {
            "path": path,
            "status": status,
            "content_type": content_type.split(";")[0].strip() if content_type else "",
            "content_hash": content_hash,
            "auth_required": auth_required,
            "rate_limit_headers": rate_limit_info if rate_limit_info else None,
            "is_openapi": is_openapi,
            "is_graphql": is_graphql,
            "response_size_bytes": len(resp.content),
        }

        if schema_preview:
            endpoint_data["schema_preview"] = schema_preview

        return endpoint_data

    @staticmethod
    def _deep_scan_docs(
        client: httpx.Client,
        endpoints: list[dict[str, Any]],
    ) -> list[str]:
        """
        For discovered docs/API-docs endpoints, fetch the page and try to
        extract additional API paths from the content (links, code blocks, etc.).
        """
        import re

        additional_paths: list[str] = []
        docs_endpoints = [
            e for e in endpoints
            if e["path"] in ("/docs", "/redoc", "/api-docs", "/api-docs.json")
            and e["status"] == 200
        ]

        for ep in docs_endpoints:
            try:
                resp = client.get(ep["path"])
                if resp.status_code != 200:
                    continue

                text = resp.text
                # Look for API path patterns in the content
                # Match patterns like /api/v1/users, /v2/products, etc.
                path_pattern = re.compile(
                    r'["\'/]((?:api|v\d+)/[a-zA-Z0-9_/\-]+)["\'\s]'
                )
                for match in path_pattern.finditer(text):
                    candidate = "/" + match.group(1).strip("/")
                    if len(candidate) < 100:  # sanity check
                        additional_paths.append(candidate)
            except (httpx.TimeoutException, httpx.RequestError):
                continue

        # Deduplicate
        return list(dict.fromkeys(additional_paths))[:20]
