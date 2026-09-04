#!/usr/bin/env python3
"""Build immutable ReleaseCandidate metadata from already-built components."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path


def digest_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def aggregate_digest(components: dict[str, str]) -> str:
    payload = json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def write_once(path: Path, candidate: dict) -> None:
    encoded = json.dumps(candidate, indent=2, sort_keys=True) + "\n"
    if path.exists():
        existing = json.loads(path.read_text())
        # created_at is observational; all identity-bearing fields are immutable.
        if {k: v for k, v in existing.items() if k != "created_at"} != {
            k: v for k, v in candidate.items() if k != "created_at"
        }:
            raise ValueError(f"refusing to replace immutable candidate {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded)


def verify_candidate(
    candidate_path: Path,
    components: list[str],
    lockfiles: list[str],
    expected_commit: str | None,
) -> dict:
    candidate = json.loads(candidate_path.read_text())
    actual: dict[str, str] = {}
    for item in components:
        name, separator, raw_path = item.partition("=")
        if not separator or not name or name in actual:
            raise ValueError(f"invalid or duplicate component: {item}")
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f"component is not a file: {path}")
        actual[name] = digest_file(path)
    if actual != candidate.get("component_digests"):
        raise ValueError("component digests do not match immutable candidate")
    if aggregate_digest(actual) != candidate.get("artifact_digest"):
        raise ValueError("aggregate artifact digest does not match immutable candidate")
    lock_digests = {str(Path(path)): digest_file(Path(path)) for path in sorted(lockfiles)}
    if aggregate_digest(lock_digests) != candidate.get("dependency_lock_hash"):
        raise ValueError("dependency lock hash does not match immutable candidate")
    if expected_commit and candidate.get("commit_sha") != expected_commit:
        raise ValueError("candidate commit does not match checked-out commit")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id")
    parser.add_argument("--component", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--lockfile", action="append", default=[])
    parser.add_argument("--profile", action="append", default=[])
    parser.add_argument("--affected-domain", action="append", default=[])
    parser.add_argument("--required-check", action="append", default=[])
    parser.add_argument("--migration-version", default="none")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true", help="verify an existing candidate instead of creating it")
    parser.add_argument("--expected-commit")
    args = parser.parse_args()
    if args.verify:
        try:
            candidate = verify_candidate(args.output, args.component, args.lockfile, args.expected_commit)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        print(json.dumps({"status": "PASS", "artifact_digest": candidate["artifact_digest"], "output": str(args.output)}))
        return 0
    if not args.candidate_id or not args.profile:
        parser.error("--candidate-id and at least one --profile are required when creating a candidate")
    components: dict[str, str] = {}
    for item in args.component:
        name, separator, raw_path = item.partition("=")
        if not separator or not name or name in components:
            parser.error(f"invalid or duplicate component: {item}")
        path = Path(raw_path)
        if not path.is_file():
            parser.error(f"component is not a file: {path}")
        components[name] = digest_file(path)
    if not components:
        parser.error("at least one --component is required")
    lock_digests = {str(Path(p)): digest_file(Path(p)) for p in sorted(args.lockfile)}
    candidate = {
        "schema_version": 1,
        "release_candidate_id": args.candidate_id,
        "commit_sha": git_sha(),
        "artifact_digest": aggregate_digest(components),
        "dependency_lock_hash": aggregate_digest(lock_digests),
        "contract_versions": {}, "migration_version": args.migration_version,
        "model_versions": {}, "policy_versions": {},
        "deployment_profiles": sorted(set(args.profile)),
        "affected_domains": sorted(set(args.affected_domain)),
        "required_checks": sorted(set(args.required_check)),
        "component_digests": components,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_once(args.output, candidate)
    print(json.dumps({"status": "PASS", "artifact_digest": candidate["artifact_digest"], "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
