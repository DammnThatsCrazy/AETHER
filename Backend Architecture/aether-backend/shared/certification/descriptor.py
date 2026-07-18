"""Adapter certification descriptor — the honest, declarative capability record.

An ``AdapterCertificationDescriptor`` is what an adapter publishes about itself:
which operations it supports, what credentials/endpoints/secret-refs it needs,
how it paginates/streams, its resilience posture, and — critically — its current
``CredentialReadiness`` state. Certification checks assert against THIS record
(plus optional offline hooks), so the descriptor is the contract that keeps
readiness claims honest and reviewable without any live call.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from shared.certification.checks import CertificationCheckResult
from shared.certification.readiness import CredentialReadiness


class AdapterCertificationDescriptor(BaseModel):
    """Declared certification surface for one domain adapter.

    Fields are intentionally free-text/enumerable so the record serializes to a
    deterministic capability matrix. ``first_release`` marks a provider inside the
    first-release scope (subject to the PR7-time strict gate).
    """

    provider: str
    domain: str
    adapter: str
    adapter_version: str = "0.0.0"

    supported_operations: list[str] = Field(default_factory=list)
    unsupported_operations: list[str] = Field(default_factory=list)

    required_credentials: list[str] = Field(default_factory=list)
    required_endpoints: list[str] = Field(default_factory=list)
    secret_ref_names: list[str] = Field(default_factory=list)
    expected_webhook_headers: list[str] = Field(default_factory=list)

    pagination_model: str = "none"          # none | cursor | page | time_window
    streaming_model: str = "none"           # none | websocket | sse | webhook
    rate_limit_behavior: str = "unspecified"
    retry_policy: str = "unspecified"

    implementation_state: CredentialReadiness
    last_certified_at: Optional[str] = None
    fixture_schema_version: str = "0"
    doc_version_or_review_date: Optional[str] = None

    certification_results: list[CertificationCheckResult] = Field(default_factory=list)
    first_release: bool = False


__all__ = ["AdapterCertificationDescriptor"]
