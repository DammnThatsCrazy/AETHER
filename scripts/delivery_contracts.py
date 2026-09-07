"""Small, dependency-free contracts shared by the delivery commands.

The delivery scripts deliberately run before the backend environment is
available.  Keeping these value objects in a dependency-free module gives the
artifact builder and staging orchestrator one vocabulary for immutable
candidates, deployment impact, and fail-closed command outcomes.
"""
from __future__ import annotations

import re
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
        if not isinstance(value, list) or len(value) != len(set(value or [])):
            errors.append(f"{field_name} must be a unique list")
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
    impact = candidate.get("deployment_impact")
    if not isinstance(impact, dict):
        errors.append("deployment_impact must be an object")
    else:
        try:
            DeploymentImpact(
                profile=str(impact.get("profile", "")),
                affected_domains=tuple(impact.get("affected_domains", [])),
                affected_components=tuple(impact.get("affected_components", [])),
                migration_required=bool(impact.get("migration_required")),
                data_contract_change=bool(impact.get("data_contract_change")),
                security_sensitive=bool(impact.get("security_sensitive")),
                rollback_required=bool(impact.get("rollback_required")),
                approval_required=bool(impact.get("approval_required")),
                risk_level=str(impact.get("risk_level", "")),
                rationale=str(impact.get("rationale", "")),
                schema_version=impact.get("schema_version", 0),
            )
        except (TypeError, ValueError) as exc:
            errors.append(f"deployment_impact is invalid: {exc}")
    try:
        datetime.fromisoformat(str(candidate.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        errors.append("created_at must be an ISO-8601 timestamp")
    return sorted(set(errors))
