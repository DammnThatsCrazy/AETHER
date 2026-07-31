"""Typed deployment contract (§14).

Each entry under ``capabilities:`` in
``docs/integration-control-plane/DEPLOYMENT_CONTRACT.yaml`` declares what a
deployment operator must supply for a capability to run turnkey — no
application code change. :class:`DeploymentContract` is the typed schema those
entries conform to, and :func:`load_capability` validates a raw mapping into
one.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeploymentContractError(ValueError):
    """Raised when a capability entry cannot be validated into a contract."""


class DeploymentContract(BaseModel):
    """Deployment requirements for one capability (§14 shape)."""

    model_config = ConfigDict(extra="forbid")

    application_code_ready: bool
    required_services: list[str] = Field(default_factory=list)
    required_public_urls: list[str] = Field(default_factory=list)
    required_secrets: list[str] = Field(default_factory=list)
    provider_registration_steps: list[str] = Field(default_factory=list)
    deployment_blockers: list[str] = Field(default_factory=list)
    migration: Optional[str] = None


def load_capability(data: dict[str, Any]) -> DeploymentContract:
    """Validate a raw capability mapping into a :class:`DeploymentContract`.

    Raises :class:`DeploymentContractError` on any type/shape violation
    (including unexpected keys, since the schema forbids extras).
    """
    if not isinstance(data, dict):
        raise DeploymentContractError(
            f"capability entry must be a mapping, got {type(data)!r}"
        )
    try:
        return DeploymentContract.model_validate(data)
    except Exception as exc:  # pydantic ValidationError -> typed contract error
        raise DeploymentContractError(str(exc)) from exc


__all__ = [
    "DeploymentContract",
    "DeploymentContractError",
    "load_capability",
]
