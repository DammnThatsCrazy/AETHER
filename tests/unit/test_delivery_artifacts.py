import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.artifact_builder import aggregate_digest, digest_file, verify_candidate, write_once
from scripts.validate_delivery_profiles import load_yaml, validate_fallbacks, validate_frontend, validate_registry

ROOT = Path(__file__).resolve().parents[2]


def test_component_digest_and_aggregate_are_stable(tmp_path):
    component = tmp_path / "backend.tar"
    component.write_bytes(b"immutable")
    digest = digest_file(component)
    assert digest.startswith("sha256:") and len(digest) == 71
    assert aggregate_digest({"backend": digest}) == aggregate_digest({"backend": digest})


def test_candidate_cannot_be_replaced(tmp_path):
    output = tmp_path / "candidate.json"
    write_once(output, {"release_candidate_id": "rc-1", "created_at": "first"})
    write_once(output, {"release_candidate_id": "rc-1", "created_at": "second"})
    with pytest.raises(ValueError, match="immutable"):
        write_once(output, {"release_candidate_id": "rc-2", "created_at": "third"})


def test_candidate_verification_binds_component_and_commit(tmp_path):
    component = tmp_path / "web.tar"
    component.write_bytes(b"built-once")
    digest = digest_file(component)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "commit_sha": "abc1234", "component_digests": {"web": digest},
        "artifact_digest": aggregate_digest({"web": digest}),
        "dependency_lock_hash": aggregate_digest({}),
    }))
    assert verify_candidate(candidate, [f"web={component}"], [], "abc1234")["commit_sha"] == "abc1234"
    component.write_bytes(b"rebuilt")
    with pytest.raises(ValueError, match="component digests"):
        verify_candidate(candidate, [f"web={component}"], [], "abc1234")


def test_candidate_verification_binds_dependency_locks(tmp_path):
    component = tmp_path / "web.tar"
    component.write_bytes(b"built-once")
    lockfile = tmp_path / "lock"
    lockfile.write_text("one")
    digest = digest_file(component)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "commit_sha": "abc1234",
        "component_digests": {"web": digest},
        "artifact_digest": aggregate_digest({"web": digest}),
        "dependency_lock_hash": aggregate_digest({str(lockfile): digest_file(lockfile)}),
    }))
    verify_candidate(candidate, [f"web={component}"], [str(lockfile)], "abc1234")
    lockfile.write_text("two")
    with pytest.raises(ValueError, match="dependency lock hash"):
        verify_candidate(candidate, [f"web={component}"], [str(lockfile)], "abc1234")


def valid_manifest():
    return {
        "profile": "staging", "api_url": "https://api.staging.aether.test",
        "websocket_url": "wss://api.staging.aether.test/ws",
        "identity_issuer": "https://identity.staging.aether.test",
        "identity_audience": "aether-staging", "identity_client_id": "web-client",
        "identity_scopes": ["openid", "profile"],
        "redirect_urls": ["https://app.staging.aether.test/callback"],
        "tenant_bootstrap_url": "https://api.staging.aether.test/bootstrap",
        "operator_url": "https://kyber.staging.aether.test",
        "tenant_url": "https://app.staging.aether.test",
    }


def test_frontend_profile_rejects_placeholder_and_insecure_endpoint():
    policy = load_yaml(ROOT / "config/deployment_profile_compatibility.yaml")
    assert validate_frontend(valid_manifest(), policy) == []
    manifest = valid_manifest()
    manifest["api_url"] = "http://localhost:8000"
    errors = validate_frontend(manifest, policy)
    assert "api_url contains prohibited placeholder" in errors
    assert "api_url must use https or wss" in errors


def test_staging_blocks_local_fallbacks():
    registry = load_yaml(ROOT / "config/runtime_fallbacks.yaml")
    assert validate_registry(registry) == []
    assert validate_fallbacks("local", ["in_memory_queue"], registry) == []
    assert validate_fallbacks("staging", ["in_memory_queue"], registry) == [
        "fallback in_memory_queue is prohibited in staging"
    ]


def test_release_candidate_schema_accepts_builder_shape():
    schema = json.loads((ROOT / "contracts/delivery/release-candidate.schema.json").read_text())
    assert schema["properties"]["artifact_digest"]["pattern"].startswith("^sha256:")
    assert {"artifact_digest", "component_digests", "deployment_profiles"} <= set(schema["required"])


def test_committed_delivery_policy_has_a_registry_only_gate():
    result = subprocess.run(
        [sys.executable, "scripts/validate_delivery_profiles.py", "--check-registry"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"
