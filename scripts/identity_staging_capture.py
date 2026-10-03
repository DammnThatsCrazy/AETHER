#!/usr/bin/env python3
"""Fetch tenant-authenticated live staging evidence into a proof-pack manifest.

This is read-only. It never seeds data, executes identity actions, or turns
missing scenario execution records into passing results. The downstream
proof-reporting collector remains the authority that emits or rejects a pack.
"""
from __future__ import annotations

import argparse
import shutil
import json
import os
import re
import sys
from urllib.parse import urlsplit
import urllib.error
import urllib.request
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "services/backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from services.identity.contract_inventory import REQUIRED_STAGING_IDENTITY_FLAGS  # noqa: E402


def _call_capture(base_url: str, api_key: str) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/admin/identity/staging-proof-capture",
        headers={"Accept": "application/json", "X-API-Key": api_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError(f"staging capture endpoint returned HTTP {response.status}")
            payload = json.loads(response.read())
    except urllib.error.HTTPError as error:
        # Do not print a response body: auth middleware can include sensitive
        # tenant diagnostics, and the status is enough to identify the blocker.
        raise RuntimeError(f"staging capture endpoint returned HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError(f"staging capture endpoint unavailable or invalid: {type(error).__name__}") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or data.get("environment") != "staging":
        raise RuntimeError("capture endpoint did not confirm the staging environment")
    if not isinstance(data.get("capture"), dict):
        raise RuntimeError("capture endpoint returned no persisted identity capture")
    if not data.get("deployment_id") or not data.get("observed_at"):
        raise RuntimeError("capture endpoint omitted deployment identity or observation time")
    return data


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _graph_versions(capture: dict[str, Any], evidence_id: str) -> list[dict[str, str]]:
    tenant_ref = capture.get("tenant_ref")
    transitions: list[dict[str, str]] = []
    for kind in ("merges", "splits"):
        for row in capture.get(kind, []):
            before = row.get("resolution_revision_before")
            after = row.get("resolution_revision_after")
            if before is None or after is None or str(before) == str(after):
                continue
            transitions.append({
                "tenant_id": str(tenant_ref),
                "graph": "identity_resolution_revision",
                "before": str(before),
                "after": str(after),
                "observed_at": str(row.get("created_at") or capture.get("captured_at") or ""),
                "evidence_id": evidence_id,
            })
    for row in capture.get("restatement_jobs", []):
        if not isinstance(row, dict):
            continue
        before = row.get("source_graph_version")
        after = row.get("resulting_graph_version")
        if before is None or after is None or str(before) == str(after):
            continue
        transitions.append({
            "tenant_id": str(tenant_ref),
            "graph": "canonical_graph_version",
            "before": str(before),
            "after": str(after),
            "observed_at": str(row.get("completed_at") or capture.get("captured_at") or ""),
            "evidence_id": evidence_id,
        })
    return transitions


def _projection_job_records(jobs: list[Any], tenant_ref: str, evidence_id: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for row in jobs:
        if not isinstance(row, dict):
            continue
        statuses = row.get("projection_status")
        if not isinstance(statuses, dict):
            evidence = row.get("projection_results")
            statuses = {
                name: result.get("status", "pending")
                for name, result in evidence.items()
                if isinstance(evidence, dict) and isinstance(name, str) and isinstance(result, dict)
            } if isinstance(evidence, dict) else {}
        for projection, status in statuses.items():
            if not isinstance(projection, str) or not isinstance(status, str):
                continue
            normalized_status = "succeeded" if status in {"completed", "succeeded"} else (
                "failed" if status in {"failed", "retryable_failure", "unsupported"} else "pending"
            )
            records.append({
                "tenant_id": tenant_ref,
                "job_id": str(row.get("job_id", "")),
                "status": normalized_status,
                "projection": projection,
                "source_graph_version": str(row.get("source_graph_version") or ""),
                "resulting_graph_version": str(row.get("resulting_graph_version") or ""),
                "completed_at": str(row.get("completed_at") or ""),
                "evidence_id": evidence_id,
            })
    return records


def _bind_scenario_artifacts(
    data: dict[str, Any], scenario_directory: Path, capture_root: Path,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Join local exact-byte artifacts to the latest durable server execution."""
    summary_path = scenario_directory / "run-summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("live scenario run summary is missing or invalid") from None
    if not isinstance(summary, dict) or summary.get("complete") is not True:
        raise RuntimeError("live scenario run is incomplete or has unrecorded results")
    capture = data.get("capture") or {}
    deployment_id = data.get("deployment_id")
    tenant_ref = capture.get("tenant_ref")
    if summary.get("deployment_id") != deployment_id:
        raise RuntimeError("scenario run is bound to a different staging deployment")
    if not isinstance(tenant_ref, str) or not tenant_ref or summary.get("tenant_ref") != tenant_ref:
        raise RuntimeError("scenario run is bound to a different tenant reference")
    execution_id = summary.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise RuntimeError("scenario run summary omitted its execution ID")

    local_results = summary.get("results")
    durable_rows = capture.get("scenario_results")
    if not isinstance(local_results, list) or not isinstance(durable_rows, list) or not local_results or not durable_rows:
        raise RuntimeError("local and durable scenario results are both required")
    local_by_id = {
        row.get("scenario_id"): row for row in local_results
        if isinstance(row, dict) and isinstance(row.get("scenario_id"), str)
    }
    durable_by_id = {
        row.get("id"): row for row in durable_rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if len(local_by_id) != len(local_results) or len(durable_by_id) != len(durable_rows):
        raise RuntimeError("scenario run contains duplicate or malformed result IDs")
    if set(local_by_id) != set(durable_by_id):
        raise RuntimeError("local scenario artifacts do not match the latest durable execution batch")
    execution_refs = {row.get("execution_ref") for row in durable_rows if isinstance(row, dict)}
    if len(execution_refs) != 1 or not next(iter(execution_refs), None):
        raise RuntimeError("durable scenario rows do not share one execution binding")

    resolved_directory = scenario_directory.resolve(strict=True)
    try:
        resolved_directory.relative_to(capture_root.resolve(strict=True))
    except ValueError:
        raise RuntimeError("scenario artifact directory must be inside the capture directory") from None
    artifacts: list[dict[str, str]] = []
    for scenario_id in sorted(local_by_id):
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", scenario_id):
            raise RuntimeError("scenario ID is not a safe artifact name")
        local = local_by_id[scenario_id]
        durable = durable_by_id[scenario_id]
        if (
            local.get("recorded") is not True
            or local.get("outcome") != durable.get("status")
            or local.get("evidence_sha256") != durable.get("evidence_sha256")
            or local.get("assertions_passed") != durable.get("assertions_passed")
            or local.get("assertions_failed") != durable.get("assertions_failed")
        ):
            raise RuntimeError(f"scenario {scenario_id} differs from its durable staging record")
        filename = f"{scenario_id}.json"
        artifact_path = resolved_directory / filename
        try:
            artifact_path.resolve(strict=True).relative_to(resolved_directory)
        except (OSError, ValueError):
            raise RuntimeError(f"scenario artifact is missing or escapes its run directory: {scenario_id}") from None
        raw_bytes = artifact_path.read_bytes()
        digest = sha256(raw_bytes).hexdigest()
        if digest != durable.get("evidence_sha256"):
            raise RuntimeError(f"scenario {scenario_id} exact-byte digest does not match durable staging evidence")
        try:
            artifact = json.loads(raw_bytes)
        except ValueError:
            raise RuntimeError(f"scenario {scenario_id} artifact is not valid JSON") from None
        if not isinstance(artifact, dict) or any((
            artifact.get("scenario_id") != scenario_id,
            artifact.get("execution_id") != execution_id,
            artifact.get("tenant_ref") != tenant_ref,
            artifact.get("outcome") != durable.get("status"),
            artifact.get("assertions_passed") != durable.get("assertions_passed"),
            artifact.get("assertions_failed") != durable.get("assertions_failed"),
        )):
            raise RuntimeError(f"scenario {scenario_id} artifact identity does not match the durable run")
        relative_path = artifact_path.relative_to(capture_root.resolve()).as_posix()
        artifacts.append({"scenario_id": scenario_id, "path": relative_path})

    scenario_run = {
        "execution_id": execution_id,
        "tenant_ref": tenant_ref,
        "deployment_id": str(deployment_id),
    }
    return scenario_run, artifacts


def _bind_ui_fixture_evidence(ui_directory: Path | None, capture_root: Path) -> list[dict[str, Any]]:
    """Copy Playwright artifacts into the capture root with explicit mock-only provenance."""
    if ui_directory is None:
        return []
    if not ui_directory.exists():
        return []
    root = ui_directory.resolve(strict=True)
    capture_root.mkdir(parents=True, exist_ok=True)
    capture_real = capture_root.resolve(strict=True)
    index_paths = sorted({*root.rglob("manifest.json"), *root.rglob("*-manifest.json")})
    if not index_paths:
        return []
    target = capture_real / "ui-fixture-evidence"
    target.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for manifest_path in index_paths:
        try:
            manifest_real = manifest_path.resolve(strict=True)
            manifest_real.relative_to(root)
            metadata = json.loads(manifest_real.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("Playwright UI evidence manifest is missing, invalid, or escapes its selected directory") from None
        if not isinstance(metadata, dict) or any((
            metadata.get("schema_version") != "aether.identity-ui-evidence-manifest.v1",
            metadata.get("evidence_class") != "ui_fixture_only",
            metadata.get("api_mode") != "playwright_route_fixture",
        )):
            raise RuntimeError("UI evidence must declare fixture-only Playwright API provenance")
        test_id = metadata.get("test_id")
        surface = metadata.get("surface")
        tenant_ref = metadata.get("tenant_ref")
        captured_at = metadata.get("captured_at")
        files = metadata.get("files")
        if not isinstance(test_id, str) or not test_id or surface not in {"activation", "review_queue", "profile_360"}:
            raise RuntimeError("UI evidence must bind a test ID and known identity surface")
        if not isinstance(tenant_ref, str) or not tenant_ref.startswith("tenant_identity_e2e_"):
            raise RuntimeError("UI fixture tenant reference is not marked as synthetic")
        if not isinstance(captured_at, str) or not captured_at:
            raise RuntimeError("UI evidence omitted its capture timestamp")
        if not isinstance(files, dict) or not all(isinstance(files.get(kind), str) for kind in ("screenshot", "structured")):
            raise RuntimeError("UI evidence must reference screenshot and structured artifacts")
        resolved_sources: dict[str, Path] = {}
        for kind in ("screenshot", "structured"):
            source_candidate = manifest_real.parent / files[kind]
            if source_candidate.is_symlink():
                raise RuntimeError(f"UI {kind} artifact is a symlink")
            candidate = source_candidate.resolve(strict=True)
            try:
                candidate.relative_to(root)
            except ValueError:
                raise RuntimeError("UI evidence artifact escapes the selected evidence directory") from None
            if candidate.stat().st_size > (5 * 1024 * 1024 if kind == "screenshot" else 512 * 1024):
                raise RuntimeError(f"UI {kind} artifact exceeds the size limit")
            resolved_sources[kind] = candidate
        try:
            observations = json.loads(resolved_sources["structured"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("structured UI evidence is unreadable JSON") from None
        if not isinstance(observations, dict) or any((
            observations.get("schema_version") != "aether.identity-ui-evidence.v1",
            observations.get("evidence_class") != "ui_fixture_only",
            observations.get("api_mode") != "playwright_route_fixture",
            observations.get("live_staging_claim") is not False,
            observations.get("test_id") != test_id,
            observations.get("surface") != surface,
            observations.get("tenant_ref") != tenant_ref,
        )):
            raise RuntimeError("structured UI artifact does not match its fixture-only manifest")
        item_id = sha256(f"{surface}\0{test_id}\0{tenant_ref}".encode()).hexdigest()[:20]
        if item_id in seen:
            raise RuntimeError("duplicate Playwright UI test evidence identity")
        seen.add(item_id)
        copied: dict[str, str] = {}
        digests: dict[str, str] = {}
        for kind, source in resolved_sources.items():
            suffix = ".png" if kind == "screenshot" else ".json"
            filename = f"{item_id}-{kind}{suffix}"
            destination = target / filename
            if destination.exists():
                raise RuntimeError("UI evidence output collision; use a fresh capture directory")
            shutil.copyfile(source, destination)
            copied[kind] = destination.relative_to(capture_real).as_posix()
            digests[kind] = sha256(destination.read_bytes()).hexdigest()
        if not resolved_sources["screenshot"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("UI screenshot artifact is not a PNG")
        results.append({
            "id": item_id,
            "surface": surface,
            "test_id": test_id,
            "tenant_ref": tenant_ref,
            "evidence_class": "ui_fixture_only",
            "api_mode": "playwright_route_fixture",
            "live_staging_claim": False,
            "captured_at": captured_at,
            "structured_path": copied["structured"],
            "structured_sha256": digests["structured"],
            "screenshot_path": copied["screenshot"],
            "screenshot_sha256": digests["screenshot"],
        })
    return results


def _bind_ui_live_evidence(
    ui_directory: Path | None, capture_root: Path, *,
    deployment_id: str, tenant_ref: str, api_base_url: str,
) -> list[dict[str, Any]]:
    """Bind authenticated production-UI observations to this exact staging run."""
    if ui_directory is None:
        return []
    if not ui_directory.exists():
        raise RuntimeError("live UI evidence directory is missing; staging UI proof cannot be inferred")
    root = ui_directory.resolve(strict=True)
    capture_root.mkdir(parents=True, exist_ok=True)
    capture_real = capture_root.resolve(strict=True)
    target = capture_real / "ui-live-evidence"
    target.mkdir(parents=True, exist_ok=True)
    expected_api_origin = urlsplit(api_base_url).scheme + "://" + urlsplit(api_base_url).netloc
    if urlsplit(api_base_url).scheme != "https" or not urlsplit(api_base_url).netloc:
        raise RuntimeError("live UI evidence requires an HTTPS staging API origin")
    paths = sorted(root.rglob("*-manifest.json"))
    if not paths:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for manifest_path in paths:
        try:
            manifest_real = manifest_path.resolve(strict=True)
            manifest_real.relative_to(root)
            metadata = json.loads(manifest_real.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("live UI evidence manifest is missing, invalid, or escapes its selected directory") from None
        if not isinstance(metadata, dict) or any((
            metadata.get("schema_version") != "aether.identity-ui-live-evidence-manifest.v1",
            metadata.get("evidence_class") != "ui_live_staging",
            metadata.get("api_mode") != "authenticated_real_backend",
            metadata.get("tenant_ref") != tenant_ref,
            metadata.get("deployment_id") != deployment_id,
        )):
            raise RuntimeError("live UI evidence does not match the authenticated staging tenant and deployment")
        evidence_id = metadata.get("id")
        surface = metadata.get("surface")
        test_id = metadata.get("test_id")
        captured_at = metadata.get("captured_at")
        files = metadata.get("files")
        if not isinstance(evidence_id, str) or not re.fullmatch(r"[0-9a-f]{24}", evidence_id):
            raise RuntimeError("live UI evidence ID is invalid")
        if evidence_id in seen:
            raise RuntimeError("duplicate live UI evidence ID")
        seen.add(evidence_id)
        if surface not in {"activation", "review_queue"} or not isinstance(test_id, str) or not test_id:
            raise RuntimeError("live UI evidence must identify an activation or review queue test")
        try:
            parsed_captured_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00")) if isinstance(captured_at, str) else None
        except ValueError:
            parsed_captured_at = None
        if parsed_captured_at is None or parsed_captured_at.tzinfo is None:
            raise RuntimeError("live UI evidence omitted a valid capture timestamp")
        if not isinstance(files, dict) or not all(isinstance(files.get(kind), str) for kind in ("screenshot", "structured")):
            raise RuntimeError("live UI evidence must reference screenshot and structured artifacts")
        sources: dict[str, Path] = {}
        for kind in ("screenshot", "structured"):
            candidate_source = manifest_real.parent / files[kind]
            if candidate_source.is_symlink():
                raise RuntimeError(f"live UI {kind} artifact is a symlink")
            resolved = candidate_source.resolve(strict=True)
            try:
                resolved.relative_to(root)
            except ValueError:
                raise RuntimeError("live UI evidence artifact escapes the selected directory") from None
            if resolved.stat().st_size > (5 * 1024 * 1024 if kind == "screenshot" else 512 * 1024):
                raise RuntimeError(f"live UI {kind} artifact exceeds its size limit")
            sources[kind] = resolved
        try:
            observations = json.loads(sources["structured"].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RuntimeError("live UI structured evidence is unreadable JSON") from None
        if not isinstance(observations, dict) or any((
            observations.get("schema_version") != "aether.identity-ui-evidence.v2",
            observations.get("evidence_class") != "ui_live_staging",
            observations.get("api_mode") != "authenticated_real_backend",
            observations.get("live_staging_claim") is not True,
            observations.get("deployment_id") != deployment_id,
            observations.get("tenant_ref") != tenant_ref,
            observations.get("test_id") != test_id,
            observations.get("surface") != surface,
        )):
            raise RuntimeError("live UI structured evidence does not match its run manifest")
        page_origin = urlsplit(str(observations.get("page_origin") or ""))
        api_origin = urlsplit(str(observations.get("api_origin") or ""))
        if page_origin.scheme != "https" or not page_origin.netloc or api_origin.scheme != "https" or (api_origin.scheme + "://" + api_origin.netloc) != expected_api_origin:
            raise RuntimeError("live UI evidence origins do not match HTTPS staging application and API origins")
        api_observations = observations.get("api_observations")
        expected_routes = {
            "activation": {"/v1/me", "/v1/capabilities", "/v1/admin/identity/activation-status"},
            "review_queue": {"/v1/me", "/v1/capabilities", "/v1/admin/identity/review-queue"},
        }[surface]
        if not isinstance(api_observations, list):
            raise RuntimeError("live UI evidence omitted authenticated API observations")
        successful_routes = {
            row.get("path") for row in api_observations
            if isinstance(row, dict) and isinstance(row.get("status"), int)
            and 200 <= row["status"] < 300
        }
        if not expected_routes.issubset(successful_routes):
            raise RuntimeError("live UI evidence is missing successful real-backend identity API responses")
        copied: dict[str, str] = {}
        digests: dict[str, str] = {}
        for kind, source in sources.items():
            suffix = ".png" if kind == "screenshot" else ".json"
            destination = target / f"{evidence_id}-{kind}{suffix}"
            if destination.exists():
                raise RuntimeError("live UI evidence output collision; use a fresh capture directory")
            shutil.copyfile(source, destination)
            copied[kind] = destination.relative_to(capture_real).as_posix()
            digests[kind] = sha256(destination.read_bytes()).hexdigest()
        if not sources["screenshot"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("live UI screenshot artifact is not a PNG")
        results.append({
            "id": evidence_id, "surface": surface, "test_id": test_id,
            "tenant_ref": tenant_ref, "deployment_id": deployment_id,
            "evidence_class": "ui_live_staging", "api_mode": "authenticated_real_backend",
            "live_staging_claim": True, "captured_at": captured_at,
            "structured_path": copied["structured"], "structured_sha256": digests["structured"],
            "screenshot_path": copied["screenshot"], "screenshot_sha256": digests["screenshot"],
        })
    if {item["surface"] for item in results} != {"activation", "review_queue"}:
        raise RuntimeError("live UI evidence must include both activation and review_queue surfaces")
    return results


def build_manifest(
    data: dict[str, Any], *, commit_sha: str, branch: str,
    scenario_run: dict[str, str] | None = None,
    scenario_artifacts: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    capture = data["capture"]
    evidence_ids = {
        "contract_inventory": "identity-contract-inventory",
        "scenario_result": "identity-scenario-results",
        "graph_versions": "identity-graph-versions",
        "restatement_job": "identity-restatement-jobs",
        "projection_outcome": "identity-projection-outcomes",
        "feature_flags": "identity-feature-flags",
    }
    contracts = capture.get("contract_inventory") or {}
    scenarios = capture.get("scenario_results") or []
    jobs = capture.get("restatement_jobs") or []
    graph_versions = _graph_versions(capture, evidence_ids["graph_versions"])
    projections = capture.get("projection_outcomes") or []
    flags = capture.get("feature_flags") or {}
    now = datetime.now(timezone.utc).isoformat()
    proof_id = "staging-" + sha256(
        f"{data['deployment_id']}\0{capture.get('tenant_ref','')}\0{now}".encode()
    ).hexdigest()[:24]
    evidence_payloads = {
        "contract_inventory": contracts,
        "scenario_result": {"scenarios": scenarios, "api_metrics": (capture.get("evidence") or {}).get("api_metrics", {})},
        "graph_versions": {"graph_versions": graph_versions, "merge_events": capture.get("merges", []), "split_events": capture.get("splits", [])},
        "restatement_job": {"restatement_jobs": jobs},
        "projection_outcome": {"projection_outcomes": projections},
        "feature_flags": {"values": flags},
    }
    sources = []
    for kind, evidence_id in evidence_ids.items():
        sources.append({"id": evidence_id, "kind": kind, "path": f"identity-evidence/{kind}.json"})

    manifest = {
        "schema_version": "1.0.0",
        "proof_id": proof_id,
        "generated_at": now,
        "commit": {"sha": commit_sha, "branch": branch},
        "environment": {"name": "staging", "deployment_id": data["deployment_id"], "observed_at": data["observed_at"]},
        "scenario_run": scenario_run or {},
        "scenario_artifacts": scenario_artifacts or [],
        "evidence_sources": sources,
        "contract_inventory": {
            "evidence_id": evidence_ids["contract_inventory"],
            "required_contract_ids": contracts.get("required_contract_ids", []),
            "observed_contract_ids": contracts.get("observed_contract_ids", []),
        },
        "scenarios": [
            {
                "id": row["id"], "status": row.get("status", "skipped"),
                "evidence_id": evidence_ids["scenario_result"],
                "artifact_evidence_id": f"scenario-artifact-{row['id']}",
                "evidence_sha256": row.get("evidence_sha256", ""),
                "execution_ref": row.get("execution_ref", ""),
                "executed_at": row.get("executed_at", ""),
            }
            for row in scenarios if isinstance(row, dict) and isinstance(row.get("id"), str)
        ],
        "graph_versions": graph_versions,
        "restatement_jobs": _projection_job_records(
            jobs, str(capture.get("tenant_ref", "")), evidence_ids["restatement_job"]
        ),
        "projection_outcomes": [
            {"projection": row.get("projection"), "status": row.get("status"), "evidence_id": evidence_ids["projection_outcome"]}
            for row in projections if isinstance(row, dict)
        ],
        "feature_flags": {
            "evidence_id": evidence_ids["feature_flags"],
            "values": flags,
            "required_enabled": list(REQUIRED_STAGING_IDENTITY_FLAGS),
        },
    }
    return manifest, evidence_payloads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("AETHER_STAGING_BASE_URL"))
    parser.add_argument("--api-key", default=os.getenv("AETHER_STAGING_CAPTURE_API_KEY"))
    parser.add_argument("--output", default="artifacts/rehearsal/identity-continuity-capture.json")
    parser.add_argument("--scenario-artifacts-directory", default="artifacts/rehearsal/identity-continuity-scenarios")
    parser.add_argument("--ui-evidence-directory", help="Optional Playwright UI fixture evidence root to bind as supplemental evidence")
    parser.add_argument("--ui-live-evidence-directory", help="Authenticated live staging UI evidence root; both identity surfaces are required")
    parser.add_argument("--commit-sha", default=os.getenv("GITHUB_SHA"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "staging"))
    args = parser.parse_args()
    if not args.base_url or not args.api_key:
        parser.error("--base-url and --api-key (or their environment variables) are required")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", args.commit_sha or ""):
        parser.error("--commit-sha or GITHUB_SHA must be a full commit SHA")
    if not args.branch or any(char in args.branch for char in "\r\n"):
        parser.error("--branch must be a non-empty single-line branch name")
    output = Path(args.output).resolve()
    try:
        data = _call_capture(args.base_url, args.api_key)
        output = Path(args.output).resolve()
        scenario_run, scenario_artifacts = _bind_scenario_artifacts(
            data, Path(args.scenario_artifacts_directory), output.parent
        )
        manifest, evidence = build_manifest(
            data, commit_sha=args.commit_sha, branch=args.branch,
            scenario_run=scenario_run, scenario_artifacts=scenario_artifacts,
        )
        ui_evidence = _bind_ui_fixture_evidence(
            Path(args.ui_evidence_directory) if args.ui_evidence_directory else None,
            output.parent,
        )
        ui_evidence.extend(_bind_ui_live_evidence(
            Path(args.ui_live_evidence_directory) if args.ui_live_evidence_directory else None,
            output.parent,
            deployment_id=str(data["deployment_id"]),
            tenant_ref=str(data["capture"].get("tenant_ref") or ""),
            api_base_url=args.base_url,
        ))
        if ui_evidence:
            manifest["ui_evidence"] = ui_evidence
        # An existing output is treated as a run collision; never overwrite prior evidence.
        if output.exists():
            raise RuntimeError(f"capture output already exists: {output}")
        for filename, value in evidence.items():
            _write_json(output.parent / "identity-evidence" / f"{filename}.json", value)
        _write_json(output, manifest)
    except (OSError, RuntimeError) as error:
        print(f"identity staging capture failed: {error}", file=sys.stderr)
        return 1
    print(f"captured tenant-scoped staging state to {output}")
    if not manifest["scenarios"]:
        print("scenario execution evidence is absent; downstream proof collection must fail closed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
