"""Safe, non-live contract tests for the one-time staging admin handoff."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/bootstrap_staging_admin_key.py"
SPEC = importlib.util.spec_from_file_location("staging_admin_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def _api_payload(api_key: str) -> bytes:
    return json.dumps({"data": {"api_key": api_key}}).encode()


def _status_payload(claimed: bool, candidate_matches: bool = False) -> bytes:
    return json.dumps({
        "data": {
            "claimed": claimed,
            "candidate_matches": candidate_matches,
        }
    }).encode()


def _admin_payload() -> bytes:
    return json.dumps({"data": {"tenant_id": "tenant-1", "is_admin": True}}).encode()


def _runtime_args(*extra: str) -> list[str]:
    return [
        "--base-url", "https://api.staging.olympuslabsml.com",
        "--repo", "DammnThatsCrazy/AETHER",
        *extra,
    ]


def _gh_auth_ok(command, **kwargs):
    assert command == ["gh", "auth", "status", "--hostname", "github.com"]
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_preflight_sets_deletes_and_verifies_disposable_repository_secret(monkeypatch, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ["gh", "secret", "set"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "secret", "delete"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "secret", "list"]:
            listed = "STAGING_ADMIN_API_KEY\n"
            list_count = len([
                item for item, _kwargs in calls
                if item[:3] == ["gh", "secret", "list"]
            ])
            if list_count == 2:
                probe_name = next(
                    item[3] for item, _kwargs in calls
                    if item[:3] == ["gh", "secret", "set"]
                )
                listed += probe_name + "\n"
            return subprocess.CompletedProcess(command, 0, stdout=listed, stderr="")
        return _gh_auth_ok(command, **kwargs)

    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    result = bootstrap.main([
        "--preflight-secret-write",
        "--repo", "DammnThatsCrazy/AETHER",
    ])

    assert result == 0
    assert [call[0][1:3] for call in calls] == [
        ["auth", "status"], ["secret", "list"], ["secret", "set"],
        ["secret", "list"], ["secret", "delete"], ["secret", "list"],
    ]
    set_command, set_kwargs = calls[2]
    probe_name = set_command[3]
    assert probe_name.startswith("AETHER_STAGING_BOOTSTRAP_PREFLIGHT_")
    assert set_command == ["gh", "secret", "set", probe_name, "--repo", "DammnThatsCrazy/AETHER"]
    assert set_kwargs["input"] and probe_name not in set_kwargs["input"]
    assert calls[4][0] == ["gh", "secret", "delete", probe_name, "--repo", "DammnThatsCrazy/AETHER"]
    list_command = calls[3][0]
    assert list_command.count("--json") == 1
    assert list_command.count("--jq") == 1
    assert list_command[-2:] == ["--jq", ".[].name"]
    assert probe_name not in capsys.readouterr().out


def test_preflight_fails_if_successful_set_is_not_visible_before_delete(monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["gh", "secret", "set"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "secret", "list"]:
            if not any(item[:3] == ["gh", "secret", "set"] for item in commands):
                return subprocess.CompletedProcess(
                    command, 0, stdout="STAGING_ADMIN_API_KEY\n", stderr=""
                )
            return subprocess.CompletedProcess(
                command, 0, stdout="STAGING_ADMIN_API_KEY\n", stderr=""
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *_args: None)

    result = bootstrap.main([
        "--preflight-secret-write",
        "--repo", "DammnThatsCrazy/AETHER",
    ])

    assert result == 2
    assert any(command[:3] == ["gh", "secret", "delete"] for command in commands)
    assert "write access could not be verified" in capsys.readouterr().err


def test_preflight_never_overwrites_a_colliding_disposable_secret_name(monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["gh", "secret", "list"]:
            # The generated probe name is existing state. No write/delete may
            # touch it; the fixed admin name also appears in this listing.
            probe_name = "AETHER_STAGING_BOOTSTRAP_PREFLIGHT_" + "A" * 32
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="STAGING_ADMIN_API_KEY\n" + probe_name + "\n",
                stderr="",
            )
        return _gh_auth_ok(command, **kwargs)

    monkeypatch.setattr(bootstrap.secrets, "token_hex", lambda _n: "A" * 32)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    result = bootstrap.main([
        "--preflight-secret-write",
        "--repo", "DammnThatsCrazy/AETHER",
    ])

    assert result == 2
    assert not any(command[:3] in (["gh", "secret", "set"], ["gh", "secret", "delete"]) for command in commands)
    assert "write access could not be verified" in capsys.readouterr().err


def test_preflight_fails_without_explicit_pat_even_if_github_token_exists(monkeypatch, capsys):
    calls = []
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "underprivileged-token")
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    result = bootstrap.main([
        "--preflight-secret-write",
        "--repo", "DammnThatsCrazy/AETHER",
    ])

    assert result == 2
    assert calls == []
    assert "must be set to WORKFLOW_DISPATCH_TOKEN or TF_AMPLIFY_GITHUB_ACCESS_TOKEN" in capsys.readouterr().err


def test_preflight_fails_when_disposable_secret_cannot_be_confirmed_absent(monkeypatch, capsys):
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["gh", "secret", "list"]:
            if not any(item[:3] == ["gh", "secret", "set"] for item in commands):
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout="STAGING_ADMIN_API_KEY\n",
                    stderr="",
                )
            probe_name = next(
                item[3] for item in commands
                if item[:3] == ["gh", "secret", "set"]
            )
            return subprocess.CompletedProcess(command, 0, stdout=f"{probe_name}\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *_args: None)

    result = bootstrap.main([
        "--preflight-secret-write",
        "--repo", "DammnThatsCrazy/AETHER",
    ])

    assert result == 2
    assert any(command[:3] == ["gh", "secret", "delete"] for command in commands)
    assert "staging bootstrap remains blocked" in capsys.readouterr().err


def test_bootstrap_stores_secret_before_post_and_exports_only_masked_env(monkeypatch, tmp_path, capsys):
    requests = []
    gh_calls = []
    events = []
    env_file = tmp_path / "github-env"
    env_file.touch()

    def fake_request(method, url, *, headers, body=None):
        requests.append((method, url, headers, body))
        events.append(("http", method))
        if method == "POST":
            return 200, _api_payload(json.loads(body)["api_key"])
        if url.endswith("/v1/auth/bootstrap/first-admin"):
            return 200, _status_payload(False)
        return 200, _admin_payload()

    def fake_run(command, **kwargs):
        gh_calls.append((command, kwargs))
        events.append(("gh", " ".join(command[1:3])))
        if command[:3] == ["gh", "secret", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="STAGING_ADMIN_API_KEY\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 0
    assert [request[0] for request in requests] == ["GET", "POST", "GET"]
    assert requests[0][1].endswith("/v1/auth/bootstrap/first-admin")
    assert events.index(("gh", "secret set")) < events.index(("http", "POST"))
    api_key = gh_calls[1][1]["input"].strip()
    assert json.loads(requests[1][3])["api_key"] == api_key
    assert api_key.startswith("ak_") and len(api_key) == 27
    assert env_file.read_text() == f"STAGING_ADMIN_API_KEY={api_key}\n"
    # The only emission containing the key is the Actions masking command;
    # it is consumed by the runner as a mask, not retained as ordinary output.
    output = capsys.readouterr().out
    assert f"::add-mask::{api_key}" in output
    assert "first-admin bootstrap completed" in output
    assert gh_calls[0][0] == ["gh", "auth", "status", "--hostname", "github.com"]
    assert gh_calls[1][0] == [
        "gh", "secret", "set", "STAGING_ADMIN_API_KEY", "--repo", "DammnThatsCrazy/AETHER"
    ]


def test_valid_existing_admin_key_is_preserved_and_sent_to_later_steps(monkeypatch, tmp_path, capsys):
    key = "ak_" + "a" * 24
    env_file = tmp_path / "github-env"
    env_file.touch()
    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", key)
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(bootstrap, "_request", lambda *args, **kwargs: (200, _admin_payload()))
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: pytest.fail("GitHub must not be called"))

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 0
    assert env_file.read_text() == f"STAGING_ADMIN_API_KEY={key}\n"
    assert f"::add-mask::{key}" in capsys.readouterr().out


def test_rejected_stale_key_is_replaced_only_when_marker_is_unclaimed(monkeypatch, tmp_path):
    key = "ak_" + "b" * 24
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    secret_writes = []
    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", key)
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    def fake_request(method, url, *, headers, body=None):
        requests.append((method, url, headers, body))
        if url.endswith("/v1/me"):
            if sum(item[1].endswith("/v1/me") for item in requests) == 1:
                return 401, b"{}"
            return 200, _admin_payload()
        if method == "GET":
            assert headers["X-Aether-First-Admin-Candidate-Key"] == key
            return 200, _status_payload(False)
        return 200, _api_payload(json.loads(body)["api_key"])

    def fake_run(command, **kwargs):
        if command == ["gh", "auth", "status", "--hostname", "github.com"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "secret", "set"]:
            secret_writes.append(kwargs["input"].strip())
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command[:3] == ["gh", "secret", "list"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="STAGING_ADMIN_API_KEY\n", stderr=""
            )
        pytest.fail(f"unexpected GitHub command: {command}")

    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 0
    assert [item[0] for item in requests] == ["GET", "GET", "POST", "GET"]
    generated = json.loads(requests[2][3])["api_key"]
    assert generated != key
    assert secret_writes == [generated]
    assert env_file.read_text() == f"STAGING_ADMIN_API_KEY={generated}\n"


def test_malformed_existing_secret_is_replaced_only_after_unclaimed_marker_and_before_post(monkeypatch, tmp_path):
    env_file = tmp_path / "github-env"
    env_file.touch()
    events = []
    requests = []

    def fake_request(method, url, *, headers, body=None):
        requests.append((method, url, body))
        if method == "GET":
            events.append(("http", "GET"))
            if url.endswith("/v1/auth/bootstrap/first-admin"):
                return 200, _status_payload(False)
            return 200, _admin_payload()
        events.append(("http", "POST"))
        return 200, _api_payload(json.loads(body)["api_key"])

    def fake_run(command, **kwargs):
        events.append(("gh", " ".join(command[1:3])))
        if command[:3] == ["gh", "secret", "list"]:
            return subprocess.CompletedProcess(command, 0, stdout="STAGING_ADMIN_API_KEY\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", "bootstrap-token-not-an-api-key")
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 0
    assert events.index(("http", "GET")) < events.index(("gh", "secret set"))
    assert events.index(("gh", "secret set")) < events.index(("http", "POST"))
    generated = json.loads(requests[1][2])["api_key"]
    assert generated.startswith("ak_")
    assert env_file.read_text() == f"STAGING_ADMIN_API_KEY={generated}\n"


def test_secret_store_failure_never_consumes_first_admin_route(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(bootstrap, "_request", lambda method, url, **kwargs: (
        requests.append((method, url)) or (200, _status_payload(False))
    ))
    monkeypatch.setattr(bootstrap.subprocess, "run", _gh_auth_ok)
    monkeypatch.setattr(bootstrap, "_store_repository_secret", lambda *_args: False)

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 2
    assert requests == [("GET", "https://api.staging.olympuslabsml.com/v1/auth/bootstrap/first-admin")]
    assert "one-time bootstrap was not called" in capsys.readouterr().err


def test_claimed_marker_never_replaces_an_existing_admin_candidate(monkeypatch, tmp_path, capsys):
    key = "ak_" + "c" * 24
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", key)
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    def fake_request(method, url, **kwargs):
        requests.append(method)
        if url.endswith("/v1/me"):
            return 401, b"{}"
        return 200, _status_payload(True)

    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.subprocess, "run", _gh_auth_ok)
    monkeypatch.setattr(bootstrap, "_store_repository_secret", lambda *_args: pytest.fail("must not replace"))

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 1
    assert requests == ["GET", "GET"]
    assert "already claimed" in capsys.readouterr().err
    assert env_file.read_text() == ""


def test_claimed_marker_resumes_only_the_same_stored_candidate(monkeypatch, tmp_path, capsys):
    key = "ak_" + "g" * 24
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", key)
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    def fake_request(method, url, *, headers, body=None):
        requests.append((method, url, headers, body))
        if url.endswith("/v1/me"):
            if sum(item[1].endswith("/v1/me") for item in requests) == 1:
                return 401, b"{}"
            return 200, _admin_payload()
        if method == "GET":
            assert headers["X-Aether-First-Admin-Candidate-Key"] == key
            return 200, _status_payload(True, candidate_matches=True)
        return 200, _api_payload(json.loads(body)["api_key"])

    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("a stored-key retry must not rewrite GitHub secrets"),
    )

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 0
    assert [item[0] for item in requests] == ["GET", "GET", "POST", "GET"]
    assert json.loads(requests[2][3])["api_key"] == key
    assert env_file.read_text() == f"STAGING_ADMIN_API_KEY={key}\n"
    assert "resuming the identical idempotent request" in capsys.readouterr().out


def test_uncertain_existing_key_verification_fails_closed(monkeypatch, tmp_path, capsys):
    key = "ak_" + "d" * 24
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    monkeypatch.setenv("EXISTING_STAGING_ADMIN_API_KEY", key)
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setenv("GITHUB_ENV", str(env_file))

    def fake_request(method, url, **kwargs):
        requests.append((method, url))
        raise bootstrap.urllib.error.URLError("temporary disconnect")

    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.subprocess, "run", _gh_auth_ok)

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 1
    assert requests and len(requests) == 1
    assert requests[0][1].endswith("/v1/me")
    assert "refusing to replace or bootstrap" in capsys.readouterr().err


def test_missing_github_env_fails_before_bootstrap_or_network(monkeypatch, capsys):
    requests = []
    monkeypatch.delenv("GITHUB_ENV", raising=False)
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GH_TOKEN", "configured-pat")
    monkeypatch.setattr(bootstrap, "_request", lambda *args, **kwargs: requests.append(args))

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 2
    assert requests == []
    assert "writable GITHUB_ENV" in capsys.readouterr().err


def test_bootstrap_never_calls_one_time_route_without_configured_secret_write_token(monkeypatch, tmp_path, capsys):
    env_file = tmp_path / "github-env"
    env_file.touch()
    requests = []
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "underprivileged-token")
    monkeypatch.setenv("FIRST_ADMIN_BOOTSTRAP_TOKEN", "opaque-token-" + "x" * 32)
    monkeypatch.setenv("GITHUB_ENV", str(env_file))
    monkeypatch.setattr(bootstrap, "_request", lambda *args, **kwargs: requests.append(args))

    result = bootstrap.main(_runtime_args("--allow-bootstrap", "--confirm-single-use"))

    assert result == 2
    assert requests == []
    assert "must be set to WORKFLOW_DISPATCH_TOKEN or TF_AMPLIFY_GITHUB_ACCESS_TOKEN" in capsys.readouterr().err


def test_bootstrap_retry_reuses_the_same_key_after_uncertain_response(monkeypatch):
    api_key = "ak_" + "f" * 24
    requests = []

    def fake_request(method, url, *, headers, body=None):
        requests.append((method, url, headers, body))
        if len(requests) == 1:
            raise bootstrap.urllib.error.URLError("temporary disconnect")
        return 200, _api_payload(api_key)

    monkeypatch.setattr(bootstrap, "_request", fake_request)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *_args: None)
    ok, reason = bootstrap._request_bootstrap(
        "https://api.staging.olympuslabsml.com", "opaque-token", api_key
    )
    assert ok is True
    assert reason == ""
    assert json.loads(requests[0][3]) == json.loads(requests[1][3])
    assert json.loads(requests[0][3])["api_key"] == api_key


def test_repository_secret_write_hides_key_in_argv_and_uses_stdin(monkeypatch):
    api_key = "ak_" + "e" * 24
    observed = []

    def fake_run(command, **kwargs):
        observed.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bootstrap.subprocess, "run", fake_run)
    assert bootstrap._store_repository_secret("DammnThatsCrazy/AETHER", api_key)
    command, kwargs = observed[0]
    assert api_key not in command
    assert kwargs["input"] == api_key + "\n"
