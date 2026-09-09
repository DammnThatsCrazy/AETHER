#!/usr/bin/env python3
"""Verify deployable artifact closure and provenance without rebuilding.

The builder creates the immutable candidate.  This module verifies that the
bytes named by that candidate still exist, retain their digest, and contain
the runtime entries the deploy workflow declares.  It does not upload, sign,
rebuild, or promote an artifact; hosted workflows can attach their registry
and signature references to the resulting evidence.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from delivery_contracts import validate_release_candidate
except ModuleNotFoundError:  # pragma: no cover
    from scripts.delivery_contracts import validate_release_candidate


SCHEMA_VERSION = 1
_DIGEST_PREFIX = "sha256:"
_PROVENANCE_SOURCES = frozenset({"local", "github_artifact", "hosted_registry"})


class ArtifactClosureError(ValueError):
    """An artifact cannot be proven to be the candidate's deployable closure."""


def digest_file(path: Path) -> str:
    if not path.is_file():
        raise ArtifactClosureError(f"artifact is not a file: {path}")
    return _DIGEST_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(candidate: Mapping[str, Any]) -> dict[str, str]:
    try:
        profile = candidate["deployment_impact"]["profile"]
        return {
            "release_candidate_id": str(candidate["release_candidate_id"]),
            "commit_sha": str(candidate["commit_sha"]),
            "artifact_digest": str(candidate["artifact_digest"]),
            "profile": str(profile),
        }
    except (KeyError, TypeError) as exc:
        raise ArtifactClosureError("candidate does not contain complete artifact identity") from exc


def _archive_entries(path: Path) -> set[str]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return {item for item in archive.namelist() if not item.endswith("/")}
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            return {item.name for item in archive.getmembers() if item.isfile()}
    return set()


def _required_entries(path: Path, patterns: list[str]) -> list[str]:
    if not patterns:
        return []
    entries = _archive_entries(path)
    if not entries:
        raise ArtifactClosureError(
            f"artifact {path} is not an archive but required closure entries were declared"
        )
    missing = sorted(pattern for pattern in patterns if not any(fnmatch.fnmatch(entry, pattern) for entry in entries))
    if missing:
        raise ArtifactClosureError(f"artifact {path} is missing required entries: {', '.join(missing)}")
    return sorted(patterns)


@dataclass(frozen=True)
class ArtifactSpec:
    name: str
    path: Path
    required_entries: tuple[str, ...] = ()


def verify_closure(
    candidate: Mapping[str, Any],
    artifacts: Mapping[str, ArtifactSpec],
    *,
    provenance_source: str = "local",
    builder: str = "repository",
    registry_ref: str | None = None,
    signature_ref: str | None = None,
) -> dict[str, Any]:
    """Return closure evidence or raise before any deployment action."""

    candidate_errors = validate_release_candidate(candidate)
    if candidate_errors:
        raise ArtifactClosureError("invalid release candidate: " + "; ".join(candidate_errors))
    if provenance_source not in _PROVENANCE_SOURCES:
        raise ArtifactClosureError(f"unsupported provenance source: {provenance_source}")
    if signature_ref and provenance_source == "local":
        raise ArtifactClosureError("local closure cannot claim a hosted signature reference")
    component_digests = candidate.get("component_digests", {})
    if set(artifacts) != set(component_digests):
        raise ArtifactClosureError("closure artifacts must exactly match candidate components")
    entries: dict[str, dict[str, Any]] = {}
    for name in sorted(artifacts):
        spec = artifacts[name]
        if spec.name != name:
            raise ArtifactClosureError(f"artifact spec name mismatch for {name}")
        actual = digest_file(spec.path)
        expected = component_digests.get(name)
        if actual != expected:
            raise ArtifactClosureError(f"artifact digest mismatch for {name}")
        verified = _required_entries(spec.path, list(spec.required_entries))
        entries[name] = {
            "path": str(spec.path),
            "digest": actual,
            "required_entries": verified,
            "closure": "PASS",
        }
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "candidate_identity": _identity(candidate),
        "artifacts": entries,
        "artifact_digest": candidate["artifact_digest"],
        "provenance": {
            "source": provenance_source,
            "builder": builder,
            "registry_ref": registry_ref,
            "signature_ref": signature_ref,
            "signature_status": "VERIFIED" if signature_ref else "UNSIGNED_OR_UNVERIFIED",
        },
    }
    return result


def validate_closure_evidence(value: Mapping[str, Any]) -> list[str]:
    """Validate serialized closure evidence and reject fabricated hosted claims."""

    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if value.get("status") != "PASS":
        errors.append("closure status must be PASS")
    identity = value.get("candidate_identity")
    if not isinstance(identity, Mapping):
        errors.append("candidate_identity must be an object")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        errors.append("artifacts must be a non-empty object")
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping):
        errors.append("provenance must be an object")
    else:
        source = provenance.get("source")
        if source not in _PROVENANCE_SOURCES:
            errors.append("provenance.source is invalid")
        if provenance.get("signature_status") == "VERIFIED" and not provenance.get("signature_ref"):
            errors.append("verified signature requires signature_ref")
        if source == "local" and provenance.get("signature_ref"):
            errors.append("local provenance cannot carry signature_ref")
    if not isinstance(value.get("artifact_digest"), str) or not value.get("artifact_digest", "").startswith(_DIGEST_PREFIX):
        errors.append("artifact_digest must be sha256")
    return sorted(set(errors))


__all__ = ["ArtifactClosureError", "ArtifactSpec", "digest_file", "validate_closure_evidence", "verify_closure"]
