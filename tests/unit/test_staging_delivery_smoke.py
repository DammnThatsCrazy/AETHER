from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "staging_delivery_smoke.py"
spec = importlib.util.spec_from_file_location("staging_delivery_smoke", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = smoke
spec.loader.exec_module(smoke)

BASE = "https://api.staging.olympuslabsml.com"
ADMIN = "ak_" + "A" * 24
TENANT_KEY = "ak_" + "B" * 24


class FakeApi:
    def __init__(
        self,
        *,
        key_status: int = 201,
        delete: tuple[int, dict] | None = None,
        deactivate: tuple[int, dict] | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.key_status = key_status
        self.delete = delete or (200, {"data": {"deleted": {"cleanup_complete": True}}})
        self.deactivate = deactivate or (
            200,
            {"data": {"status": "inactive", "api_keys_revoked": 1, "keys_evicted": 1}},
        )

    def __call__(self, method: str, path: str, body: Any = None) -> tuple[int, dict]:
        self.calls.append((method, path, body))
        if (method, path) == ("POST", "/v1/admin/tenants"):
            return 201, {"data": {"tenant_id": "tn_smoke"}}
        if path == "/v1/admin/tenants/tn_smoke/api-keys":
            return self.key_status, {
                "data": {"api_key": TENANT_KEY}
            } if self.key_status < 300 else {}
        if method == "DELETE":
            return self.delete
        if path.endswith("/deactivate"):
            return self.deactivate
        raise AssertionError((method, path))


def _run(api: FakeApi, smoke_status: int = 0, captured: list | None = None) -> int:
    def fake_smoke(argv: list[str]) -> int:
        if captured is not None:
            captured.append(argv)
        return smoke_status

    return smoke.run(
        base_url=BASE, admin_key=ADMIN, run_label="42", timeout=15, call=api, smoke=fake_smoke
    )


def test_smokes_with_a_run_scoped_tenant_key_and_removes_the_tenant():
    api, argv = FakeApi(), []
    assert _run(api, captured=argv) == 0
    create = api.calls[0]
    assert create[2]["plan"] == "enterprise"
    assert create[2]["settings"] == {"lifecycle": "run-scoped-delivery-smoke"}
    assert create[2]["contact_email"].endswith("@staging.invalid")
    # The tenant key drives the smoke; the admin key is only for diagnostics.
    assert argv[0][argv[0].index("--api-key") + 1] == TENANT_KEY
    assert argv[0][argv[0].index("--admin-api-key") + 1] == ADMIN
    assert argv[0][argv[0].index("--base-url") + 1] == BASE
    assert ("DELETE", "/v1/admin/tenants/tn_smoke", None) in api.calls


def test_a_failed_smoke_still_removes_the_tenant_and_fails():
    api = FakeApi()
    assert _run(api, smoke_status=1) == 1
    assert ("DELETE", "/v1/admin/tenants/tn_smoke", None) in api.calls


def test_key_creation_failure_removes_the_created_tenant():
    api, argv = FakeApi(key_status=500), []
    assert _run(api, captured=argv) == 1
    assert argv == []
    assert ("DELETE", "/v1/admin/tenants/tn_smoke", None) in api.calls


def test_unproven_delete_falls_back_to_deactivation():
    api = FakeApi(delete=(409, {}))
    assert _run(api) == 0
    assert ("POST", "/v1/admin/tenants/tn_smoke/deactivate", None) in api.calls


def test_incomplete_cleanup_fails_even_when_the_smoke_passed():
    api = FakeApi(delete=(200, {"data": {"deleted": {}}}))
    assert _run(api) == 1
    api = FakeApi(delete=(409, {}), deactivate=(200, {"data": {"status": "inactive"}}))
    assert _run(api) == 1


def test_refuses_non_staging_origins_and_malformed_admin_keys():
    def never(*_: Any) -> Any:
        raise AssertionError("no request may be made")

    assert (
        smoke.run(
            base_url="https://api.olympuslabsml.com",
            admin_key=ADMIN,
            run_label="1",
            timeout=15,
            call=never,
            smoke=never,
        )
        == 2
    )
    assert (
        smoke.run(
            base_url=BASE, admin_key="not-a-key", run_label="1", timeout=15, call=never, smoke=never
        )
        == 2
    )


def test_delivery_uses_the_run_scoped_smoke_only_for_staging():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Golden-path smoke test") :]
    step = step[: step.index("- name:", 10)]
    assert 'if [ "$TARGET_ENV" = staging ]; then' in step
    assert "scripts/release/staging_delivery_smoke.py" in step
    assert "STAGING_ADMIN_API_KEY: ${{ secrets.STAGING_ADMIN_API_KEY }}" in step
    # Production keeps the fixed smoke key.
    assert '--api-key "${SMOKE_API_KEY}"' in step
