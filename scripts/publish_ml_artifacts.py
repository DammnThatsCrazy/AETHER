#!/usr/bin/env python3
"""Publish staged ML model artifacts to S3 and mark them as promoted.

Scans the artifact directory for models with promotion_state='staged', uploads
each artifact file to $ML_ARTIFACT_BUCKET via boto3, promotes it in the
registry metadata, then runs a health-check against $ML_SERVING_URL/v1/health.

Exit 0 on success, 1 with error detail on failure.

Required env vars:
  ML_ARTIFACT_BUCKET   — S3 bucket name (e.g. aether-ml-artifacts-prod)
  ML_SERVING_URL       — base URL of the ML serving API (e.g. https://ml.aether.network)

Optional:
  ML_ARTIFACT_DIR      — override the default artifact output directory
                         (default: ML Models/aether-ml/artifacts)
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
        from common.artifact_registry import list_artifacts, promote_artifact, ArtifactMetadata
    except ImportError as exc:
        print(f"ERROR: cannot import artifact_registry — {exc}", file=sys.stderr)
        sys.exit(1)

    if not artifact_dir.exists():
        print(f"Artifact directory not found: {artifact_dir} — nothing to publish.")
        _health_check(serving_url)
        return

    # Collect all staged artifacts across all model directories
    staged: list[tuple[str, ArtifactMetadata]] = []
    for model_dir in sorted(artifact_dir.iterdir()):
        if not model_dir.is_dir():
            continue
        model_id = model_dir.name
        for meta in list_artifacts(artifact_dir, model_id):
            if meta.promotion_state == "staged":
                staged.append((model_id, meta))

    if not staged:
        print("No artifacts in 'staged' state — nothing to publish.")
        _health_check(serving_url)
        return

    print(f"Publishing {len(staged)} staged artifact(s) to s3://{bucket}")
    for model_id, artifact in staged:
        # artifact_path in metadata is the absolute path to the model file
        artifact_file = Path(artifact.artifact_path)
        if not artifact_file.exists():
            # Fallback: look relative to the version directory
            version_dir = artifact_dir / model_id / artifact.artifact_version
            artifact_file = version_dir / Path(artifact.artifact_path).name
        if not artifact_file.exists():
            print(f"  WARN: artifact file not found for {model_id}@{artifact.artifact_version}, skipping")
            continue

        s3_key = f"models/{model_id}/{artifact.artifact_version}/{artifact_file.name}"
        _s3_upload(bucket, s3_key, artifact_file)

        # promote_artifact takes the version directory (where metadata.json lives)
        version_dir = artifact_file.parent
        try:
            promote_artifact(version_dir, "promoted", promoted_by="publish_ml_artifacts")
            print(f"  marked {model_id}@{artifact.artifact_version} as promoted")
        except Exception as exc:
            print(f"  WARN: failed to mark promoted — {exc}")

    print("Upload complete. Running serving health check...")
    _health_check(serving_url)
    print("Done.")


if __name__ == "__main__":
    main()
