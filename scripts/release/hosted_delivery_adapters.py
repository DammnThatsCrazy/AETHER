#!/usr/bin/env python3
"""Credential-safe contracts for hosted delivery adapters.

The repository owns the boundary between GitHub-hosted adapters and the
delivery authorities, but it does not own AWS credentials or a hosted
transport.  This module therefore validates requests and observations without
calling AWS, GitHub, Terraform, or a secrets backend.  A hosted workflow may
adapt its read-only output into these contracts; local fixtures use the same
validation and cannot claim live evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


SCHEMA_VERSION = 1
IDENTITY_KEYS = ("release_candidate_id", "commit_sha", "artifact_digest", "profile")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
_SOURCES = frozenset({"offline_fixture", "github_artifact", "aws_read_only", "github_environment"})
_STATUSES = frozenset({"PASS", "PASS_WITH_DEGRADATION", "BLOCKED", "FAILED"})
_AUTHORITIES = frozenset({"environment", "iam", "state", "artifact", "runtime", "release"})
_CREDENTIAL_SOURCES = frozenset({"github_oidc", "aws_profile", "injected_read_only"})
_SECRET_KEY = re.compile(
    r"(?:^|[_-])(secret|token|password|passwd|api[_-]?key|private[_-]?key|access[_-]?key)(?:$|[_-])",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|-----BEGIN[^-]*PRIVATE KEY-----|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_REDACTED = frozenset({"<sensitive>", "REDACTED", "***", "(redacted)"})


class HostedAdapterError(ValueError):
    """A hosted adapter request or response is unsafe or malformed."""


def _secret_paths(value: Any, path: str = "$", *, key: str | None = None) -> list[str]:
    paths: list[str] = []
    if key and _SECRET_KEY.search(key):
        if isinstance(value, str) and value and value not in _REDACTED:
            paths.append(path)
        elif value not in (None, False, 0, "", *_REDACTED):
            paths.append(path)
    elif isinstance(value, str) and value not in _REDACTED and _SECRET_VALUE.search(value):
        paths.append(path)
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            paths.extend(_secret_paths(child, f"{path}.{child_key}", key=str(child_key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_secret_paths(child, f"{path}[{index}]"))
    return paths


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostedAdapterError(f"{where} must be a non-empty string")
    return value.strip()


def _identity(value: Mapping[str, Any], where: str = "candidate_identity") -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise HostedAdapterError(f"{where} must be an object")
    missing = [key for key in IDENTITY_KEYS if key not in value]
    if missing:
        raise HostedAdapterError(f"{where} is missing: {', '.join(missing)}")
    result = {key: _string(value[key], f"{where}.{key}") for key in IDENTITY_KEYS}
    if not _COMMIT.fullmatch(result["commit_sha"]):
        raise HostedAdapterError(f"{where}.commit_sha must be lowercase hexadecimal")
    if not _DIGEST.fullmatch(result["artifact_digest"]):
        raise HostedAdapterError(f"{where}.artifact_digest must be sha256")
    return result


@dataclass(frozen=True)
class CredentialReference:
    """A non-secret reference to a short-lived hosted credential."""

    provider: str
    source: str
    role_arn: str | None
    expires_at: str | None
    scopes: tuple[str, ...]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CredentialReference":
        if _secret_paths(value):
            raise HostedAdapterError("credential reference contains plaintext secret material")
        provider = _string(value.get("provider"), "credential.provider")
        source = _string(value.get("source"), "credential.source")
        if source not in _CREDENTIAL_SOURCES:
            raise HostedAdapterError(f"credential.source must be one of {sorted(_CREDENTIAL_SOURCES)}")
        role_arn = value.get("role_arn")
        if role_arn is not None:
            role_arn = _string(role_arn, "credential.role_arn")
        expires_at = value.get("expires_at")
        if expires_at is not None:
            expires_at = _string(expires_at, "credential.expires_at")
            try:
                datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise HostedAdapterError("credential.expires_at must be ISO-8601") from exc
        scopes = value.get("scopes", [])
        if not isinstance(scopes, list) or not all(isinstance(item, str) and item for item in scopes):
            raise HostedAdapterError("credential.scopes must be a list of non-empty strings")
        return cls(provider, source, role_arn, expires_at, tuple(sorted(set(scopes))))

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source": self.source,
            **({"role_arn": self.role_arn} if self.role_arn else {}),
            **({"expires_at": self.expires_at} if self.expires_at else {}),
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class HostedAdapterRequest:
    operation_id: str
    authority: str
    profile: str
    credential: CredentialReference | None
    candidate_identity: dict[str, str] | None
    read_only: bool = True
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HostedAdapterRequest":
        if not isinstance(value, Mapping):
            raise HostedAdapterError("adapter request must be an object")
        if _secret_paths(value):
            raise HostedAdapterError("adapter request contains plaintext secret material")
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise HostedAdapterError("schema_version must be 1")
        operation_id = _string(value.get("operation_id"), "operation_id")
        authority = _string(value.get("authority"), "authority")
        if authority not in _AUTHORITIES:
            raise HostedAdapterError(f"authority must be one of {sorted(_AUTHORITIES)}")
        profile = _string(value.get("profile"), "profile")
        raw_credential = value.get("credential")
        credential = CredentialReference.from_mapping(raw_credential) if raw_credential is not None else None
        raw_identity = value.get("candidate_identity")
        identity = _identity(raw_identity) if raw_identity is not None else None
        if identity is not None and identity["profile"] != profile:
            raise HostedAdapterError("candidate_identity.profile must match request profile")
        read_only = value.get("read_only", True)
        if not isinstance(read_only, bool):
            raise HostedAdapterError("read_only must be boolean")
        if authority in {"environment", "iam", "state"} and credential is None:
            raise HostedAdapterError(f"{authority} adapter requires a credential reference")
        if not read_only and authority not in {"environment", "state", "release"}:
            raise HostedAdapterError("only environment/state/release adapters may request mutation")
        return cls(operation_id, authority, profile, credential, identity, read_only, SCHEMA_VERSION)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "authority": self.authority,
            "profile": self.profile,
            "read_only": self.read_only,
            **({"credential": self.credential.as_dict()} if self.credential else {}),
            **({"candidate_identity": self.candidate_identity} if self.candidate_identity else {}),
        }


@dataclass(frozen=True)
class HostedAdapterResult:
    operation_id: str
    authority: str
    profile: str
    status: str
    source: str
    mutation_occurred: bool
    retryable: bool
    payload: Mapping[str, Any]
    candidate_identity: dict[str, str] | None = None
    evidence_ref: str | None = None
    next_action: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "HostedAdapterResult":
        if not isinstance(value, Mapping):
            raise HostedAdapterError("adapter result must be an object")
        if _secret_paths(value):
            raise HostedAdapterError("adapter result contains plaintext secret material")
        if value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise HostedAdapterError("schema_version must be 1")
        status = _string(value.get("status"), "status")
        if status not in _STATUSES:
            raise HostedAdapterError(f"status must be one of {sorted(_STATUSES)}")
        source = _string(value.get("source"), "source")
        if source not in _SOURCES:
            raise HostedAdapterError(f"source must be one of {sorted(_SOURCES)}")
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise HostedAdapterError("payload must be an object")
        identity = value.get("candidate_identity")
        parsed_identity = _identity(identity) if identity is not None else None
        mutation = value.get("mutation_occurred", False)
        retryable = value.get("retryable", False)
        if not isinstance(mutation, bool) or not isinstance(retryable, bool):
            raise HostedAdapterError("mutation_occurred and retryable must be boolean")
        return cls(
            _string(value.get("operation_id"), "operation_id"),
            _string(value.get("authority"), "authority"),
            _string(value.get("profile"), "profile"),
            status,
            source,
            mutation,
            retryable,
            dict(payload),
            parsed_identity,
            value.get("evidence_ref"),
            value.get("next_action"),
            SCHEMA_VERSION,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "authority": self.authority,
            "profile": self.profile,
            "status": self.status,
            "source": self.source,
            "mutation_occurred": self.mutation_occurred,
            "retryable": self.retryable,
            "payload": dict(self.payload),
            **({"candidate_identity": self.candidate_identity} if self.candidate_identity else {}),
            **({"evidence_ref": self.evidence_ref} if self.evidence_ref else {}),
            **({"next_action": self.next_action} if self.next_action else {}),
        }


def validate_result_for_request(request: HostedAdapterRequest, result: HostedAdapterResult) -> list[str]:
    """Validate adapter provenance and candidate binding without performing I/O."""

    errors: list[str] = []
    if result.operation_id != request.operation_id:
        errors.append("operation_id does not match request")
    if result.authority != request.authority:
        errors.append("authority does not match request")
    if result.profile != request.profile:
        errors.append("profile does not match request")
    if request.read_only and result.mutation_occurred:
        errors.append("read-only request returned mutation_occurred=true")
    if request.candidate_identity and result.candidate_identity != request.candidate_identity:
        errors.append("candidate_identity does not match request")
    if result.source == "offline_fixture" and result.status == "PASS" and result.authority in {"environment", "iam", "state", "runtime"}:
        errors.append("offline fixture cannot claim live hosted PASS")
    if result.status == "BLOCKED" and not result.next_action:
        errors.append("blocked adapter result requires next_action")
    return sorted(set(errors))


def validate_adapter_pair(request_data: Mapping[str, Any], result_data: Mapping[str, Any]) -> list[str]:
    try:
        request = HostedAdapterRequest.from_mapping(request_data)
        result = HostedAdapterResult.from_mapping(result_data)
    except HostedAdapterError as exc:
        return [str(exc)]
    return validate_result_for_request(request, result)


__all__ = [
    "CredentialReference",
    "HostedAdapterError",
    "HostedAdapterRequest",
    "HostedAdapterResult",
    "validate_adapter_pair",
    "validate_result_for_request",
]
