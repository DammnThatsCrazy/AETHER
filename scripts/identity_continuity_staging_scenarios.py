#!/usr/bin/env python3
"""Run and record the ten live identity-continuity staging scenarios.

The runner uses tenant-authenticated public APIs. Every scenario produces a
redacted API transcript before its digest is submitted to the staging evidence
endpoint. Unsupported or failed assertions are recorded as failures, never as
skipped or passing results.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCENARIOS = (
    "A_import_first_sdk_later",
    "B_shared_device_no_merge",
    "C_bad_merge_split",
    "D_agent_human_no_merge",
    "shared_email_review",
    "cross_tenant_block",
    "deleted_suppressed_identity_block",
    "multi_sdk_same_user",
    "connector_reimport_idempotency",
    "projection_restatement",
)

# Proof artifacts need stable references within one run so related API events
# can be compared, but a plain digest lets readers test guessed emails and IDs.
# This process-local random key makes references unlinkable across runs and is
# never written to the transcript, environment, or evidence API.
_REDACTION_KEY = secrets.token_bytes(32)


class ScenarioFailure(RuntimeError):
    pass


@dataclass
class ScenarioContext:
    base_url: str
    api_key: str
    tenant_id: str
    execution_id: str
    output_dir: Path
    admin_api_key: str | None = None
    tenant_ref: str | None = None
    foreign_entity_id: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    assertions_passed: int = 0
    assertions_failed: int = 0

    def call(
        self, method: str, path: str, body: dict[str, Any] | bytes | None = None,
        *, admin: bool = False, content_type: str = "application/json",
    ) -> tuple[int, Any]:
        data = None if body is None else (
            body if isinstance(body, bytes) else json.dumps(body, separators=(",", ":")).encode()
        )
        if admin and not self.admin_api_key:
            raise ScenarioFailure("an isolated tenant admin API key is required for this endpoint")
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.admin_api_key if admin else self.api_key,
        }
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base_url.rstrip("/") + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                status = response.status
                raw = response.read()
                try:
                    parsed = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    parsed = {"invalid_json": True}
        except urllib.error.HTTPError as exc:
            status = exc.code
            try:
                parsed = json.loads(exc.read())
            except Exception:
                parsed = {}
        except (urllib.error.URLError, TimeoutError) as exc:
            self.trace.append({"method": method, "path": path, "status": 0, "error": type(exc).__name__})
            raise ScenarioFailure(f"API request unavailable ({type(exc).__name__})") from None
        if path.endswith("/raw-records") and isinstance(parsed, dict):
            safe_response = _data(parsed)
            parsed_trace = {key: safe_response.get(key) for key in ("count", "total", "truncated")}
        else:
            parsed_trace = parsed
        self.trace.append({"method": method, "path": _safe_path(path), "status": status, "response": parsed_trace})
        return status, parsed

    def check(self, condition: bool, message: str) -> None:
        if condition:
            self.assertions_passed += 1
        else:
            self.assertions_failed += 1
            raise ScenarioFailure(message)

    def resolve(self, suffix: str, **signals: Any) -> dict[str, Any]:
        anonymous_id = f"ic-{self.execution_id}-{suffix}-anon"
        self.call("POST", "/v1/consent/records", {
            "anonymous_id": anonymous_id, "purposes": ["analytics"], "granted": True,
            "source": "staging-identity-continuity", "mode": "opt_in",
            "idempotency_key": f"{self.execution_id}:{suffix}:consent",
        })
        consent_status, consent_raw = self.trace[-1]["status"], self.trace[-1].get("response", {})
        self.check(consent_status == 200 and bool(_data(consent_raw)),
                   f"server-authoritative consent receipt could not be recorded (HTTP {consent_status})")
        status, result = self.call("POST", "/v1/identity/resolve", {
            "event_id": f"ic-{self.execution_id}-{suffix}",
            "anonymous_id": anonymous_id,
            **signals,
            "context": {"source": "identity_continuity_staging_scenario", "execution_id": self.execution_id},
        })
        data = result.get("data", result) if isinstance(result, dict) else {}
        self.check(status == 200 and isinstance(data, dict) and bool(data.get("canonical_entity_id")),
                   f"identity resolve did not return a canonical entity (HTTP {status})")
        self.check(data.get("tenant_id") == self.tenant_id, "identity API returned a different tenant")
        return data


def _value_ref(value: Any) -> str:
    digest = hmac.new(_REDACTION_KEY, str(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return "hmac-sha256:" + digest[:20]


def _safe_path(path: str) -> str:
    clean = urllib.parse.urlsplit(path).path
    parts = clean.split("/")
    id_after = {
        "entities", "imports", "jobs", "provider-connections", "review-queue",
        "suppress", "connections", "files", "scenarios",
    }
    for index in range(1, len(parts)):
        if parts[index - 1] in id_after and parts[index]:
            parts[index] = "<ref>"
    return "/".join(parts)


def _redact(value: Any, key: str = "") -> Any:
    lowered = key.lower()
    sensitive = (
        lowered not in {"scenario_id", "execution_id"}
        and (lowered == "id" or lowered.endswith("_id") or lowered.endswith("_token")
             or lowered.endswith("_secret") or lowered.endswith("_credential")
             or lowered in {"api_key", "token", "secret", "credential"})
    ) or any(token in lowered for token in (
        "email", "phone", "user_id", "anonymous", "entity_id", "canonical_entity",
        "source_identity", "conflict_id", "audit_id", "event_id", "session_id",
        "device_id", "installation_id", "suppression_id", "tenant_id", "actor_id",
        "api_key", "credential", "secret", "token", "identifier_hash",
        "email_hash", "phone_hash",
    ))
    if sensitive and value is not None:
        if isinstance(value, list):
            return [_value_ref(item) for item in value]
        if isinstance(value, dict):
            return {str(k): _value_ref(v) for k, v in value.items()}
        return _value_ref(value)
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, str) and "@" in value:
        return _value_ref(value)
    return value


def _data(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data", value)
    return data if isinstance(data, dict) else {}


def _required_data(ctx: ScenarioContext, method: str, path: str, body: Any = None,
                   *, content_type: str = "application/json") -> dict[str, Any]:
    status, raw = ctx.call(method, path, body, content_type=content_type)
    data = _data(raw)
    ctx.check(status == 200 and isinstance(data, dict), f"{method} {path} failed (HTTP {status})")
    return data


def _csv_import(ctx: ScenarioContext, suffix: str, email: str, external_id: str) -> tuple[str, dict[str, Any]]:
    created = _required_data(ctx, "POST", "/v1/imports")
    import_id = created.get("id") or created.get("import_id") or created.get("session", {}).get("id")
    ctx.check(bool(import_id), "import API did not return an import session ID")
    encoded = urllib.parse.quote(str(import_id), safe="")
    csv_bytes = f"entity_id,identifier_type,value\n{external_id},email,{email}\n".encode()
    uploaded = _required_data(ctx, "POST", f"/v1/imports/{encoded}/files?filename=identity-{suffix}.csv",
                             csv_bytes, content_type="text/csv")
    ctx.check(bool(uploaded.get("file_id") or uploaded.get("id")), "import API did not confirm uploaded file")
    analyzed = _required_data(ctx, "POST", f"/v1/imports/{encoded}/analyze")
    ctx.check(int(analyzed.get("row_count") or 0) == 1, "CSV analysis did not find exactly one source row")
    mapping = [
        {"source_column": "entity_id", "primitive": "entity", "target_field": "external_id", "required": True},
        {"source_column": "identifier_type", "primitive": "identifier", "target_field": "identifier_type", "required": True},
        {"source_column": "value", "primitive": "identifier", "target_field": "value", "required": True},
        {"source_column": "entity_id", "primitive": "identifier", "target_field": "entity_ref", "required": True},
    ]
    _required_data(ctx, "PUT", f"/v1/imports/{encoded}/mapping", {"fields": mapping})
    validation = _required_data(ctx, "POST", f"/v1/imports/{encoded}/validate")
    ctx.check(validation.get("ok") is True, "CSV identity mapping did not validate")
    _required_data(ctx, "POST", f"/v1/imports/{encoded}/approve")
    committed = _required_data(ctx, "POST", f"/v1/imports/{encoded}/commit")
    job = committed.get("job") if isinstance(committed.get("job"), dict) else {}
    job_id = job.get("id") or job.get("job_id")
    ctx.check(bool(job_id), "import commit did not return a durable job ID")
    job_path = "/v1/jobs/" + urllib.parse.quote(str(job_id), safe="")
    deadline = time.monotonic() + 180
    terminal = None
    while time.monotonic() < deadline:
        response = _required_data(ctx, "GET", job_path)
        state = response.get("status")
        if state in {"succeeded", "completed", "failed", "dead_letter", "cancelled"}:
            terminal = response
            break
        time.sleep(2)
    ctx.check(terminal is not None and terminal.get("status") in {"succeeded", "completed"},
              "CSV identity commit did not finish successfully within 180 seconds")
    session = _required_data(ctx, "GET", f"/v1/imports/{encoded}")
    ctx.check(session.get("session", {}).get("status") == "committed",
              "CSV import session did not reach committed state")
    return str(import_id), session


def _run_a(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    email = f"a-{tag}@example.invalid"
    _csv_import(ctx, "late-binding", email, f"csv-{tag}")
    app = os.getenv("AETHER_STAGING_TENANT_APP_KEY", "")
    ctx.check(bool(app), "AETHER_STAGING_TENANT_APP_KEY is required for the SDK late-binding step")
    if not app:
        return
    anonymous_id = f"a-anonymous-{tag}"
    _required_data(ctx, "POST", "/v1/consent/records", {
        "anonymous_id": anonymous_id, "purposes": ["analytics"], "granted": True,
        "source": "staging-identity-continuity", "mode": "opt_in",
        "idempotency_key": f"{ctx.execution_id}:scenario-a-consent",
    })
    sdk = _required_data(ctx, "POST", "/sdk/identify", {
        "tenant_app_key": app, "user_id": f"sdk-user-{tag}", "anonymous_id": anonymous_id,
        "traits": {"email": email}, "sdk_name": "aether-web", "sdk_version": "staging-proof",
        "idempotency_key": f"{ctx.execution_id}:scenario-a-identify",
    })
    ctx.check(bool(sdk.get("canonical_entity_id")) and sdk.get("resolution_outcome") not in {"blocked", "candidate", "pending_review"},
              "later SDK identify did not safely bind to an imported canonical entity")


def _run_b(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    one = ctx.resolve("b-one", user_id=f"shared-device-one-{tag}", email=f"one-{tag}@example.invalid",
                      properties={"device_fingerprint": f"device-{tag}"})
    two = ctx.resolve("b-two", user_id=f"shared-device-two-{tag}", email=f"two-{tag}@example.invalid",
                      properties={"device_fingerprint": f"device-{tag}"})
    ctx.check(one["canonical_entity_id"] != two["canonical_entity_id"],
              "different users on a shared device were assigned one canonical entity")


def _run_c(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    left = ctx.resolve("c-left", user_id=f"repair-left-{tag}", email=f"left-{tag}@example.invalid")
    right = ctx.resolve("c-right", user_id=f"repair-right-{tag}", email=f"right-{tag}@example.invalid")
    status, raw = ctx.call("POST", "/v1/identity/merge", {
        "primary_entity_id": left["canonical_entity_id"],
        "secondary_entity_id": right["canonical_entity_id"],
        "reason": f"staging identity continuity proof {ctx.execution_id}",
    })
    merged = _data(raw)
    ctx.check(status == 200 and merged.get("decision") in {"merged", "auto_merged"},
              f"controlled test merge did not complete (HTTP {status})")
    status, raw = ctx.call("POST", "/v1/identity/split", {
        "original_entity_id": merged.get("canonical_entity_id") or left["canonical_entity_id"],
        "reason": f"repair staging identity continuity proof {ctx.execution_id}",
    })
    split = _data(raw)
    before, after = split.get("resolution_revision_before"), split.get("resolution_revision_after")
    ctx.check(status == 200 and split.get("allowed") is True and before is not None and after is not None and after > before,
              f"repair split did not complete with a graph revision change (HTTP {status})")


def _run_d(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    agent = ctx.resolve("d-agent", agent_id=f"agent-{tag}", email=f"agent-{tag}@example.invalid")
    human = ctx.resolve("d-human", user_id=f"human-{tag}", email=f"human-{tag}@example.invalid")
    ctx.check(agent["canonical_entity_id"] != human["canonical_entity_id"],
              "agent and human observations resolved to the same canonical entity")


def _run_shared_email(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    email = f"support+{tag}@example.invalid"
    first = ctx.resolve("shared-inbox-one", user_id=f"inbox-one-{tag}", email=email)
    second = ctx.resolve("shared-inbox-two", user_id=f"inbox-two-{tag}", email=email)
    status, raw = ctx.call("GET", "/v1/identity/conflicts?status=open&limit=200")
    conflicts = _data(raw).get("conflicts", [])
    ctx.check(status == 200 and isinstance(conflicts, list), f"could not read tenant conflict queue (HTTP {status})")
    ids = {first["canonical_entity_id"], second["canonical_entity_id"]}
    ctx.check(any(ids.intersection(set(row.get("candidate_entity_ids", []))) for row in conflicts if isinstance(row, dict)),
              "shared inbox identity did not produce a visible open conflict for both candidates")


def _run_cross_tenant(ctx: ScenarioContext) -> None:
    if not ctx.foreign_entity_id:
        ctx.check(False, "AETHER_STAGING_FOREIGN_ENTITY_ID is required to verify isolation against a real foreign-tenant entity")
        return
    encoded = urllib.parse.quote(ctx.foreign_entity_id, safe="")
    status, raw = ctx.call("GET", f"/v1/identity/entities/{encoded}")
    ctx.check(status in {403, 404}, f"foreign tenant entity was readable (HTTP {status})")
    ctx.check(not bool(_data(raw).get("canonical_entity_id")), "foreign entity response exposed a canonical ID")


def _run_deleted(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    email = f"suppressed-{tag}@example.invalid"
    user_id = f"suppressed-user-{tag}"
    entity = ctx.resolve("deleted-before", user_id=user_id, email=email)
    dsr = _required_data(ctx, "POST", "/v1/consent/dsr", {
        "user_id": user_id, "request_type": "erasure",
        "details": f"staging identity continuity deletion scenario {ctx.execution_id}",
    })
    job_id = dsr.get("erasure_job_id")
    ctx.check(bool(job_id), "DSR API did not return a durable erasure job")
    deadline = time.monotonic() + 300
    terminal = None
    while time.monotonic() < deadline:
        job = _required_data(ctx, "GET", f"/v1/jobs/{urllib.parse.quote(str(job_id), safe='')}")
        state = job.get("status")
        if state in {"succeeded", "completed", "failed", "dead_letter", "cancelled"}:
            terminal = state
            break
        time.sleep(2)
    ctx.check(terminal in {"succeeded", "completed"},
              "durable DSR erasure did not complete within 300 seconds")
    after = ctx.resolve("deleted-after", user_id=user_id, email=email)
    ctx.check(after.get("canonical_entity_id") != entity.get("canonical_entity_id")
              or after.get("decision") in {"blocked", "suppressed"}
              or after.get("blocked_reason") in {"suppressed_identity", "deleted_identity"},
              "erased identity was resurrected as its prior canonical entity")


def _run_multi_sdk(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    app = os.getenv("AETHER_STAGING_TENANT_APP_KEY", "")
    ctx.check(bool(app), "AETHER_STAGING_TENANT_APP_KEY is required for SDK API scenarios")
    if not app:
        return
    common = {"tenant_app_key": app, "user_id": f"multi-sdk-user-{tag}",
              "traits": {"email": f"multi-sdk-{tag}@example.invalid"}}
    outcomes = []
    for sdk in ("aether-web", "aether-ios", "aether-android"):
        anonymous_id = f"multi-sdk-anon-{tag}-{sdk}"
        _required_data(ctx, "POST", "/v1/consent/records", {
            "anonymous_id": anonymous_id, "purposes": ["analytics"], "granted": True,
            "source": "staging-identity-continuity", "mode": "opt_in",
            "idempotency_key": f"{ctx.execution_id}:multi-sdk:{sdk}:consent",
        })
        body = {**common, "anonymous_id": anonymous_id, "sdk_name": sdk,
                "idempotency_key": f"{ctx.execution_id}:{sdk}"}
        status, raw = ctx.call("POST", "/sdk/identify", body)
        data = _data(raw)
        ctx.check(status == 200, f"{sdk} identify endpoint failed (HTTP {status})")
        outcomes.append(data.get("canonical_entity_id"))
    ctx.check(all(outcomes) and len(set(outcomes)) == 1,
              "web, iOS, and Android did not bind to one canonical entity with server-authorized consent")


def _run_connector(ctx: ScenarioContext) -> None:
    connection_id = os.getenv("AETHER_STAGING_CONNECTOR_CONNECTION_ID", "")
    ctx.check(bool(connection_id), "AETHER_STAGING_CONNECTOR_CONNECTION_ID must name an isolated staging provider connection")
    if not connection_id:
        return
    encoded = urllib.parse.quote(connection_id, safe="")
    before_raw = _required_data(ctx, "GET", f"/v1/provider-connections/{encoded}/raw-records?limit=1")
    before_total = before_raw.get("total")
    ctx.check(isinstance(before_total, int), "provider API omitted its persisted raw-record count")
    first = _required_data(ctx, "POST", f"/v1/provider-connections/{encoded}/sync", {})
    second = _required_data(ctx, "POST", f"/v1/provider-connections/{encoded}/sync", {})
    first_status = first.get("status")
    second_status = second.get("status")
    ctx.check(first_status == "completed" and second_status == "completed",
              "both repeated connector syncs must complete before idempotency can be evaluated")
    ctx.check(int(second.get("records_received") or 0) > 0,
              "connector sync returned no records, so reimport idempotency was not exercised")
    after_raw = _required_data(ctx, "GET", f"/v1/provider-connections/{encoded}/raw-records?limit=1")
    ctx.check(after_raw.get("total") == before_total,
              "repeating the same connector sync changed the provider-scoped persisted raw-record count")


def _run_projection(ctx: ScenarioContext) -> None:
    tag = ctx.execution_id[:8]
    left = ctx.resolve("projection-left", user_id=f"projection-left-{tag}", email=f"projection-left-{tag}@example.invalid")
    right = ctx.resolve("projection-right", user_id=f"projection-right-{tag}", email=f"projection-right-{tag}@example.invalid")
    status, before_raw = ctx.call("GET", "/v1/admin/identity/staging-proof-capture", admin=True)
    before_capture = _data(before_raw).get("capture", {})
    before_jobs = before_capture.get("restatement_jobs", []) if isinstance(before_capture, dict) else []
    known_job_refs = {
        str(row.get("job_id")) for row in before_jobs
        if isinstance(row, dict) and row.get("job_id")
    }
    ctx.check(status == 200 and isinstance(before_jobs, list),
              f"could not capture pre-merge restatement baseline (HTTP {status})")
    status, raw = ctx.call("POST", "/v1/identity/merge", {
        "primary_entity_id": left["canonical_entity_id"],
        "secondary_entity_id": right["canonical_entity_id"],
        "reason": f"staging projection restatement proof {ctx.execution_id}",
    })
    merge = _data(raw)
    ctx.check(status == 200 and bool(merge.get("restatement_job_id"))
              and merge.get("restatement_status") in {"queued", "completed", "partially_succeeded"},
              f"merge did not enqueue projection restatement (HTTP {status})")
    expected = {
        "profile_360", "journey", "communications_360", "signals", "agent_360",
        "execution_360", "account_360", "syndicates",
    }
    flags = before_capture.get("feature_flags", {}) if isinstance(before_capture, dict) else {}
    if flags.get("campaign_restatement_enabled"):
        expected.add("campaign_360")
    if flags.get("value_restatement_enabled"):
        expected.add("value")
    deadline = time.monotonic() + 300
    observed_job = None
    while time.monotonic() < deadline:
        status, raw = ctx.call("GET", "/v1/admin/identity/staging-proof-capture", admin=True)
        capture = _data(raw).get("capture", {})
        jobs = capture.get("restatement_jobs", []) if isinstance(capture, dict) else []
        new_jobs = [
            row for row in jobs if isinstance(row, dict)
            and row.get("job_id") and str(row["job_id"]) not in known_job_refs
        ]
        if status == 200 and new_jobs:
            observed_job = new_jobs[0]
            status_by_projection = observed_job.get("projection_status") or {}
            job_state = observed_job.get("status")
            terminal = job_state in {"completed", "partially_succeeded", "unsupported", "retryable_failure", "failed"}
            complete = expected.issubset(status_by_projection) and all(
                value in {"completed", "unsupported", "failed", "retryable_failure"}
                for value in status_by_projection.values()
            )
            if terminal and complete:
                break
        time.sleep(2)
    ctx.check(observed_job is not None, "persisted tenant projection job was not visible in staging capture")
    if not observed_job:
        return
    status_by_projection = observed_job.get("projection_status") or {}
    ctx.check(expected.issubset(status_by_projection),
              "projection job omitted one or more required projection outcomes")
    ctx.check(all(status_by_projection.get(name) == "completed" for name in expected - {"syndicates"}),
              "one or more implemented identity projections did not complete successfully")
    ctx.check(status_by_projection.get("syndicates") == "unsupported",
              "syndicates must remain explicitly unsupported until an executor exists")


RUNNERS: dict[str, Callable[[ScenarioContext], None]] = dict(zip(SCENARIOS, (
    _run_a, _run_b, _run_c, _run_d, _run_shared_email, _run_cross_tenant,
    _run_deleted, _run_multi_sdk, _run_connector, _run_projection,
)))


def _artifact_bytes(scenario_id: str, execution_id: str, started_at: str, ctx: ScenarioContext,
                    outcome: str, message: str | None) -> bytes:
    artifact = {
        "schema_version": "1.0.0", "scenario_id": scenario_id,
        "execution_id": execution_id, "tenant_ref": ctx.tenant_ref or _value_ref(ctx.tenant_id),
        "started_at": started_at, "executed_at": datetime.now(timezone.utc).isoformat(),
        "outcome": outcome, "assertions_passed": ctx.assertions_passed,
        "assertions_failed": ctx.assertions_failed, "failure": message,
        "api_trace": _redact(ctx.trace),
    }
    return (json.dumps(artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def execute_scenario(ctx: ScenarioContext, scenario_id: str) -> dict[str, Any]:
    ctx.trace = []
    ctx.assertions_passed = ctx.assertions_failed = 0
    started = datetime.now(timezone.utc).isoformat()
    outcome, failure = "passed", None
    try:
        status, raw = ctx.call("GET", "/v1/identity/health")
        health = _data(raw)
        ctx.check(status == 200 and health.get("tenant_id") == ctx.tenant_id,
                  f"tenant credential health check failed or crossed tenant boundary (HTTP {status})")
        RUNNERS[scenario_id](ctx)
    except ScenarioFailure as exc:
        outcome, failure = "failed", str(exc)
        if ctx.assertions_failed == 0:
            ctx.assertions_failed = 1
    except Exception as exc:
        outcome, failure = "failed", f"runner error ({type(exc).__name__})"
        if ctx.assertions_failed == 0:
            ctx.assertions_failed = 1
    if ctx.assertions_passed == 0 and ctx.assertions_failed == 0:
        outcome, failure, ctx.assertions_failed = "failed", "scenario executed no assertions", 1
    if ctx.assertions_failed:
        outcome = "failed"
    artifact = _artifact_bytes(scenario_id, ctx.execution_id, started, ctx, outcome, failure)
    target = ctx.output_dir / f"{scenario_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError(f"refusing to overwrite prior scenario artifact: {target}")
    target.write_bytes(artifact)
    digest = hashlib.sha256(artifact).hexdigest()
    status, response = ctx.call("POST", "/v1/admin/identity/staging-proof-scenarios", {
        "execution_id": ctx.execution_id, "scenario_id": scenario_id, "outcome": outcome,
        "evidence_sha256": digest, "assertions_passed": ctx.assertions_passed,
        "assertions_failed": ctx.assertions_failed, "started_at": started,
    }, admin=True)
    if status != 200:
        raise RuntimeError(f"scenario evidence recording failed for {scenario_id} (HTTP {status}); artifact preserved at {target}")
    return {"scenario_id": scenario_id, "outcome": outcome, "assertions_passed": ctx.assertions_passed,
            "assertions_failed": ctx.assertions_failed, "evidence_sha256": digest,
            "artifact": target.name, "recorded": True, "record_response": _redact(_data(response))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("AETHER_STAGING_BASE_URL"), required=not bool(os.getenv("AETHER_STAGING_BASE_URL")))
    parser.add_argument("--api-key", default=os.getenv("AETHER_STAGING_SCENARIO_API_KEY"), required=not bool(os.getenv("AETHER_STAGING_SCENARIO_API_KEY")))
    parser.add_argument("--admin-api-key", default=os.getenv("AETHER_STAGING_ADMIN_API_KEY"),
                        help="isolated tenant admin key for scenario evidence capture and submission")
    parser.add_argument("--tenant-id", default=os.getenv("AETHER_STAGING_TENANT_ID"), required=not bool(os.getenv("AETHER_STAGING_TENANT_ID")))
    parser.add_argument("--deployment-id", default=os.getenv("AETHER_DEPLOYMENT_ID"),
                        help="optional expected deployment ID; the authenticated capture endpoint supplies the bound ID")
    parser.add_argument("--execution-id", default=os.getenv("AETHER_IDENTITY_EXECUTION_ID"), required=not bool(os.getenv("AETHER_IDENTITY_EXECUTION_ID")))
    parser.add_argument("--output-directory", default="artifacts/rehearsal/identity-continuity-scenarios")
    args = parser.parse_args(argv)
    try:
        base_url = args.base_url.rstrip("/")
        api_key, tenant_id, expected_deployment_id = args.api_key, args.tenant_id, args.deployment_id
        execution_id = str(uuid.UUID(args.execution_id))
    except (ValueError, AttributeError):
        parser.error("required identifiers must be valid single-line values")
    if any(not value or any(c in value for c in "\r\n\x00") for value in (base_url, api_key, tenant_id)):
        parser.error("base URL, API key, and tenant ID must be non-empty single-line values")
    if expected_deployment_id and any(c in expected_deployment_id for c in "\r\n\x00"):
        parser.error("deployment ID must be single-line")
    if not base_url.startswith("https://") and not base_url.startswith("http://localhost") and not base_url.startswith("http://127.0.0.1"):
        parser.error("base URL must use HTTPS outside localhost")
    output_dir = Path(args.output_directory).resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        parser.error(f"output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    admin_api_key = args.admin_api_key
    if not admin_api_key or any(c in admin_api_key for c in "\r\n\x00"):
        parser.error("AETHER_STAGING_ADMIN_API_KEY must be a non-empty single-line tenant admin key")
    ctx = ScenarioContext(base_url, api_key, tenant_id, execution_id, output_dir,
                          admin_api_key=admin_api_key,
                          foreign_entity_id=os.getenv("AETHER_STAGING_FOREIGN_ENTITY_ID"))
    try:
        status, raw = ctx.call("GET", "/v1/admin/identity/staging-proof-capture", admin=True)
        data = _data(raw)
        if status != 200 or data.get("environment") != "staging":
            raise RuntimeError("endpoint did not confirm staging")
        deployment_id = data.get("deployment_id")
        if not isinstance(deployment_id, str) or not deployment_id:
            raise RuntimeError("capture omitted deployment ID")
        if expected_deployment_id and deployment_id != expected_deployment_id:
            raise RuntimeError("API key is bound to a different deployment")
        tenant_ref = data.get("capture", {}).get("tenant_ref")
        if not isinstance(tenant_ref, str) or not tenant_ref:
            raise RuntimeError("capture omitted tenant binding")
        ctx.tenant_ref = tenant_ref
        status, raw = ctx.call("GET", "/v1/identity/health")
        health = _data(raw)
        if status != 200 or health.get("tenant_id") != tenant_id:
            raise RuntimeError("API credential is not bound to the requested tenant")
    except Exception as exc:
        print(f"staging scenario preflight failed: {exc}", file=sys.stderr)
        return 2

    results = []
    for scenario_id in SCENARIOS:
        try:
            results.append(execute_scenario(ctx, scenario_id))
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            results.append({"scenario_id": scenario_id, "outcome": "unrecorded", "error": str(exc)})
            break
    summary = {"schema_version": "1.0.0", "execution_id": execution_id,
               "deployment_id": deployment_id,
               "tenant_ref": ctx.tenant_ref or _value_ref(tenant_id),
               "results": results, "complete": len(results) == len(SCENARIOS) and all(r.get("recorded") for r in results)}
    summary_path = output_dir / "run-summary.json"
    if summary_path.exists():
        print(f"refusing to overwrite prior run summary: {summary_path}", file=sys.stderr)
        return 2
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    failed = [row["scenario_id"] for row in results if row.get("outcome") != "passed" or not row.get("recorded")]
    print(f"recorded {len(results)}/{len(SCENARIOS)} identity scenarios; artifacts: {output_dir}")
    if failed or len(results) != len(SCENARIOS):
        print("failed or unrecorded scenarios: " + ", ".join(failed or SCENARIOS[len(results):]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
