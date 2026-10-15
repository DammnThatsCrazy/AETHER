#!/usr/bin/env python3
"""Validate the opt-in inputs for the customer Access Kit MCP deployment."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
# ALB caps each path pattern at 128 characters. The metadata prefix is 37,
# leaving at most 91 characters for the configured MCP path, including '/'.
_PATH_RE = re.compile(r"^/[A-Za-z0-9/_-]{1,90}$")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_AUTHORITY_RE = re.compile(rf"^(?P<host>{_LABEL}(?:\.{_LABEL})*)(?::(?P<port>[0-9]+))?$")


def _boolean(value: str | bool, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be boolean")
    return value == "true"


def _valid_origin(origin: object) -> bool:
    if not isinstance(origin, str) or not origin.startswith("https://"):
        return False
    authority = origin[len("https://") :]
    match = _AUTHORITY_RE.fullmatch(authority)
    if not match:
        return False
    host = match.group("host")
    if len(host) > 253:
        return False
    if re.fullmatch(r"[0-9.]+", host):
        try:
            if ipaddress.ip_address(host).version != 4:
                return False
        except ValueError:
            return False
    port = match.group("port")
    if port is not None:
        if len(port) > 5:
            return False
        try:
            numeric_port = int(port)
        except ValueError:
            return False
        if numeric_port < 1 or numeric_port > 65535:
            return False
    return True


def validate_inputs(
    *,
    profile: str,
    enable_repository: str | bool,
    enable_service: str | bool,
    image_digest: str,
    desired_count: str,
    allowed_origins_json: str,
    access_mcp_path: str,
    enable_oauth: str | bool = False,
) -> None:
    """Raise ValueError unless deployment inputs fit the reviewed contract."""
    repository_enabled = _boolean(enable_repository, "enable_access_mcp_repository")
    service_enabled = _boolean(enable_service, "enable_access_mcp")
    oauth_enabled = _boolean(enable_oauth, "enable_access_mcp_oauth")

    if (repository_enabled or service_enabled) and profile != "production-scale":
        raise ValueError(
            "Access MCP repository and service are supported only by the canonical "
            "production-scale state owner"
        )
    if service_enabled and not repository_enabled:
        raise ValueError("enable_access_mcp requires enable_access_mcp_repository=true")
    if oauth_enabled and not service_enabled:
        raise ValueError("enable_access_mcp_oauth requires enable_access_mcp=true")
    if image_digest and not _DIGEST_RE.fullmatch(image_digest):
        raise ValueError("access_mcp_image_digest must be an immutable sha256 digest")
    if service_enabled and not image_digest:
        raise ValueError("enable_access_mcp requires an immutable access_mcp_image_digest")
    if not re.fullmatch(r"[1-4]", str(desired_count)):
        raise ValueError("access_mcp_desired_count must be an integer from 1 through 4")

    try:
        origins = json.loads(allowed_origins_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("access_mcp_allowed_origins must be a JSON array") from exc
    if not isinstance(origins, list) or not all(_valid_origin(origin) for origin in origins):
        raise ValueError(
            "access_mcp_allowed_origins must contain exact HTTPS origins with valid "
            "DNS or IPv4 hosts and optional ports from 1 through 65535"
        )

    if (
        not isinstance(access_mcp_path, str)
        or not _PATH_RE.fullmatch(access_mcp_path)
        or access_mcp_path.startswith("//")
        or access_mcp_path.endswith("/")
        or "//" in access_mcp_path
    ):
        raise ValueError("access_mcp_path must be a bounded absolute path without repeated or trailing slashes")
    if access_mcp_path.lower().startswith("/mcp"):
        raise ValueError("access_mcp_path must not overlap the reserved /mcp* tfmcp route")


def main() -> int:
    try:
        validate_inputs(
            profile=os.environ.get("PROFILE", ""),
            enable_repository=os.environ.get("ENABLE_ACCESS_MCP_REPOSITORY", ""),
            enable_service=os.environ.get("ENABLE_ACCESS_MCP", ""),
            image_digest=os.environ.get("ACCESS_MCP_IMAGE_DIGEST", ""),
            desired_count=os.environ.get("ACCESS_MCP_DESIRED_COUNT", ""),
            allowed_origins_json=os.environ.get("ACCESS_MCP_ALLOWED_ORIGINS", ""),
            access_mcp_path=os.environ.get("ACCESS_MCP_PATH", ""),
            enable_oauth=os.environ.get("ENABLE_ACCESS_MCP_OAUTH", "false"),
        )
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print("Access MCP deployment inputs are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
