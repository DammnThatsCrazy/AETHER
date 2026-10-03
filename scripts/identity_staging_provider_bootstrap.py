#!/usr/bin/env python3
"""Create and verify a real provider connection for one staging run.

All input is explicit and environment-backed. Secret values are sent only to
AETHER's tenant-scoped credential broker endpoint and are never logged or
written to output artifacts. On success, only the opaque connection ID is
emitted for a later staging scenario step.
"""
from __future__ import annotations

import json
import os
import re
import sys
import argparse
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class BootstrapError(RuntimeError):
    """Safe-to-display bootstrap failure with no request/credential values."""


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    provider_identity: str
    config: dict[str, Any]
    credential: dict[str, Any]
    admin_api_key: str | None = None
    poll_interval: float = 3.0
    timeout: float = 20.0
    max_wait: float = 600.0


def _required_env(env: dict[str, str], key: str) -> str:
    value = env.get(key, "")
    if not value or any(ch in value for ch in "\r\n\x00"):
        raise BootstrapError(f"required environment variable {key} is missing or invalid")
    return value


def _json_object(env: dict[str, str], key: str) -> dict[str, Any]:
    raw = _required_env(env, key)
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        raise BootstrapError(f"environment variable {key} must contain a JSON object") from None
    if not isinstance(value, dict):
        raise BootstrapError(f"environment variable {key} must contain a JSON object")
    return value


def settings_from_env(env: dict[str, str] | None = None) -> Settings:
    source = os.environ if env is None else env
    base_url = _required_env(source, "AETHER_STAGING_BASE_URL").rstrip("/")
    if not base_url.startswith("https://"):
        raise BootstrapError("AETHER_STAGING_BASE_URL must use HTTPS")
    identity = _required_env(source, "AETHER_STAGING_PROVIDER_IDENTITY")
    return Settings(
        base_url=base_url,
        api_key=_required_env(source, "AETHER_STAGING_TENANT_WRITE_KEY"),
        provider_identity=identity,
        config=_json_object(source, "AETHER_STAGING_PROVIDER_CONFIG_JSON"),
        credential=_json_object(source, "AETHER_STAGING_PROVIDER_CREDENTIAL_JSON"),
        admin_api_key=source.get("AETHER_STAGING_TENANT_ADMIN_KEY") or None,
        poll_interval=float(source.get("AETHER_STAGING_PROVIDER_POLL_INTERVAL", "3")),
        timeout=float(source.get("AETHER_STAGING_PROVIDER_HTTP_TIMEOUT", "20")),
        max_wait=float(source.get("AETHER_STAGING_PROVIDER_MAX_WAIT", "600")),
    )


def validate_provider_inputs(env: dict[str, str] | None = None) -> None:
    """Validate provider secrets locally before staging infrastructure is woken.

    This mode deliberately performs no request and prints no input values. It
    lets the lifecycle workflow catch missing or malformed provider secrets in
    its pre-wake job, while the regular run still validates the full runtime
    settings after the staging API is available.
    """
    source = os.environ if env is None else env
    _required_env(source, "AETHER_STAGING_PROVIDER_IDENTITY")
    _json_object(source, "AETHER_STAGING_PROVIDER_CONFIG_JSON")
    _json_object(source, "AETHER_STAGING_PROVIDER_CREDENTIAL_JSON")


Transport = Callable[[str, str, dict[str, str], dict[str, Any] | None, float], tuple[int, Any]]


def _http_transport(method: str, url: str, headers: dict[str, str], body: dict[str, Any] | None, timeout: float) -> tuple[int, Any]:
    data = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except HTTPError as exc:
        # Discard body: provider errors sometimes echo request details.
        return exc.code, None
    except (URLError, TimeoutError, OSError):
        raise BootstrapError("provider staging request failed before receiving a response") from None
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise BootstrapError("provider staging API returned invalid JSON") from None


class ProviderBootstrap:
    def __init__(self, settings: Settings, *, transport: Transport = _http_transport,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": settings.api_key,
        }

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None,
        *, api_key: str | None = None,
    ) -> dict[str, Any]:
        try:
            headers = self.headers if api_key is None else {
                **self.headers, "X-API-Key": api_key,
            }
            status, payload = self.transport(method, self.settings.base_url + path, headers, body, self.settings.timeout)
        except BootstrapError:
            raise
        except Exception:
            raise BootstrapError("provider staging request failed before receiving a response") from None
        if status < 200 or status >= 300:
            raise BootstrapError(f"provider staging API request failed (HTTP {status}, {method} {path.split('?')[0]})")
        if not isinstance(payload, dict):
            raise BootstrapError("provider staging API returned an invalid response shape")
        if payload.get("success") is False or payload.get("error"):
            raise BootstrapError("provider staging API reported an unsuccessful operation")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise BootstrapError("provider staging API returned an invalid data shape")
        return data

    def _validate_manifest_inputs(self, manifest: dict[str, Any]) -> None:
        configuration = manifest.get("configuration")
        fields = configuration.get("fields", []) if isinstance(configuration, dict) else []
        if not isinstance(fields, list):
            raise BootstrapError("provider registry returned an invalid configuration contract")
        declared: set[str] = set()
        for field in fields:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                raise BootstrapError("provider registry returned an invalid configuration contract")
            name = field["name"]
            declared.add(name)
            if field.get("required") and name not in self.settings.config:
                raise BootstrapError(f"provider configuration is missing required field {name}")

    def cleanup(self, connection_id: str) -> None:
        """Hard-delete broker material, then disable the per-run connection."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", connection_id):
            raise BootstrapError("staging cleanup requires a safe opaque connection ID")
        if not self.settings.admin_api_key:
            raise BootstrapError("staging cleanup requires the isolated tenant admin key to disable the connection")
        encoded = quote(connection_id, safe="")
        self._request("DELETE", f"/v1/provider-connections/{encoded}/credentials")
        self._request("DELETE", f"/v1/provider-connections/{encoded}", api_key=self.settings.admin_api_key)

    def run(self, *, on_created: Callable[[str], None] | None = None) -> str:
        identity = quote(self.settings.provider_identity, safe=".")
        manifest = self._request("GET", f"/v1/provider-connections/providers/{identity}")
        if manifest.get("identity_key") != self.settings.provider_identity:
            # Older serialized manifests may omit computed identity_key. Verify
            # the canonical tuple instead of accepting an unrelated registry row.
            parts = self.settings.provider_identity.split(".")
            if len(parts) != 3 or [manifest.get("provider_family"), manifest.get("product_id"), manifest.get("capability_id")] != parts:
                raise BootstrapError("provider identity is not present in the staging registry")

        self._validate_manifest_inputs(manifest)
        created = self._request("POST", "/v1/provider-connections", {
            "provider_identity": self.settings.provider_identity,
            "display_name": "Identity continuity staging reimport",
            "config": self.settings.config,
        })
        connection_id = created.get("connection_id")
        if not isinstance(connection_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", connection_id):
            raise BootstrapError("provider staging API did not return a safe opaque connection ID")
        raw_connection_id = connection_id

        try:
            if on_created is not None:
                on_created(raw_connection_id)
            # Credential payload is sent only to the broker endpoint. Never include
            # it in exceptions, logs, CLI output, or workflow outputs.
            self._request("POST", f"/v1/provider-connections/{connection_id}/credentials", self.settings.credential)
            tested = self._request("POST", f"/v1/provider-connections/{connection_id}/test")
            if tested.get("success") is not True:
                raise BootstrapError("provider credentials were not accepted by the provider")

            accounts = manifest.get("accounts") if isinstance(manifest.get("accounts"), dict) else {}
            if accounts.get("discovery_supported"):
                discovered = self._request("GET", f"/v1/provider-connections/{connection_id}/accounts")
                items = discovered.get("items")
                if not isinstance(items, list):
                    raise BootstrapError("provider account discovery returned an invalid response")
                if accounts.get("selection_required"):
                    if not items:
                        raise BootstrapError("provider requires an account but discovery returned none")
                    account_id = items[0].get("account_id") if isinstance(items[0], dict) else None
                    if not isinstance(account_id, str) or not account_id:
                        raise BootstrapError("provider account discovery returned no selectable account")
                    self._request("POST", f"/v1/provider-connections/{connection_id}/accounts/select", {"account_id": account_id})

            sync = self._request("POST", f"/v1/provider-connections/{connection_id}/sync", {})
            run_id = sync.get("sync_run_id")
            if not isinstance(run_id, str) or not run_id:
                raise BootstrapError("provider initial sync did not return a sync run ID")
            deadline = self.clock() + self.settings.max_wait
            while self.clock() <= deadline:
                runs = self._request("GET", f"/v1/provider-connections/{connection_id}/sync-runs?limit=50")
                items = runs.get("items")
                if not isinstance(items, list):
                    raise BootstrapError("provider sync status returned an invalid response")
                current = next((row for row in items if isinstance(row, dict) and row.get("sync_run_id") == run_id), None)
                if current is not None:
                    status = current.get("status")
                    if status in {"failed", "partial", "rolled_back"}:
                        raise BootstrapError("provider initial sync did not complete successfully")
                    if status == "completed":
                        received = current.get("records_received", 0)
                        if not isinstance(received, int) or received <= 0:
                            raise BootstrapError("provider initial sync completed without importing records")
                        return raw_connection_id
                self.sleep(min(self.settings.poll_interval, max(0, deadline - self.clock())))
            raise BootstrapError("provider initial sync did not complete before the staging timeout")
        except (BootstrapError, OSError) as exc:
            try:
                self.cleanup(raw_connection_id)
            except BootstrapError:
                pass
            if isinstance(exc, BootstrapError):
                raise
            raise BootstrapError("could not publish the staging connection cleanup handle") from None


def _write_connection_id(connection_id: str, env: dict[str, str] | None = None) -> None:
    target_env = os.environ if env is None else env
    # GitHub Actions receives only the opaque ID. No config, credential, or
    # response body is written to workflow files.
    path = target_env.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"provider_connection_id={connection_id}\n")
    requested = target_env.get("AETHER_PROVIDER_CONNECTION_OUTPUT")
    if requested:
        with open(requested, "w", encoding="utf-8") as handle:
            handle.write(connection_id + "\n")
    if not any(target_env.get(key) for key in ("GITHUB_OUTPUT", "GITHUB_ENV", "AETHER_PROVIDER_CONNECTION_OUTPUT")):
        print(connection_id)


def _write_connection_env(connection_id: str, env: dict[str, str] | None = None) -> None:
    """Publish the cleanup handle as soon as a durable connection exists."""
    target_env = os.environ if env is None else env
    path = target_env.get("GITHUB_ENV")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"AETHER_STAGING_PROVIDER_CONNECTION_ID={connection_id}\n")


def main() -> int:
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("--cleanup", action="store_true", help="hard-delete the run credential and disable its connection")
        parser.add_argument("--validate-inputs-only", action="store_true", help="validate provider secrets without network access")
        args = parser.parse_args()
        if args.cleanup and args.validate_inputs_only:
            raise BootstrapError("--cleanup cannot be combined with --validate-inputs-only")
        if args.validate_inputs_only:
            validate_provider_inputs()
        elif args.cleanup:
            env = os.environ
            base_url = _required_env(env, "AETHER_STAGING_BASE_URL").rstrip("/")
            if not base_url.startswith("https://"):
                raise BootstrapError("AETHER_STAGING_BASE_URL must use HTTPS")
            connection_id = _required_env(env, "AETHER_STAGING_PROVIDER_CONNECTION_ID")
            cfg = Settings(
                base_url,
                _required_env(env, "AETHER_STAGING_TENANT_WRITE_KEY"),
                "cleanup", {}, {},
                admin_api_key=_required_env(env, "AETHER_STAGING_TENANT_ADMIN_KEY"),
            )
            ProviderBootstrap(cfg).cleanup(connection_id)
        else:
            cfg = settings_from_env()
            connection_id = ProviderBootstrap(cfg).run(on_created=_write_connection_env)
            _write_connection_id(connection_id)
    except BootstrapError as exc:
        print(f"identity staging provider bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except (ValueError, OSError):
        print("identity staging provider bootstrap failed due to invalid runtime configuration or output destination", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
