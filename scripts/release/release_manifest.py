#!/usr/bin/env python3
"""Create and verify immutable, commit-bound deployment manifests."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def canonical(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode()


def validate(data: dict, expected_sha: str | None = None) -> None:
    required = {"schema_version", "commit_sha", "workflow_run_id", "profile", "artifacts"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"manifest missing fields: {sorted(missing)}")
    if expected_sha and data["commit_sha"] != expected_sha:
        raise ValueError("manifest commit does not match approved commit")
    if data["profile"] not in {"staging", "production-lean", "production-scale", "enterprise-isolated"}:
        raise ValueError("invalid deployment profile")
    artifacts = data["artifacts"]
    for name in ("backend_image", "aether_spa", "kyber_spa", "migration_package", "configuration"):
        if name not in artifacts:
            raise ValueError(f"missing artifact: {name}")
        digest = artifacts[name].get("digest", "")
        if not DIGEST.fullmatch(digest):
            raise ValueError(f"artifact {name} has invalid digest")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("manifest", type=Path)
    p.add_argument("--expected-sha")
    p.add_argument("--checksum")
    p.add_argument("--write-checksum", action="store_true")
    args = p.parse_args()
    data = json.loads(args.manifest.read_text())
    validate(data, args.expected_sha)
    checksum = hashlib.sha256(canonical(data)).hexdigest()
    if args.checksum and checksum != args.checksum.removeprefix("sha256:"):
        raise SystemExit("release manifest checksum mismatch")
    if args.write_checksum:
        args.manifest.write_bytes(canonical(data))
        args.manifest.with_suffix(args.manifest.suffix + ".sha256").write_text(checksum + "\n")
    print(f"release manifest verified: sha256:{checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
