"""Operational runbooks + incident classification for the AETHER model runtime.

ADR-008 D8: the harness ships runbooks (operational playbooks) for common
incidents — provider outage, circuit open, credential rotation, verification
block, budget exceeded, misconfiguration fail-closed. Runbooks are data plus a
resolution DSL (``steps`` is a sequence of generic ops instructions), not
prose-only.

Security invariant: runbook steps NEVER contain credentials or credential-shaped
literals (API keys, tokens, passwords, bearer headers). Steps are generic ops
instructions; they may reference the "secret backend" as a noun, but never carry
secret values.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Runbook(BaseModel, frozen=True):
    """A single operational playbook for a class of incidents.

    ``apply_to`` lists the incident-type keys this runbook covers (matched by
    ``IncidentClassifier.classify`` and ``RunbookCatalog.get``). ``steps`` is an
    ordered resolution DSL: each entry is a generic ops instruction with no
    credentials, keys, or tokens.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    summary: str
    severity: Literal["info", "warning", "critical"]
    steps: tuple[str, ...]
    apply_to: tuple[str, ...]


# ---------------------------------------------------------------------------
# Default catalog (ADR-008 D8 incident types)
# ---------------------------------------------------------------------------

_DEFAULT_RUNBOOKS: tuple[Runbook, ...] = (
    Runbook(
        id="provider_outage",
        title="Provider outage response",
        summary="Respond to a model provider outage or sustained error spike.",
        severity="critical",
        steps=(
            "Verify the incident on the provider status page before acting.",
            "Confirm the error rate and affected models from runtime metrics.",
            "Identify alternative configured providers for the affected models.",
            "Enable fallback routing and re-run the readiness probe.",
            "Escalate to on-call if the outage exceeds the SLO window.",
        ),
        apply_to=("provider_outage",),
    ),
    Runbook(
        id="circuit_open",
        title="Circuit breaker recovery",
        summary="Recover a model-runtime circuit that tripped open.",
        severity="warning",
        steps=(
            "Inspect the circuit breaker state and recent error rate.",
            "Confirm the underlying provider health before reopening.",
            "Allow the cooldown period or reset once the error rate drops.",
            "Re-run the readiness probe and watch for a half-open transition.",
        ),
        apply_to=("circuit_open",),
    ),
    Runbook(
        id="credential_rotation",
        title="Credential rotation follow-through",
        summary="Complete and verify a model-provider credential rotation.",
        severity="warning",
        steps=(
            "Confirm rotation completed in the secret backend.",
            "Verify the runtime picks up the new credential on next read.",
            "Re-run the readiness probe to confirm authentication passes.",
            "Record rotation completion and expiry in the operations log.",
        ),
        apply_to=("credential_rotation",),
    ),
    Runbook(
        id="verification_block",
        title="Verification block resolution",
        summary="Clear a blocked verification check on an account or provider.",
        severity="warning",
        steps=(
            "Review the verification decision and the blocked reason.",
            "Confirm the account details are current and accurate.",
            "Re-submit the verification check once details are corrected.",
            "Re-run the readiness probe and monitor for recurrence.",
        ),
        apply_to=("verification_block",),
    ),
    Runbook(
        id="budget_exceeded",
        title="Budget exceeded response",
        summary="Respond when a token or spend budget blocks model calls.",
        severity="critical",
        steps=(
            "Confirm which budget was exceeded from runtime metrics.",
            "Identify the top-costing calls and the largest consumers.",
            "Adjust the budget, throttle, or add capacity as approved.",
            "Re-run the readiness probe to confirm calls resume.",
        ),
        apply_to=("budget_exceeded",),
    ),
    Runbook(
        id="misconfigured_failclosed",
        title="Misconfiguration fail-closed recovery",
        summary="Restore configuration and exit fail-closed mode.",
        severity="critical",
        steps=(
            "Restore the configuration from the last known-good version.",
            "Confirm provider credentials and required settings are present.",
            "Re-run the readiness probe to verify all checks pass.",
            "Remove the fail-closed override once readiness is green.",
        ),
        apply_to=("misconfigured_failclosed",),
    ),
)


class RunbookCatalog:
    """Catalog of runbooks keyed by incident type.

    Builds an index over each runbook's ``apply_to`` keys so ``get`` is a
    deterministic O(1) lookup. ``get`` raises ``KeyError`` for incident types
    the catalog does not cover.
    """

    def __init__(self, runbooks: Sequence[Runbook] | None = None) -> None:
        if runbooks is None:
            runbooks = _DEFAULT_RUNBOOKS
        self._runbooks: tuple[Runbook, ...] = tuple(runbooks)
        self._by_type: dict[str, Runbook] = {}
        for runbook in self._runbooks:
            for incident_type in runbook.apply_to:
                self._by_type[incident_type] = runbook

    def get(self, incident_type: str) -> Runbook:
        """Return the runbook for ``incident_type`` or raise KeyError."""
        try:
            return self._by_type[incident_type]
        except KeyError:
            raise KeyError(f"no runbook for incident type {incident_type!r}") from None

    def all(self) -> tuple[Runbook, ...]:
        """Return every runbook in the catalog."""
        return self._runbooks


class IncidentClassifier:
    """Classify an incident from operational signals.

    Deterministic precedence (highest first): misconfigured_failclosed
    (``config_ok`` is False) -> circuit_open -> provider_outage (``provider_errors``
    >= threshold) -> credential_rotation (``credential_missing``) ->
    budget_exceeded (``budget_exceeded``) -> verification_block
    (``verification_failures`` >= threshold) -> "ok".
    """

    PROVIDER_ERROR_THRESHOLD = 5
    VERIFICATION_FAILURE_THRESHOLD = 3

    @classmethod
    def classify(
        cls,
        *,
        provider_errors: int,
        circuit_open: bool,
        credential_missing: bool,
        verification_failures: int,
        budget_exceeded: bool,
        config_ok: bool,
    ) -> str:
        """Return the highest-precedence incident type, or ``"ok"``."""
        if not config_ok:
            return "misconfigured_failclosed"
        if circuit_open:
            return "circuit_open"
        if provider_errors >= cls.PROVIDER_ERROR_THRESHOLD:
            return "provider_outage"
        if credential_missing:
            return "credential_rotation"
        if budget_exceeded:
            return "budget_exceeded"
        if verification_failures >= cls.VERIFICATION_FAILURE_THRESHOLD:
            return "verification_block"
        return "ok"


def recommend(incident_type: str, catalog: RunbookCatalog | None = None) -> Runbook:
    """Return the runbook for ``incident_type`` (default catalog when omitted)."""
    if catalog is None:
        catalog = RunbookCatalog()
    return catalog.get(incident_type)
