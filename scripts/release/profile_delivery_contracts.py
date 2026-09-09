#!/usr/bin/env python3
"""Profile-aware GitHub delivery request/result contracts.

These contracts describe what a hosted workflow may be asked to do.  They do
not perform wake, deploy, promotion, rollback, tenant setup, or cleanup.  A
workflow adapter must supply the exact candidate identity and retain the
resulting evidence before a later authority can consume it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

try:
    from hosted_delivery_adapters import HostedAdapterError
except ModuleNotFoundError:  # pragma: no cover
    from scripts.release.hosted_delivery_adapters import HostedAdapterError


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
PROFILE_CONFIG = ROOT / "config" / "deployment_profiles.yaml"
EPHEMERAL_PROFILES = frozenset({"preview", "demo"})
PROMOTION_PROFILES = frozenset({"production-lean", "production-scale", "enterprise-isolated"})
OPERATIONS = frozenset({"wake", "sleep", "deploy", "validate", "promote", "rollback", "reconcile", "destroy"})
RESULT_STATUSES = frozenset({"DRY_RUN", "BLOCKED", "FAILED", "DEPLOYED", "VALIDATED", "PROMOTED", "ROLLED_BACK", "SLEPT"})
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProfileDeliveryError(ValueError):
    """A profile delivery request/result is unsafe or inconsistent."""


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileDeliveryError(f"{where} must be a non-empty string")
    return value.strip()


def _identity(value: Mapping[str, Any], where: str = "candidate_identity") -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ProfileDeliveryError(f"{where} must be an object")
    required = ("release_candidate_id", "commit_sha", "artifact_digest", "profile")
    missing = [key for key in required if key not in value]
    if missing:
        raise ProfileDeliveryError(f"{where} is missing: {', '.join(missing)}")
    result = {key: _string(value[key], f"{where}.{key}") for key in required}
    if not _COMMIT.fullmatch(result["commit_sha"]) or not _DIGEST.fullmatch(result["artifact_digest"]):
        raise ProfileDeliveryError(f"{where} has invalid commit or artifact digest")
    return result


def canonical_profiles() -> dict[str, Mapping[str, Any]]:
    try:
        raw = yaml.safe_load(PROFILE_CONFIG.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileDeliveryError(f"cannot read deployment profiles: {exc}") from exc
    profiles = raw.get("profiles") if isinstance(raw, Mapping) else None
    if not isinstance(profiles, Mapping) or not profiles:
        raise ProfileDeliveryError("deployment profile registry is empty")
    return dict(profiles)


@dataclass(frozen=True)
class DeliveryRequest:
    operation_id: str
    operation: str
    profile: str
    candidate_identity: dict[str, str]
    requested_at: str
    ttl_hours: int | None = None
    staging_evidence: dict[str, str] | None = None
    from_candidate: dict[str, str] | None = None
    to_candidate: dict[str, str] | None = None
    dry_run: bool = False
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DeliveryRequest":
        if not isinstance(value, Mapping):
            raise ProfileDeliveryError("delivery request must be an object")
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise ProfileDeliveryError("schema_version must be 1")
        operation_id = _string(value.get("operation_id"), "operation_id")
        operation = _string(value.get("operation"), "operation")
        if operation not in OPERATIONS:
            raise ProfileDeliveryError(f"operation must be one of {sorted(OPERATIONS)}")
        profile = _string(value.get("profile"), "profile")
        identity = _identity(value.get("candidate_identity"), "candidate_identity")
        requested_at = _string(value.get("requested_at"), "requested_at")
        try:
            datetime.fromisoformat(requested_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProfileDeliveryError("requested_at must be ISO-8601") from exc
        ttl_hours = value.get("ttl_hours")
        if ttl_hours is not None and (not isinstance(ttl_hours, int) or isinstance(ttl_hours, bool) or not 0 < ttl_hours <= 168):
            raise ProfileDeliveryError("ttl_hours must be an integer from 1 through 168")
        def optional_identity(name: str) -> dict[str, str] | None:
            raw = value.get(name)
            return _identity(raw, name) if raw is not None else None
        result = cls(
            operation_id, operation, profile, identity, requested_at, ttl_hours,
            optional_identity("staging_evidence"), optional_identity("from_candidate"),
            optional_identity("to_candidate"), value.get("dry_run", False),
            SCHEMA_VERSION,
        )
        if not isinstance(result.dry_run, bool):
            raise ProfileDeliveryError("dry_run must be boolean")
        errors = validate_request(result)
        if errors:
            raise ProfileDeliveryError("invalid delivery request: " + "; ".join(errors))
        return result

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "operation": self.operation,
            "profile": self.profile,
            "candidate_identity": self.candidate_identity,
            "requested_at": self.requested_at,
            "dry_run": self.dry_run,
            **({"ttl_hours": self.ttl_hours} if self.ttl_hours is not None else {}),
            **({"staging_evidence": self.staging_evidence} if self.staging_evidence else {}),
            **({"from_candidate": self.from_candidate} if self.from_candidate else {}),
            **({"to_candidate": self.to_candidate} if self.to_candidate else {}),
        }


def validate_request(request: DeliveryRequest) -> list[str]:
    profiles = canonical_profiles()
    errors: list[str] = []
    if request.profile not in profiles:
        errors.append(f"unknown deployment profile: {request.profile}")
        return errors
    if request.candidate_identity["profile"] != request.profile and request.operation not in {"promote", "rollback"}:
        errors.append("candidate identity profile does not match requested profile")
    config = profiles[request.profile]
    if request.operation in {"wake", "sleep"} and not config.get("wake_sleep"):
        errors.append(f"{request.profile} does not declare wake_sleep")
    if request.profile in EPHEMERAL_PROFILES:
        if not config.get("ttl_cleanup_required"):
            errors.append(f"{request.profile} must require TTL cleanup")
        if request.operation in {"deploy", "validate", "destroy"} and request.ttl_hours is None:
            errors.append(f"{request.profile} {request.operation} requires ttl_hours")
    if request.operation == "promote":
        if request.profile not in PROMOTION_PROFILES:
            errors.append("promote target must be a production profile")
        if request.staging_evidence is None:
            errors.append("promotion requires staging_evidence")
        elif request.staging_evidence != request.candidate_identity:
            errors.append("staging_evidence must exactly match candidate_identity")
    if request.operation == "rollback":
        if request.from_candidate is None or request.to_candidate is None:
            errors.append("rollback requires from_candidate and to_candidate")
        else:
            if request.from_candidate != request.candidate_identity:
                errors.append("rollback from_candidate must match candidate_identity")
            if request.to_candidate == request.from_candidate:
                errors.append("rollback target must differ from source candidate")
    return sorted(set(errors))


def validate_result(request: DeliveryRequest, result: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(result, Mapping):
        return ["result must be an object"]
    try:
        status = _string(result.get("status"), "result.status")
        identity = _identity(result.get("candidate_identity"), "result.candidate_identity")
    except ProfileDeliveryError as exc:
        return [str(exc)]
    if status not in RESULT_STATUSES:
        errors.append("result.status is invalid")
    if identity != request.candidate_identity:
        errors.append("result candidate identity does not match request")
    if request.dry_run and status in {"DEPLOYED", "PROMOTED", "ROLLED_BACK", "SLEPT"}:
        errors.append("dry-run cannot report a mutating result")
    if request.operation == "promote" and status == "PROMOTED" and not request.staging_evidence:
        errors.append("promoted result requires staging evidence")
    if request.profile in EPHEMERAL_PROFILES and status in {"DEPLOYED", "VALIDATED"}:
        cleanup = result.get("cleanup")
        if not isinstance(cleanup, Mapping) or cleanup.get("status") != "PASS":
            errors.append("ephemeral result requires PASS cleanup evidence")
    if status in {"BLOCKED", "FAILED"} and not result.get("next_action"):
        errors.append("blocked/failed result requires next_action")
    return sorted(set(errors))


def operation_telemetry(request: DeliveryRequest, result: Mapping[str, Any]) -> dict[str, Any]:
    """Build the data payload consumed by the canonical telemetry registry."""
    identity = request.candidate_identity
    metrics = result.get("metrics") if isinstance(result.get("metrics"), Mapping) else {}
    return {
        "operation_id": request.operation_id,
        "operation": request.operation,
        "profile": request.profile,
        "release_candidate_id": identity["release_candidate_id"],
        "commit_sha": identity["commit_sha"],
        "artifact_digest": identity["artifact_digest"],
        "status": result.get("status", "BLOCKED"),
        "mutation_occurred": bool(result.get("mutation_occurred", False)),
        "retryable": bool(result.get("retryable", False)),
        "resumed": bool(result.get("resumed", False)),
        "duration_seconds": int(metrics.get("duration_seconds", 0)),
        "queue_seconds": int(metrics.get("queue_seconds", 0)),
        "setup_seconds": int(metrics.get("setup_seconds", 0)),
        "execution_seconds": int(metrics.get("execution_seconds", 0)),
        "cache_hit": bool(metrics.get("cache_hit", False)),
        "failure_category": str(result.get("failure_category", "NONE")),
        "next_action": str(result.get("next_action", "none")),
        "evidence_ref": str(result.get("evidence_ref", "offline://unpersisted")),
    }


__all__ = ["DeliveryRequest", "ProfileDeliveryError", "canonical_profiles", "operation_telemetry", "validate_request", "validate_result"]
