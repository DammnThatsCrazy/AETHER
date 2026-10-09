from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "identity_staging_provider_bootstrap.py"
spec = importlib.util.spec_from_file_location("identity_staging_provider_bootstrap", SCRIPT)
bootstrap = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)


IDENTITY = "shopify.products.read"
SECRET = "provider-token-never-log"


def _settings(**changes):
    values = {
        "base_url": "https://staging.example.test",
        "api_key": "tenant-write-key",
        "provider_identity": IDENTITY,
        "config": {"shop_domain": "example.myshopify.com"},
        "credential": {"type": "api_key", "api_key": SECRET},
        "admin_api_key": "tenant-admin-key",
        "poll_interval": 1,
        "timeout": 3,
        "max_wait": 10,
    }
    values.update(changes)
    return bootstrap.Settings(**values)


class FakeTransport:
    def __init__(self, *, test_success=True, sync_status="completed", records=3, response_error=None):
        self.calls = []
        self.test_success = test_success
        self.sync_status = sync_status
        self.records = records
        self.response_error = response_error

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body, timeout))
        path = url.removeprefix("https://staging.example.test")
        if self.response_error and path == self.response_error[0]:
            return self.response_error[1], {"error": f"provider detail contained {SECRET}"}
        if method == "DELETE" and path.endswith("/credentials"):
            return 200, {"data": {"credential_deleted": True}}
        if method == "DELETE" and path.count("/") == 3:
            return 200, {"data": {"state": "disabled"}}
        if path == f"/v1/provider-connections/providers/{IDENTITY}":
            return 200, {"data": {"provider_family": "shopify", "product_id": "products", "capability_id": "read", "accounts": {"discovery_supported": True, "selection_required": True}}}
        if path == "/v1/provider-connections" and method == "POST":
            return 200, {"data": {"connection_id": "conn-opaque-456"}}
        if path.endswith("/credentials"):
            assert body == {"type": "api_key", "api_key": SECRET}
            return 200, {"data": {"credential_ref": "secret-ref"}}
        if path.endswith("/test"):
            return 200, {"data": {"success": self.test_success}}
        if path.endswith("/accounts") and method == "GET":
            return 200, {"data": {"items": [{"account_id": "real-account-1"}]}}
        if path.endswith("/accounts/select"):
            return 200, {"data": {"selected_accounts": [body["account_id"]]}}
        if path.endswith("/sync") and method == "POST":
            return 200, {"data": {"sync_run_id": "sync-1"}}
        if path.endswith("/sync-runs?limit=50"):
            return 200, {"data": {"items": [{"sync_run_id": "sync-1", "status": self.sync_status, "records_received": self.records, "facts_written": 0}]}}
        raise AssertionError(f"unexpected provider API path {method} {path}")


def test_bootstraps_real_connection_and_exports_only_opaque_id(tmp_path):
    transport = FakeTransport()
    bootstrapper = bootstrap.ProviderBootstrap(_settings(), transport=transport, sleep=lambda _: None)
    output = tmp_path / "github-output"
    envfile = tmp_path / "github-env"
    connection_id = bootstrapper.run(
        on_created=lambda value: bootstrap._write_connection_env(
            value, {"GITHUB_ENV": str(envfile)}
        )
    )
    assert connection_id == "conn-opaque-456"
    assert [call[0] for call in transport.calls] == ["GET", "POST", "POST", "POST", "GET", "POST", "POST", "GET"]
    credential_call = next(call for call in transport.calls if call[1].endswith("/credentials"))
    assert credential_call[3]["api_key"] == SECRET
    bootstrap._write_connection_id(connection_id, {"GITHUB_OUTPUT": str(output)})
    assert output.read_text() == "provider_connection_id=conn-opaque-456\n"
    assert envfile.read_text() == "AETHER_STAGING_PROVIDER_CONNECTION_ID=conn-opaque-456\n"
    assert SECRET not in output.read_text() + envfile.read_text()


def test_invalid_credentials_fail_without_echoing_provider_error():
    transport = FakeTransport(test_success=False)
    with pytest.raises(bootstrap.BootstrapError, match="credentials were not accepted") as exc:
        bootstrap.ProviderBootstrap(_settings(), transport=transport).run()
    assert SECRET not in str(exc.value)
    assert not any(call[1].endswith("/sync") for call in transport.calls)


def test_empty_sync_fails_even_when_completed():
    transport = FakeTransport(records=0)
    with pytest.raises(bootstrap.BootstrapError, match="without importing records"):
        bootstrap.ProviderBootstrap(_settings(), transport=transport, sleep=lambda _: None).run()


def test_api_failure_is_sanitized_and_stops_bootstrap():
    transport = FakeTransport(response_error=("/v1/provider-connections", 401))
    with pytest.raises(bootstrap.BootstrapError) as exc:
        bootstrap.ProviderBootstrap(_settings(), transport=transport).run()
    assert "HTTP 401" in str(exc.value)
    assert SECRET not in str(exc.value)
    assert len(transport.calls) == 2


def test_required_account_with_no_discovered_accounts_fails():
    transport = FakeTransport()
    original = transport.__call__

    def no_accounts(method, url, headers, body, timeout):
        if url.endswith("/accounts") and method == "GET":
            transport.calls.append((method, url, headers, body, timeout))
            return 200, {"data": {"items": []}}
        return original(method, url, headers, body, timeout)

    with pytest.raises(bootstrap.BootstrapError, match="discovery returned none"):
        bootstrap.ProviderBootstrap(_settings(), transport=no_accounts).run()


def test_missing_inputs_and_invalid_json_fail_closed():
    with pytest.raises(bootstrap.BootstrapError, match="AETHER_STAGING_PROVIDER_CREDENTIAL_JSON"):
        bootstrap.settings_from_env({
            "AETHER_STAGING_BASE_URL": "https://staging.example.test",
            "AETHER_STAGING_TENANT_WRITE_KEY": "key",
            "AETHER_STAGING_PROVIDER_IDENTITY": IDENTITY,
            "AETHER_STAGING_PROVIDER_CONFIG_JSON": "{}",
        })


def test_pre_wake_validation_checks_secrets_without_network_or_value_output(capsys):
    bootstrap.validate_provider_inputs({
        "AETHER_STAGING_PROVIDER_IDENTITY": IDENTITY,
        "AETHER_STAGING_PROVIDER_CONFIG_JSON": '{"shop_domain":"example.myshopify.com"}',
        "AETHER_STAGING_PROVIDER_CREDENTIAL_JSON": '{"type":"api_key","api_key":"private"}',
    })
    assert capsys.readouterr().out == ""
    with pytest.raises(bootstrap.BootstrapError, match="AETHER_STAGING_PROVIDER_CREDENTIAL_JSON"):
        bootstrap.validate_provider_inputs({
            "AETHER_STAGING_PROVIDER_IDENTITY": IDENTITY,
            "AETHER_STAGING_PROVIDER_CONFIG_JSON": "{}",
        })
    with pytest.raises(bootstrap.BootstrapError, match="JSON object"):
        bootstrap.validate_provider_inputs({
            "AETHER_STAGING_PROVIDER_IDENTITY": IDENTITY,
            "AETHER_STAGING_PROVIDER_CONFIG_JSON": "[]",
            "AETHER_STAGING_PROVIDER_CREDENTIAL_JSON": "{}",
        })
    with pytest.raises(bootstrap.BootstrapError, match="JSON object"):
        bootstrap.settings_from_env({
            "AETHER_STAGING_BASE_URL": "https://staging.example.test",
            "AETHER_STAGING_TENANT_WRITE_KEY": "key",
            "AETHER_STAGING_PROVIDER_IDENTITY": IDENTITY,
            "AETHER_STAGING_PROVIDER_CONFIG_JSON": "[]",
            "AETHER_STAGING_PROVIDER_CREDENTIAL_JSON": "{}",
        })


def test_api_failure_response_body_is_never_in_error_text():
    transport = FakeTransport(response_error=(f"/v1/provider-connections/providers/{IDENTITY}", 500))
    with pytest.raises(bootstrap.BootstrapError) as exc:
        bootstrap.ProviderBootstrap(_settings(), transport=transport).run()
    assert SECRET not in str(exc.value)
    assert "provider detail" not in str(exc.value)


def test_cleanup_hard_deletes_credential_before_disabling_connection():
    transport = FakeTransport()
    bootstrap.ProviderBootstrap(_settings(), transport=transport).cleanup("conn-opaque-456")
    assert [(call[0], call[1].removeprefix("https://staging.example.test")) for call in transport.calls] == [
        ("DELETE", "/v1/provider-connections/conn-opaque-456/credentials"),
        ("DELETE", "/v1/provider-connections/conn-opaque-456"),
    ]
    assert transport.calls[0][2]["X-API-Key"] == "tenant-write-key"
    assert transport.calls[1][2]["X-API-Key"] == "tenant-admin-key"


def test_cleanup_requires_admin_key_before_disabling_connection():
    transport = FakeTransport()
    with pytest.raises(bootstrap.BootstrapError, match="tenant admin key"):
        bootstrap.ProviderBootstrap(_settings(admin_api_key=None), transport=transport).cleanup(
            "conn-opaque-456"
        )
    assert transport.calls == []


def test_failed_provider_validation_attempts_credential_cleanup():
    transport = FakeTransport(test_success=False)
    cleanup_handles = []
    with pytest.raises(bootstrap.BootstrapError, match="credentials were not accepted"):
        bootstrap.ProviderBootstrap(_settings(), transport=transport).run(
            on_created=cleanup_handles.append
        )
    assert cleanup_handles == ["conn-opaque-456"]
    assert any(call[0] == "DELETE" and call[1].endswith("/credentials") for call in transport.calls)
    assert any(call[0] == "DELETE" and call[1].endswith("conn-opaque-456") for call in transport.calls)
