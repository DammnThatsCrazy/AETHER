"""Silver projector for identity lifecycle events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_IDENTITY_TYPES = frozenset({
    "signup_started",
    "signup_completed",
    "login_succeeded",
    "login_failed",
    "logout_observed",
    "sso_observed",
    "mfa_challenge_observed",
    "identity_verified",
    "alias_link_requested",
    "alias_link_confirmed",
    "alias_revoked",
    "account_recovery_started",
    "account_recovery_completed",
    "device_registered",
    "device_revoked",
})


class IdentityEvidenceProjector(BaseProjector):
    handles = _IDENTITY_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "event_kind": event["type"],
            "identity_method": p.get("method") or p.get("provider"),
            "mfa_type": p.get("mfaType"),
            "device_id": p.get("deviceId"),
            "confidence": p.get("confidence"),
            "linked_actor_id": p.get("linkedActorId"),
        })
        return ProjectionResult(table="silver_identity_evidence_facts", rows=[row])
