#!/usr/bin/env python3
"""Adapt and verify the hosted release manifest as a canonical ReleaseCandidate.

The hosted build already produces ``release.json``.  This adapter gives that
manifest the same candidate identity used by local staging and promotion,
while retaining the manifest checksum as the workflow's transport envelope.
It never deploys or contacts AWS.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.artifact_builder import aggregate_digest, digest_file
from scripts.delivery_contracts import DeploymentImpact, validate_release_candidate
from scripts.release.release_manifest import validate as validate_manifest


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _file_artifacts(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("aether_spa", "kyber_spa", "migration_package", "configuration"):
        artifact = manifest["artifacts"][name]
        path = Path(artifact["file"])
        if not path.is_file():
            raise ValueError(f"manifest artifact {name} is not a file: {path}")
        actual = digest_file(path)
        if actual != artifact["digest"]:
            raise ValueError(f"manifest artifact {name} digest does not match its file")
        result[name] = actual
    backend_digest = manifest["artifacts"]["backend_image"]["digest"]
    if not isinstance(backend_digest, str) or not backend_digest.startswith("sha256:"):
        raise ValueError("manifest backend image digest is invalid")
    result["backend_image"] = backend_digest
    return result


def _lock_artifacts(lockfiles: list[Path]) -> dict[str, str]:
    result = {}
    for path in sorted(lockfiles, key=lambda item: str(item)):
        if not path.is_file():
            raise ValueError(f"lockfile is not a file: {path}")
        result[str(path)] = digest_file(path)
    return result


def build_candidate(manifest_path: Path, lockfiles: list[Path]) -> dict[str, Any]:
    manifest = _load(manifest_path)
    validate_manifest(manifest, expected_sha=manifest.get("commit_sha"))
    components = _file_artifacts(manifest)
    locks = _lock_artifacts(lockfiles)
    profile = manifest["profile"]
    candidate = {
        "schema_version": 1,
        "release_candidate_id": f"release-{manifest['workflow_run_id']}",
        "commit_sha": manifest["commit_sha"],
        "artifact_digest": aggregate_digest(components),
        "dependency_lock_hash": aggregate_digest(locks),
        "dependency_lock_digests": locks,
        "contract_versions": {},
        "migration_version": "release-manifest",
        "model_versions": {},
        "policy_versions": {},
        "deployment_profiles": [profile],
        "affected_domains": ["backend", "frontend", "infrastructure"],
        "required_checks": ["canonical-consistency", "release-manifest"],
        "component_digests": components,
        "deployment_impact": DeploymentImpact.for_candidate(
            profile=profile,
            components=sorted(components),
            affected_domains=["backend", "frontend", "infrastructure"],
            migration_version="release-manifest",
            risk_level="high",
            approval_required=profile.startswith("production"),
        ).as_dict(),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    errors = validate_release_candidate(candidate)
    if errors:
        raise ValueError("adapted release candidate is invalid: " + "; ".join(errors))
    return candidate


def verify(manifest_path: Path, candidate_path: Path, lockfiles: list[Path], expected_sha: str | None) -> dict[str, Any]:
    manifest = _load(manifest_path)
    validate_manifest(manifest, expected_sha=expected_sha or manifest.get("commit_sha"))
    candidate = _load(candidate_path)
    errors = validate_release_candidate(candidate)
    if errors:
        raise ValueError("release candidate is invalid: " + "; ".join(errors))
    expected = build_candidate(manifest_path, lockfiles)
    immutable = {key: value for key, value in expected.items() if key != "created_at"}
    actual = {key: value for key, value in candidate.items() if key != "created_at"}
    if actual != immutable:
        raise ValueError("release candidate does not match the verified release manifest")
    if expected_sha and candidate["commit_sha"] != expected_sha:
        raise ValueError("release candidate commit does not match checked-out commit")
    return candidate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--lockfile", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-sha")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            if not args.candidate:
                parser.error("--candidate is required with --verify")
            result = verify(args.manifest, args.candidate, args.lockfile, args.expected_sha)
            print(json.dumps({"status": "PASS", "release_candidate_id": result["release_candidate_id"], "artifact_digest": result["artifact_digest"]}))
            return 0
        result = build_candidate(args.manifest, args.lockfile)
        output = args.output or args.candidate
        if output is None:
            parser.error("--output is required when creating a candidate")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": "PASS", "release_candidate_id": result["release_candidate_id"], "artifact_digest": result["artifact_digest"], "output": str(output)}))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
