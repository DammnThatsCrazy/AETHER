#!/usr/bin/env python3
"""Publish staged ML model artifacts to S3 and mark them as promoted.

Reads artifact metadata from aether-ml's ArtifactRegistry, uploads each
artifact with promotion_state='staged' to $ML_ARTIFACT_BUCKET via boto3,
marks them promoted in the registry, then runs a health-check against
$ML_SERVING_URL/v1/health.

Exit 0 on success, 1 with error detail on failure.

Required env vars:
  ML_ARTIFACT_BUCKET   — S3 bucket name (e.g. aether-ml-artifacts-prod)
  ML_SERVING_URL       — base URL of the ML serving API (e.g. https://ml.aether.network)

Optional:
  ML_ARTIFACT_DIR      — override the default artifact output directory
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

ML_ROOT = Path(__file__).parent.parent / "ML Models" / "aether-ml"
sys.path.insert(0, str(ML_ROOT))


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        print(f"ERROR: {name} env var is not set", file=sys.stderr)
        sys.exit(1)
    return val


def _s3_upload(bucket: str, key: str, path: Path) -> None:
    try:
        import boto3  # type: ignore[import]
    except ImportError:
        print("ERROR: boto3 is not installed — pip install boto3", file=sys.stderr)
        sys.exit(1)
    s3 = boto3.client("s3")
    print(f"  uploading s3://{bucket}/{key} ...", end=" ", flush=True)
    s3.upload_file(str(path), bucket, key)
    print("OK")


def _health_check(serving_url: str) -> None:
    import urllib.request
    url = serving_url.rstrip("/") + "/v1/health"
    print(f"  health check {url} ...", end=" ", flush=True)
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            body = json.loads(resp.read())
            print(f"OK — status={body.get('status', 'unknown')}")
    except Exception as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    bucket = _require_env("ML_ARTIFACT_BUCKET")
    serving_url = _require_env("ML_SERVING_URL")
    artifact_dir = Path(os.getenv("ML_ARTIFACT_DIR", str(ML_ROOT / "artifacts")))

    try:
        from common.artifact_registry import ArtifactRegistry, ArtifactMetadata
    except ImportError as exc:
        print(f"ERROR: cannot import ArtifactRegistry — {exc}", file=sys.stderr)
        sys.exit(1)

    registry = ArtifactRegistry(artifact_dir=artifact_dir)

    try:
        artifacts: list[ArtifactMetadata] = registry.list_artifacts()
    except Exception as exc:
        print(f"ERROR: failed to load artifact registry — {exc}", file=sys.stderr)
        sys.exit(1)

    staged = [a for a in artifacts if getattr(a, "promotion_state", None) == "staged"]
    if not staged:
        print("No artifacts in 'staged' state — nothing to publish.")
        _health_check(serving_url)
        return

    print(f"Publishing {len(staged)} staged artifact(s) to s3://{bucket}")
    for artifact in staged:
        artifact_path = artifact_dir / artifact.model_id / artifact.artifact_version
        if not artifact_path.exists():
            # Try as a direct file path
            artifact_path = artifact_dir / f"{artifact.model_id}-{artifact.artifact_version}.{artifact.artifact_format}"
        if not artifact_path.exists():
            print(f"  WARN: artifact path not found for {artifact.model_id}@{artifact.artifact_version}, skipping")
            continue

        s3_key = f"models/{artifact.model_id}/{artifact.artifact_version}/{artifact_path.name}"
        _s3_upload(bucket, s3_key, artifact_path)

        try:
            registry.mark_promoted(artifact.model_id, artifact.artifact_version)
            print(f"  marked {artifact.model_id}@{artifact.artifact_version} as promoted")
        except Exception as exc:
            print(f"  WARN: failed to mark promoted — {exc}")

    print("Upload complete. Running serving health check...")
    _health_check(serving_url)
    print("Done.")


if __name__ == "__main__":
    main()
