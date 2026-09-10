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
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from delivery_contracts import _aggregate_digest, validate_release_candidate
except ModuleNotFoundError:  # pragma: no cover
    from scripts.delivery_contracts import _aggregate_digest, validate_release_candidate


SCHEMA_VERSION = 1
_DIGEST_PREFIX = "sha256:"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
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
    if not isinstance(value, Mapping):
        return ["closure evidence must be an object"]
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if value.get("status") != "PASS":
        errors.append("closure status must be PASS")
    identity = value.get("candidate_identity")
    if not isinstance(identity, Mapping):
        errors.append("candidate_identity must be an object")
    else:
        required_identity = ("release_candidate_id", "commit_sha", "artifact_digest", "profile")
        missing = [key for key in required_identity if key not in identity]
        if missing:
            errors.append("candidate_identity is missing: " + ", ".join(missing))
        elif (
            not isinstance(identity["release_candidate_id"], str)
            or not identity["release_candidate_id"].strip()
            or not isinstance(identity["profile"], str)
            or not identity["profile"].strip()
            or not isinstance(identity["commit_sha"], str)
            or not _COMMIT.fullmatch(identity["commit_sha"])
            or not isinstance(identity["artifact_digest"], str)
            or not _DIGEST.fullmatch(identity["artifact_digest"])
        ):
            errors.append("candidate_identity has invalid fields")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, Mapping) or not artifacts:
        errors.append("artifacts must be a non-empty object")
        artifact_digests: dict[str, str] = {}
    else:
        artifact_digests = {}
        for name, artifact in artifacts.items():
            if not isinstance(name, str) or not name.strip():
                errors.append("artifacts must use non-empty string names")
                continue
            if not isinstance(artifact, Mapping):
                errors.append(f"artifact {name} must be an object")
                continue
            required = {"path", "digest", "required_entries", "closure"}
            missing = sorted(required - set(artifact))
            if missing:
                errors.append(f"artifact {name} is missing: {', '.join(missing)}")
                continue
            path = artifact.get("path")
            if not isinstance(path, str) or not path.strip():
                errors.append(f"artifact {name}.path must be a non-empty string")
            digest = artifact.get("digest")
            if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
                errors.append(f"artifact {name}.digest must be an immutable sha256 digest")
            else:
                artifact_digests[name] = digest
            entries = artifact.get("required_entries")
            if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
                errors.append(f"artifact {name}.required_entries must be a list of strings")
            if artifact.get("closure") != "PASS":
                errors.append(f"artifact {name}.closure must be PASS")
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
    if not isinstance(value.get("artifact_digest"), str) or not _DIGEST.fullmatch(value.get("artifact_digest", "")):
        errors.append("artifact_digest must be sha256")
    else:
        if isinstance(identity, Mapping) and identity.get("artifact_digest") != value.get("artifact_digest"):
            errors.append("artifact_digest must match candidate_identity.artifact_digest")
        if artifact_digests and _aggregate_digest(artifact_digests) != value.get("artifact_digest"):
            errors.append("artifact_digest does not match serialized artifact digests")
    return sorted(set(errors))


__all__ = ["ArtifactClosureError", "ArtifactSpec", "digest_file", "validate_closure_evidence", "verify_closure"]
