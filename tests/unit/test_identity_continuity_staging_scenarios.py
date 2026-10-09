from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import urllib.request
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/identity_continuity_staging_scenarios.py"
SPEC = importlib.util.spec_from_file_location("identity_continuity_staging_scenarios", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._payload


def test_scenario_result_digest_matches_retained_redacted_artifact(monkeypatch, tmp_path):
    captured = {}
    observed_keys = []

    def fake_urlopen(request, timeout=0):
        observed_keys.append((request.full_url, request.get_header("X-api-key")))
        if request.full_url.endswith("/v1/identity/health"):
            return _Response({"data": {"tenant_id": "tenant-test"}})
        if request.full_url.endswith("/staging-proof-scenarios"):
            captured["body"] = json.loads(request.data)
            return _Response({"data": {"outcome": captured["body"]["outcome"]}})
        raise AssertionError(request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    ctx = runner.ScenarioContext(
        "https://staging.example", "opaque-key", "tenant-test",
        "07f97f5e-6abe-4cff-8ec6-0899d8ace700", tmp_path, admin_api_key="admin-key",
    )
    result = runner.execute_scenario(ctx, "cross_tenant_block")

    artifact_path = tmp_path / "cross_tenant_block.json"
    artifact = artifact_path.read_bytes()
    assert result["outcome"] == "failed"
    assert result["recorded"] is True
    assert captured["body"]["outcome"] == "failed"
    assert captured["body"]["assertions_failed"] > 0
    assert captured["body"]["assertions_passed"] > 0
    assert captured["body"]["evidence_sha256"] == hashlib.sha256(artifact).hexdigest()
    document = json.loads(artifact)
    assert document["scenario_id"] == "cross_tenant_block"
    assert "AETHER_STAGING_FOREIGN_ENTITY_ID is required" in document["failure"]
    assert "tenant-test" not in artifact.decode()
    assert observed_keys[-1][1] == "admin-key"


def test_successful_scenario_requires_observed_api_assertions(monkeypatch, tmp_path):
    recorded = {}

    def fake_urlopen(request, timeout=0):
        if request.full_url.endswith("/v1/identity/health"):
            return _Response({"data": {"tenant_id": "tenant-test"}})
        if request.full_url.endswith("/staging-proof-scenarios"):
            recorded.update(json.loads(request.data))
            return _Response({"data": {"outcome": "passed"}})
        raise AssertionError(request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setitem(runner.RUNNERS, "A_import_first_sdk_later", lambda ctx: ctx.check(True, "observed invariant"))
    ctx = runner.ScenarioContext(
        "https://staging.example", "opaque-key", "tenant-test",
        "ec8879e8-33a4-4906-90af-bf49f1ac7433", tmp_path, admin_api_key="admin-key",
    )

    result = runner.execute_scenario(ctx, "A_import_first_sdk_later")

    assert result["outcome"] == "passed"
    assert recorded["outcome"] == "passed"
    assert recorded["assertions_passed"] == 2
    assert recorded["assertions_failed"] == 0


def test_api_non_success_cannot_be_recorded_as_scenario_pass(monkeypatch, tmp_path):
    recorded = {}

    def fake_urlopen(request, timeout=0):
        if request.full_url.endswith("/v1/identity/health"):
            return _Response({"data": {"tenant_id": "tenant-test"}})
        if request.full_url.endswith("/staging-proof-scenarios"):
            recorded.update(json.loads(request.data))
            return _Response({"data": {"outcome": "failed"}})
        raise AssertionError(request.full_url)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setitem(runner.RUNNERS, "B_shared_device_no_merge", lambda ctx: ctx.check(False, "two users merged"))
    ctx = runner.ScenarioContext(
        "https://staging.example", "opaque-key", "tenant-test",
        "1bdecd81-5f4f-4a33-a98a-f9fa23456789", tmp_path, admin_api_key="admin-key",
    )

    result = runner.execute_scenario(ctx, "B_shared_device_no_merge")

    assert result["outcome"] == "failed"
    assert recorded["outcome"] == "failed"
    assert recorded["assertions_failed"] == 1


def test_evidence_redacts_identifier_paths_and_secret_fields():
    path = runner._safe_path("/v1/provider-connections/connection-private/raw-records?limit=200")
    redacted = runner._redact({
        "id": "entity-private",
        "api_key": "api-secret",
        "credential_ref": "credential-private",
        "scenario_id": "cross_tenant_block",
    })

    assert path == "/v1/provider-connections/<ref>/raw-records"
    assert "connection-private" not in path
    assert redacted["id"] != "entity-private"
    assert redacted["api_key"] != "api-secret"
    assert redacted["credential_ref"] != "credential-private"
    assert redacted["scenario_id"] == "cross_tenant_block"


def test_redaction_refs_are_keyed_and_stable_only_within_the_run():
    identity = "person@example.test"
    reference = runner._value_ref(identity)

    assert reference == runner._value_ref(identity)
    assert reference.startswith("hmac-sha256:")
    assert reference != "sha256:" + hashlib.sha256(identity.encode()).hexdigest()[:20]
    assert identity not in reference


def test_admin_endpoints_require_separate_tenant_admin_credential(tmp_path):
    ctx = runner.ScenarioContext(
        "https://staging.example", "tenant-write-key", "tenant-test",
        "07f97f5e-6abe-4cff-8ec6-0899d8ace700", tmp_path,
    )

    try:
        ctx.call("GET", "/v1/admin/identity/staging-proof-capture", admin=True)
    except runner.ScenarioFailure as exc:
        assert "tenant admin API key is required" in str(exc)
    else:
        raise AssertionError("admin calls must not silently reuse the tenant write key")


def test_projection_scenario_waits_for_every_registered_projection(tmp_path):
    ctx = runner.ScenarioContext(
        "https://staging.example", "tenant-write-key", "tenant-test",
        "07f97f5e-6abe-4cff-8ec6-0899d8ace700", tmp_path,
        admin_api_key="tenant-admin-key",
    )
    ctx.resolve = lambda suffix, **_signals: {"canonical_entity_id": f"canonical-{suffix}"}
    expected = {
        "profile_360", "journey", "communications_360", "signals", "agent_360",
        "execution_360", "account_360", "syndicates", "campaign_360", "value",
    }
    status_by_projection = {name: "completed" for name in expected}
    status_by_projection["syndicates"] = "unsupported"
    responses = iter([
        (200, {"data": {"capture": {
            "restatement_jobs": [{"job_id": "preexisting-job"}],
            "feature_flags": {"campaign_restatement_enabled": True, "value_restatement_enabled": True},
        }}}),
        (200, {"data": {"restatement_status": "queued", "restatement_job_id": "raw-job-id"}}),
        (200, {"data": {"capture": {"restatement_jobs": [
            {"job_id": "preexisting-job", "status": "completed", "projection_status": {}},
            {"job_id": "new-job-ref", "status": "partially_succeeded", "projection_status": status_by_projection},
        ]}}}),
    ])
    calls = []

    def call(method, path, body=None, **kwargs):
        calls.append((method, path, body, kwargs))
        return next(responses)

    ctx.call = call
    runner._run_projection(ctx)

    assert ctx.assertions_failed == 0
    assert ctx.assertions_passed == 6
    assert sum(call[1] == "/v1/admin/identity/staging-proof-capture" for call in calls) == 2
    assert all(call[3].get("admin") is True for call in calls if "staging-proof-capture" in call[1])
