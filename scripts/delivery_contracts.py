"""Small, dependency-free contracts shared by the delivery commands.

The delivery scripts deliberately run before the backend environment is
available.  Keeping these value objects in a dependency-free module gives the
artifact builder and staging orchestrator one vocabulary for immutable
candidates, deployment impact, and fail-closed command outcomes.
"""
from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping, Any


SCHEMA_VERSION = 1
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
FAILURE_STATUSES = frozenset({"BLOCKED", "FAILED"})

# Command output is evidence, but it is not a safe place to persist secrets.
# These patterns intentionally cover the common credential-bearing forms while
# leaving ordinary diagnostic text intact.
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(\b(?:aws_secret_access_key|aws_session_token|password|token|api[_-]?key)\s*[=:]\s*)[^\s,;]+"), r"\1[redacted]"),
    (re.compile(r"(?i)(postgres(?:ql)?://[^:/\s]+:)[^@/\s]+(@)"), r"\1[redacted]\2"),
)


def sanitize_detail(value: str, *, limit: int = 4000) -> str:
    """Bound and redact command detail before it enters release evidence."""

    result = str(value or "")
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result[-limit:]


def _aggregate_digest(values: Mapping[str, Any]) -> str:
    """Derive the canonical digest for a named digest map.

    Candidate identity is a relationship, not merely a set of correctly
    shaped strings.  Keeping this helper here lets every consumer verify the
    same canonical serialization without importing the artifact builder.
    """

    payload = json.dumps(dict(values), sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class DeploymentImpact:
    """The deployment-relevant impact of an immutable release candidate."""

    profile: str
    affected_domains: tuple[str, ...]
    affected_components: tuple[str, ...]
    migration_required: bool
    data_contract_change: bool
    security_sensitive: bool
    rollback_required: bool
    approval_required: bool
    risk_level: str
    rationale: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("deployment impact schema_version must be 1")
        if not self.profile.strip():
            raise ValueError("deployment impact profile is required")
        if not self.affected_domains:
            raise ValueError("deployment impact requires an affected domain")
        if not self.affected_components:
            raise ValueError("deployment impact requires an affected component")
        if len(set(self.affected_domains)) != len(self.affected_domains):
            raise ValueError("deployment impact domains must be unique")
        if len(set(self.affected_components)) != len(self.affected_components):
            raise ValueError("deployment impact components must be unique")
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"invalid deployment impact risk level: {self.risk_level}")
        if not self.rationale.strip():
            raise ValueError("deployment impact rationale is required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "affected_domains": list(self.affected_domains),
            "affected_components": list(self.affected_components),
            "migration_required": self.migration_required,
            "data_contract_change": self.data_contract_change,
            "security_sensitive": self.security_sensitive,
            "rollback_required": self.rollback_required,
            "approval_required": self.approval_required,
            "risk_level": self.risk_level,
            "rationale": self.rationale,
        }

    @classmethod
    def for_candidate(
        cls,
        *,
        profile: str,
        components: list[str] | tuple[str, ...],
        affected_domains: list[str] | tuple[str, ...],
        migration_version: str,
        risk_level: str = "medium",
        security_sensitive: bool = False,
        data_contract_change: bool = False,
        approval_required: bool = False,
    ) -> "DeploymentImpact":
        migration_required = migration_version != "none"
        return cls(
            profile=profile,
            affected_domains=tuple(sorted(set(affected_domains or ("delivery",)))),
            affected_components=tuple(sorted(set(components))),
            migration_required=migration_required,
            data_contract_change=data_contract_change,
            security_sensitive=security_sensitive,
            rollback_required=migration_required or security_sensitive,
            approval_required=approval_required,
            risk_level=risk_level,
            rationale=(
                "migration and security-sensitive changes require rollback evidence"
                if migration_required or security_sensitive
                else "candidate contains immutable, digest-bound build outputs"
            ),
        )


@dataclass(frozen=True)
class FailureEnvelope:
    """A safe, machine-readable explanation for a blocked or failed stage."""

    operation_id: str
    stage: str
    status: str
    code: str
    message: str
    retryable: bool
    blocking: bool
    evidence_ref: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("failure envelope schema_version must be 1")
        if not self.operation_id.strip() or not self.stage.strip() or not self.code.strip():
            raise ValueError("failure envelope operation_id, stage, and code are required")
        if self.status not in FAILURE_STATUSES:
            raise ValueError("failure envelope status must be BLOCKED or FAILED")
        if not self.message.strip():
            raise ValueError("failure envelope message is required")
        if self.evidence_ref is not None and not self.evidence_ref.strip():
            raise ValueError("failure envelope evidence_ref cannot be empty")
        cleaned = {
            str(key): sanitize_detail(str(value), limit=1000)
            for key, value in self.details.items()
        }
        object.__setattr__(self, "message", sanitize_detail(self.message))
        object.__setattr__(self, "details", MappingProxyType(cleaned))

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "stage": self.stage,
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "blocking": self.blocking,
        }
        if self.evidence_ref is not None:
            result["evidence_ref"] = self.evidence_ref
        if self.details:
            result["details"] = dict(self.details)
        return result

    @classmethod
    def from_result(
        cls,
        *,
        operation_id: str,
        stage: str,
        status: str,
        reason: str,
        code: str,
        evidence_ref: str | None = None,
        retryable: bool | None = None,
        details: Mapping[str, str] | None = None,
    ) -> "FailureEnvelope":
        if retryable is None:
            retryable = status == "BLOCKED"
        return cls(
            operation_id=operation_id,
            stage=stage,
            status=status,
            code=code,
            message=reason,
            retryable=retryable,
            blocking=True,
            evidence_ref=evidence_ref,
            details=details or {},
        )


def validate_release_candidate(candidate: Mapping[str, Any]) -> list[str]:
    """Validate the identity-bearing shape before any candidate is consumed."""

    required = {
        "schema_version", "release_candidate_id", "commit_sha", "artifact_digest",
        "dependency_lock_hash", "dependency_lock_digests", "contract_versions",
        "migration_version", "model_versions", "policy_versions", "deployment_profiles",
        "affected_domains", "required_checks", "component_digests", "deployment_impact",
        "created_at",
    }
    errors: list[str] = []
    if not isinstance(candidate, Mapping):
        return ["release candidate must be an object"]
    unknown = sorted(set(candidate) - required)
    if unknown:
        errors.append("unknown fields: " + ", ".join(unknown))
    missing = sorted(required - set(candidate))
    if missing:
        errors.append("missing fields: " + ", ".join(missing))
    if candidate.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    if not isinstance(candidate.get("release_candidate_id"), str) or not candidate.get("release_candidate_id", "").strip():
        errors.append("release_candidate_id must be a non-empty string")
    if not COMMIT_RE.fullmatch(str(candidate.get("commit_sha", ""))):
        errors.append("commit_sha must be 7-64 lowercase hex characters")
    for field_name in ("artifact_digest", "dependency_lock_hash"):
        if not DIGEST_RE.fullmatch(str(candidate.get(field_name, ""))):
            errors.append(f"{field_name} must be an immutable sha256 digest")
    for field_name in ("deployment_profiles", "affected_domains", "required_checks"):
        value = candidate.get(field_name)
        if not isinstance(value, list):
            errors.append(f"{field_name} must be a unique list of non-empty strings")
            continue
        if (
            (not value and field_name != "required_checks")
            or any(not isinstance(item, str) or not item.strip() for item in value)
            or len(value) != len(set(value))
        ):
            errors.append(f"{field_name} must be a unique list of non-empty strings")
    for field_name in ("contract_versions", "model_versions", "policy_versions"):
        value = candidate.get(field_name)
        if not isinstance(value, dict):
            errors.append(f"{field_name} must be an object")
        elif any(not isinstance(key, str) or not key.strip() for key in value):
            errors.append(f"{field_name} must have non-empty string keys")
    if not isinstance(candidate.get("migration_version"), str) or not candidate.get("migration_version", "").strip():
        errors.append("migration_version must be a non-empty string")
    value = candidate.get("model_versions")
    if isinstance(value, dict) and any(not isinstance(item, str) for item in value.values()):
        errors.append("model_versions values must be strings")
    for field_name in ("contract_versions", "policy_versions"):
        value = candidate.get(field_name)
        if isinstance(value, dict) and any(not isinstance(item, (str, int, float)) or isinstance(item, bool) for item in value.values()):
            errors.append(f"{field_name} values must be strings or numbers")
    components = candidate.get("component_digests")
    if not isinstance(components, dict) or not components:
        errors.append("component_digests must contain at least one component")
    else:
        for name, digest in components.items():
            if not isinstance(name, str) or not name.strip() or not DIGEST_RE.fullmatch(str(digest)):
                errors.append(f"component {name!r} has an invalid digest")
    lock_digests = candidate.get("dependency_lock_digests")
    if not isinstance(lock_digests, dict):
        errors.append("dependency_lock_digests must be an object")
    else:
        invalid_locks = [
            name for name, digest in lock_digests.items()
            if not isinstance(name, str) or not name.strip() or not DIGEST_RE.fullmatch(str(digest))
        ]
        if invalid_locks:
            errors.append("dependency_lock_digests contains invalid entries")
    impact = candidate.get("deployment_impact")
    if not isinstance(impact, dict):
        errors.append("deployment_impact must be an object")
    else:
        impact_keys = {
            "schema_version", "profile", "affected_domains", "affected_components",
            "migration_required", "data_contract_change", "security_sensitive",
            "rollback_required", "approval_required", "risk_level", "rationale",
        }
        extra_impact = sorted(set(impact) - impact_keys)
        if extra_impact:
            errors.append("deployment_impact has unknown fields: " + ", ".join(extra_impact))
        for boolean_name in ("migration_required", "data_contract_change", "security_sensitive", "rollback_required", "approval_required"):
            if not isinstance(impact.get(boolean_name), bool):
                errors.append(f"deployment_impact.{boolean_name} must be boolean")
        impact_booleans_valid = all(
            isinstance(impact.get(boolean_name), bool)
            for boolean_name in (
                "migration_required",
                "data_contract_change",
                "security_sensitive",
                "rollback_required",
                "approval_required",
            )
        )
        try:
            impact_domains = impact.get("affected_domains")
            impact_components = impact.get("affected_components")
            if not isinstance(impact_domains, list) or any(not isinstance(item, str) or not item.strip() for item in impact_domains):
                raise ValueError("affected_domains must be a list of non-empty strings")
            if not isinstance(impact_components, list) or any(not isinstance(item, str) or not item.strip() for item in impact_components):
                raise ValueError("affected_components must be a list of non-empty strings")
            if not isinstance(impact.get("profile"), str) or not impact["profile"].strip():
                raise ValueError("profile must be a non-empty string")
            if not isinstance(impact.get("rationale"), str) or not impact["rationale"].strip():
                raise ValueError("rationale must be a non-empty string")
            if not isinstance(impact.get("risk_level"), str):
                raise ValueError("risk_level must be a string")
            if not impact_booleans_valid:
                raise ValueError("boolean fields must be boolean")
            parsed_impact = DeploymentImpact(
                profile=impact["profile"],
                affected_domains=tuple(impact_domains),
                affected_components=tuple(impact_components),
                migration_required=impact["migration_required"],
                data_contract_change=impact["data_contract_change"],
                security_sensitive=impact["security_sensitive"],
                rollback_required=impact["rollback_required"],
                approval_required=impact["approval_required"],
                risk_level=impact["risk_level"],
                rationale=impact["rationale"],
                schema_version=impact.get("schema_version", 0),
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"deployment_impact is invalid: {exc}")
        else:
            profiles = candidate.get("deployment_profiles") or []
            if parsed_impact.profile not in profiles:
                errors.append("deployment_impact.profile must be listed in deployment_profiles")
            if set(parsed_impact.affected_domains) != set(candidate.get("affected_domains") or []):
                errors.append("deployment_impact.affected_domains must match affected_domains")
            component_names = set((candidate.get("component_digests") or {}).keys())
            if set(parsed_impact.affected_components) != component_names:
                errors.append("deployment_impact.affected_components must match component_digests")
            expected_migration = candidate.get("migration_version") != "none"
            if parsed_impact.migration_required != expected_migration:
                errors.append("deployment_impact.migration_required must match migration_version")
            expected_rollback = expected_migration or parsed_impact.security_sensitive
            if parsed_impact.rollback_required != expected_rollback:
                errors.append("deployment_impact.rollback_required must reflect migration or security impact")

    components = candidate.get("component_digests")
    if isinstance(components, dict) and components:
        if all(isinstance(name, str) and isinstance(digest, str) for name, digest in components.items()):
            if _aggregate_digest(components) != candidate.get("artifact_digest"):
                errors.append("artifact_digest does not match component_digests")
    if isinstance(lock_digests, dict) and all(
        isinstance(name, str) and isinstance(digest, str) for name, digest in lock_digests.items()
    ):
        if _aggregate_digest(lock_digests) != candidate.get("dependency_lock_hash"):
            errors.append("dependency_lock_hash does not match dependency_lock_digests")
    try:
        datetime.fromisoformat(str(candidate.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("created_at must be an ISO-8601 timestamp")
    return sorted(set(errors))
