"""Credential-readiness truth model.

This is the *honesty* core of the credentialless certification framework. It
defines the mission-canonical readiness tokens, a lossless mapping from the
existing connector ``ImplementationStatus`` taxonomy onto those tokens, and a
``ReadinessDimensions`` record whose validators refuse to let a provider claim
more readiness than its evidence supports.

Design rules enforced here:
- ``production_ready`` is NEVER inferred from structure. It is a claim that must
  be backed by live validation + security review (+ external audit when the
  provider requires one). ``derive()`` computes only a *coarse* state and never
  turns ``production_ready`` on.
- Readiness ranks are ordered so a caller can assert "at least
  CREDENTIAL_WAITING" without accidentally accepting a DEGRADED/DISABLED
  provider — those are off-ramp states ranked below everything.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, model_validator

from services.integrations.connectors.base import ImplementationStatus


class CredentialReadiness(str, Enum):
    """Mission-canonical readiness tokens for a provider adapter.

    ``SCAFFOLDED`` is the forbidden-for-first-release marker: an adapter that is
    only a descriptor with unimplemented decode/execution paths. ``DEGRADED`` and
    ``DISABLED`` are off-ramp states — a provider that regressed or was pulled.
    """

    REPLAY_VALIDATED = "replay_validated"
    CREDENTIAL_WAITING = "credential_waiting"
    SANDBOX_VALIDATED = "sandbox_validated"
    PARTNER_LIVE = "partner_live"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    SCAFFOLDED = "scaffolded"


# Lossless projection of the existing connector taxonomy onto readiness tokens.
# Every ImplementationStatus member MUST appear here (a test asserts coverage).
IMPLEMENTATION_STATUS_TO_READINESS: dict[ImplementationStatus, CredentialReadiness] = {
    ImplementationStatus.SCAFFOLDED: CredentialReadiness.SCAFFOLDED,
    ImplementationStatus.PRODUCTION_SHAPED: CredentialReadiness.CREDENTIAL_WAITING,
    ImplementationStatus.CREDENTIAL_GATED: CredentialReadiness.CREDENTIAL_WAITING,
    ImplementationStatus.PROVIDER_LIVE: CredentialReadiness.PARTNER_LIVE,
    ImplementationStatus.WAREHOUSE_DATASHARE_READY: CredentialReadiness.CREDENTIAL_WAITING,
    ImplementationStatus.STAGING_VALIDATION_REQUIRED: CredentialReadiness.CREDENTIAL_WAITING,
    ImplementationStatus.DISABLED_COMPLIANCE_REVIEW: CredentialReadiness.DISABLED,
    ImplementationStatus.DEPRECATED: CredentialReadiness.DISABLED,
}


# Linear progression ranks. DEGRADED/DISABLED are *separate low states* ranked
# below the progression so that "rank >= CREDENTIAL_WAITING" never admits them.
_READINESS_RANK: dict[CredentialReadiness, int] = {
    CredentialReadiness.DISABLED: -2,
    CredentialReadiness.DEGRADED: -1,
    CredentialReadiness.SCAFFOLDED: 1,
    CredentialReadiness.CREDENTIAL_WAITING: 2,
    CredentialReadiness.REPLAY_VALIDATED: 3,
    CredentialReadiness.SANDBOX_VALIDATED: 4,
    CredentialReadiness.PARTNER_LIVE: 5,
}


def to_readiness(status: ImplementationStatus) -> CredentialReadiness:
    """Map an ``ImplementationStatus`` (enum member or its string value) onto a
    ``CredentialReadiness`` token. Raises ``ValueError`` for anything unmapped."""
    try:
        return IMPLEMENTATION_STATUS_TO_READINESS[status]
    except (KeyError, TypeError):
        target = getattr(status, "value", status)
        for member, readiness in IMPLEMENTATION_STATUS_TO_READINESS.items():
            if member.value == target:
                return readiness
        raise ValueError(f"no readiness mapping for implementation status {status!r}")


def readiness_rank(r: CredentialReadiness) -> int:
    """Ordinal rank for a readiness token.

    SCAFFOLDED < CREDENTIAL_WAITING < REPLAY_VALIDATED < SANDBOX_VALIDATED
    < PARTNER_LIVE. DEGRADED/DISABLED rank below all of them.
    Enables "at least CREDENTIAL_WAITING" assertions via ``>=``.
    """
    try:
        return _READINESS_RANK[r]
    except (KeyError, TypeError):
        target = getattr(r, "value", r)
        for member, rank in _READINESS_RANK.items():
            if member.value == target:
                return rank
        raise ValueError(f"no rank for readiness {r!r}")


class ReadinessDimensions(BaseModel):
    """Evidence-backed readiness record.

    Booleans describe what has actually been proven. The model validator refuses
    dishonest combinations (e.g. ``production_ready`` without live validation).
    ``state`` is the coarse readiness token; use ``derive()`` to compute it
    honestly from the dimensions rather than setting it by hand.
    """

    code_complete: bool = False
    infra_defined: bool = False
    credential_required: bool = True
    credential_supplied: bool = False
    replay_validated: bool = False
    sandbox_validated: bool = False
    live_validated: bool = False
    security_reviewed: bool = False
    externally_audited: bool = False
    requires_external_audit: bool = False
    pilot_ready: bool = False
    production_ready: bool = False
    state: CredentialReadiness = CredentialReadiness.SCAFFOLDED

    @model_validator(mode="after")
    def _enforce_honesty(self) -> "ReadinessDimensions":
        if self.production_ready:
            if not (self.live_validated and self.security_reviewed):
                raise ValueError(
                    "production_ready requires live_validated AND security_reviewed"
                )
            if self.requires_external_audit and not self.externally_audited:
                raise ValueError(
                    "production_ready requires externally_audited when "
                    "requires_external_audit is set"
                )
        if self.sandbox_validated and not self.replay_validated:
            raise ValueError("sandbox_validated implies replay_validated")
        if self.live_validated and not self.credential_supplied:
            raise ValueError("live_validated implies credential_supplied")
        if self.pilot_ready and not (
            self.code_complete and self.infra_defined and self.replay_validated
        ):
            raise ValueError(
                "pilot_ready requires code_complete AND infra_defined AND replay_validated"
            )
        return self

    @staticmethod
    def _coarse_state(d: "ReadinessDimensions") -> CredentialReadiness:
        """Coarse readiness implied by the evidence. Never returns based on the
        ``production_ready`` claim — structure does not confer production."""
        if d.live_validated:
            return CredentialReadiness.PARTNER_LIVE
        if d.sandbox_validated:
            return CredentialReadiness.SANDBOX_VALIDATED
        if d.replay_validated:
            return CredentialReadiness.REPLAY_VALIDATED
        if d.code_complete and d.infra_defined:
            return CredentialReadiness.CREDENTIAL_WAITING
        return CredentialReadiness.SCAFFOLDED

    @classmethod
    def derive(
        cls, *, state: Optional[CredentialReadiness] = None, **dimensions: bool
    ) -> "ReadinessDimensions":
        """Build a ``ReadinessDimensions`` and compute a coarse ``state`` from the
        evidence. An explicit ``state`` overrides the computed one; invariants are
        still enforced (raises ``ValueError`` on a dishonest combination)."""
        base = cls(state=CredentialReadiness.SCAFFOLDED, **dimensions)
        computed = cls._coarse_state(base)
        return base.model_copy(update={"state": state or computed})


__all__ = [
    "CredentialReadiness",
    "IMPLEMENTATION_STATUS_TO_READINESS",
    "to_readiness",
    "readiness_rank",
    "ReadinessDimensions",
]
