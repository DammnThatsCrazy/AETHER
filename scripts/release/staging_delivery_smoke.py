#!/usr/bin/env python3
"""Run the delivery golden-path smoke on staging with a run-scoped tenant key.

Pilot staging never provisions the fixed ``SMOKE_API_KEY``; its durable
credential is ``STAGING_ADMIN_API_KEY`` (verified or bootstrapped by the
staging lifecycle). This helper follows the rehearsal's pattern: the admin key
creates one run-scoped enterprise tenant and a tenant API key, the existing
``scripts/smoke_test.py`` runs with that key (the admin key is used only for
the diagnostic endpoints), and the tenant is always deleted, or deactivated
when deletion cannot prove cleanup. A cleanup failure fails the run even when
the smoke passed. Keys are masked and never written to output or artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bootstrap_staging_admin_key import (  # noqa: E402  (script directory import)
    STAGING_ADMIN_KEY_RE,
    _base_url_errors,
    _request,
)

ROOT = Path(__file__).resolve().parents[2]
TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TENANT_PERMISSIONS = [
    "read",
    "write",
    "ingest",
    "analytics",
    "analytics:export",
    "consent:manage",
    "billing",
]

Call = Callable[[str, str, "dict[str, Any] | None"], "tuple[int, dict[str, Any]]"]


def _api(base_url: str, admin_key: str) -> Call:
    def call(
        method: str, path: str, body: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        headers = {"Accept": "application/json", "X-API-Key": admin_key}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, raw = _request(method, base_url + path, headers=headers, body=data)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        return status, payload if isinstance(payload, dict) else {}

    return call


def _extract(node: Any, *names: str) -> Any:
    if not isinstance(node, dict):
        return None
    for name in names:
        if node.get(name):
            return node[name]
    for nested in ("data", "tenant"):
        value = _extract(node.get(nested), *names)
        if value:
            return value
    return None


def create_run_scoped_tenant(call: Call, run_label: str) -> tuple[str, str]:
    status, payload = call(
        "POST",
        "/v1/admin/tenants",
        {
            "name": f"Aether staging delivery smoke {run_label}",
            "plan": "enterprise",
            "contact_email": f"aether-staging-smoke-{uuid.uuid4().hex}@staging.invalid",
            "settings": {"lifecycle": "run-scoped-delivery-smoke"},
        },
    )
    tenant_id = _extract(payload, "tenant_id", "id")
    if (
        status not in (200, 201)
        or not isinstance(tenant_id, str)
        or not TENANT_ID_RE.fullmatch(tenant_id)
    ):
        raise RuntimeError(f"run-scoped tenant creation failed (HTTP {status})")
    status, payload = call(
        "POST",
        f"/v1/admin/tenants/{tenant_id}/api-keys",
        {
            "name": f"staging-delivery-smoke-{run_label}",
            "tier": "enterprise",
            "permissions": TENANT_PERMISSIONS,
        },
    )
    key = _extract(payload, "api_key")
    if (
        status not in (200, 201)
        or not isinstance(key, str)
        or not STAGING_ADMIN_KEY_RE.fullmatch(key)
    ):
        # The tenant exists; the caller still removes it.
        raise _KeyCreationError(tenant_id, f"run-scoped API key creation failed (HTTP {status})")
    return tenant_id, key


class _KeyCreationError(RuntimeError):
    def __init__(self, tenant_id: str, message: str) -> None:
        super().__init__(message)
        self.tenant_id = tenant_id


def remove_tenant(call: Call, tenant_id: str) -> str | None:
    """Delete the tenant, falling back to deactivation. Returns an error or None."""
    status, payload = call("DELETE", f"/v1/admin/tenants/{tenant_id}", None)
    deleted = (
        ((payload.get("data") or {}).get("deleted") or {})
        if isinstance(payload.get("data"), dict)
        else {}
    )
    if status == 200 and isinstance(deleted, dict) and deleted.get("cleanup_complete") is True:
        return None
    if status in (200, 204):
        return f"delete returned {status} without a verified cleanup_complete receipt"
    delete_status = status
    status, payload = call("POST", f"/v1/admin/tenants/{tenant_id}/deactivate", None)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if status != 200 or data.get("status") != "inactive":
        return f"delete returned {delete_status}, deactivation returned {status}"
    if "api_keys_revoked" not in data or "keys_evicted" not in data:
        return "deactivation returned no credential-invalidation receipt"
    return None


def run(
    *,
    base_url: str,
    admin_key: str,
    run_label: str,
    timeout: int,
    call: Call | None = None,
    smoke: Callable[[list[str]], int] | None = None,
) -> int:
    errors = _base_url_errors(base_url)
    if errors:
        print(f"::error::{errors[0]}", file=sys.stderr)
        return 2
    if not STAGING_ADMIN_KEY_RE.fullmatch(admin_key or ""):
        print(
            "::error::STAGING_ADMIN_API_KEY must be the durable ak_ staging admin key",
            file=sys.stderr,
        )
        return 2
    call = call or _api(base_url.rstrip("/"), admin_key)
    smoke = smoke or (lambda argv: subprocess.run(argv, check=False).returncode)

    tenant_id: str | None = None
    smoke_status = 1
    try:
        tenant_id, tenant_key = create_run_scoped_tenant(call, run_label)
        print(f"::add-mask::{tenant_key}")
        print(f"run-scoped smoke tenant {tenant_id}")
        smoke_status = smoke(
            [
                sys.executable,
                str(ROOT / "scripts" / "smoke_test.py"),
                "--base-url",
                base_url,
                "--api-key",
                tenant_key,
                "--admin-api-key",
                admin_key,
                "--timeout",
                str(timeout),
            ]
        )
    except _KeyCreationError as error:
        tenant_id = error.tenant_id
        print(f"::error::{error}", file=sys.stderr)
    except (RuntimeError, OSError) as error:
        print(f"::error::{error}", file=sys.stderr)
    finally:
        if tenant_id is not None:
            cleanup_error = remove_tenant(call, tenant_id)
            if cleanup_error:
                print(
                    f"::error::run-scoped smoke tenant {tenant_id} cleanup incomplete: {cleanup_error}",
                    file=sys.stderr,
                )
                return 1
            print(f"run-scoped smoke tenant {tenant_id} removed")
    return 0 if smoke_status == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTPS staging API origin")
    parser.add_argument("--timeout", type=int, default=15)
    args = parser.parse_args(argv)
    return run(
        base_url=args.base_url,
        admin_key=os.environ.get("STAGING_ADMIN_API_KEY", ""),
        run_label=os.environ.get("GITHUB_RUN_ID", "local"),
        timeout=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
