#!/usr/bin/env python3
"""Fail closed when a staging image digest is not tagged for the reviewed commit.

The Terraform contract pins ECS to an image digest, while the immutable
delivery workflow publishes the same image under the exact source commit SHA.
Checking only that a digest exists in ECR is insufficient: a stale digest can
be present, valid, and still deploy code from an older head.  This checker
reads ECR image metadata only and never pulls an image or prints credentials.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,255}$")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def image_metadata(
    *,
    repository: str,
    digest: str,
    runner: Runner = subprocess.run,
) -> tuple[Mapping[str, Any] | None, str | None]:
    result = runner(
        [
            "aws",
            "ecr",
            "describe-images",
            "--repository-name",
            repository,
            "--image-ids",
            f"imageDigest={digest}",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, "ECR image metadata request failed"
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return None, "ECR returned invalid image metadata"
    details = payload.get("imageDetails") if isinstance(payload, Mapping) else None
    if not isinstance(details, list) or not details or not isinstance(details[0], Mapping):
        return None, "ECR returned no image for the requested digest"
    return details[0], None


def provenance_errors(
    *,
    repository: str,
    digest: str,
    expected_commit: str | None = None,
    runner: Runner = subprocess.run,
) -> list[str]:
    errors: list[str] = []
    if not REPOSITORY_RE.fullmatch(repository):
        errors.append("repository is not a valid ECR repository name")
    if not DIGEST_RE.fullmatch(digest):
        errors.append("digest must be an immutable sha256 digest")
    if expected_commit is not None and not COMMIT_RE.fullmatch(expected_commit):
        errors.append("expected commit must be a 40-character lowercase Git SHA")
    if errors:
        return errors

    metadata, error = image_metadata(repository=repository, digest=digest, runner=runner)
    if error or metadata is None:
        errors.append(f"{error or 'ECR image metadata is unavailable'} for {repository}")
        return errors

    actual_digest = metadata.get("imageDigest")
    if actual_digest != digest:
        errors.append("ECR returned a different digest for the requested image")
    tags = metadata.get("imageTags")
    if not isinstance(tags, list):
        tags = []
    normalized_tags = {tag for tag in tags if isinstance(tag, str)}
    if expected_commit is not None and expected_commit not in normalized_tags:
        errors.append(
            f"{repository}@{digest} is not tagged with the reviewed commit {expected_commit}"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="aether-backend")
    parser.add_argument("--digest", required=True)
    parser.add_argument(
        "--expected-commit",
        help="Require the immutable image to carry this exact commit-SHA tag",
    )
    args = parser.parse_args(argv)
    errors = provenance_errors(
        repository=args.repository,
        digest=args.digest,
        expected_commit=args.expected_commit,
    )
    if errors:
        print("staging image provenance FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    tag_message = f" tagged {args.expected_commit}" if args.expected_commit else ""
    print(f"staging image provenance valid: {args.repository}@{args.digest}{tag_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
