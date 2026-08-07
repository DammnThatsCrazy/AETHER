"""Capability lifecycle authority — machine-enforced, persisted, evidence-based.

The single runtime authority for promoting, demoting, suspending, resuming and
credential-event-driven transitions of a tenant capability along the canonical
``CredentialReadiness`` lifecycle. Every transition:

* must be a legal edge in ``activation_schema.TRANSITIONS`` (raise otherwise);
* must satisfy the fail-closed promotion preconditions for its target rung
  (evidence references, credential slot ACTIVE, entitlement);
* is persisted as an append-only state version recording WHO (actor_type /
  actor_id), WHY (reason), WHAT EVIDENCE (evidence_refs), the credential
  version it is bound to, and WHEN (occurred_at).

No UI or API may display a readiness state that does not come from this
authority's persisted rows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from shared.certification.readiness import CredentialReadiness as R
from shared.certification.readiness import readiness_rank
from shared.logger.logger import get_logger, metrics

from services.capabilities.activation_repository import (
    ActivationStateRepo,
    ConcurrentTransitionError,
)
from services.capabilities.activation_schema import (
    ACTIVATION_ENVIRONMENTS,
    ACTIVATION_STATE_FIELDS,
    ACTOR_TYPES,
    ENTITLEMENT_REQUIRED_FROM,
    EVIDENCE_REQUIRED_STATES,
    is_legal_transition,
)

logger = get_logger("aether.capabilities.lifecycle")


class IllegalTransitionError(ValueError):
    """The requested move is not a legal edge of the lifecycle machine."""


class PromotionPreconditionError(ValueError):
    """A fail-closed promotion requirement is not satisfied."""


# Pluggable precondition checkers (wired by later phases; every one of them
# fail-closed: an ABSENT checker denies rather than allows).
EvidenceResolver = Callable[[list[str]], Awaitable[bool]]
CredentialChecker = Callable[[str, str, str, str], Awaitable[Optional[str]]]
EntitlementChecker = Callable[[str, str, str], Awaitable[bool]]


class CapabilityLifecycleAuthority:
    """Persisted, fail-closed capability lifecycle state machine."""

    def __init__(
        self,
        repo: Optional[ActivationStateRepo] = None,
        *,
        evidence_resolver: Optional[EvidenceResolver] = None,
        credential_checker: Optional[CredentialChecker] = None,
        entitlement_checker: Optional[EntitlementChecker] = None,
    ) -> None:
        self._repo = repo or ActivationStateRepo()
        self._evidence_resolver = evidence_resolver
        self._credential_checker = credential_checker
        self._entitlement_checker = entitlement_checker

    # ── Wiring points for later phases ────────────────────────────────────
    def set_evidence_resolver(self, resolver: EvidenceResolver) -> None:
        self._evidence_resolver = resolver

    def set_credential_checker(self, checker: CredentialChecker) -> None:
        self._credential_checker = checker

    def set_entitlement_checker(self, checker: EntitlementChecker) -> None:
        self._entitlement_checker = checker

    # ── Reads ─────────────────────────────────────────────────────────────

    async def get_state(
        self, tenant_id: str, provider: str, environment: str, capability: str
    ) -> Optional[dict]:
        return await self._repo.current(tenant_id, provider, environment, capability)

    async def history(
        self, tenant_id: str, provider: str, environment: str, capability: str
    ) -> list[dict]:
        return await self._repo.history(tenant_id, provider, environment, capability)

    async def states_for_tenant(self, tenant_id: str) -> list[dict]:
        return await self._repo.current_for_tenant(tenant_id)

    async def states_all_tenants(self) -> list[dict]:
        return await self._repo.current_all()

    # ── Transitions ───────────────────────────────────────────────────────

    async def promote(
        self,
        *,
        tenant_id: str,
        provider: str,
        environment: str,
        capability: str,
        target: R,
        actor_type: str,
        actor_id: str,
        domain: str = "",
        reason: str = "",
        evidence_refs: Optional[list[str]] = None,
        credential_version_ref: Optional[str] = None,
        credential_slot: Optional[str] = None,
    ) -> dict:
        """Promote toward ``target`` with fail-closed preconditions.

        Requirements enforced here (each raises with a precise reason):
        * the move is a legal single-step edge;
        * ``target`` in EVIDENCE_REQUIRED_STATES ⇒ non-empty ``evidence_refs``
          that RESOLVE through the registered evidence resolver;
        * ``target`` at/above ENTITLEMENT_REQUIRED_FROM ⇒ the registered
          entitlement checker approves (absent checker ⇒ deny);
        * a ``credential_slot`` was declared ⇒ the registered credential
          checker returns the ACTIVE credential version for the coordinate
          (absent checker or no active version ⇒ deny), and the returned
          version is recorded as ``credential_version_ref``.
        """
        current = await self.get_state(tenant_id, provider, environment, capability)
        current_state = R(current["readiness_state"]) if current else R.CREDENTIAL_WAITING
        if readiness_rank(target) <= readiness_rank(current_state):
            raise IllegalTransitionError(
                f"promote requires an upward move: {current_state.value} -> {target.value}"
            )
        self._require_legal(current_state, target)

        if target in EVIDENCE_REQUIRED_STATES:
            refs = evidence_refs or []
            if not refs:
                raise PromotionPreconditionError(
                    f"promotion to {target.value} requires evidence references"
                )
            if self._evidence_resolver is None:
                raise PromotionPreconditionError(
                    "no evidence resolver registered — evidence cannot be verified "
                    f"(promotion to {target.value} denied)"
                )
            if not await self._evidence_resolver(refs):
                raise PromotionPreconditionError(
                    f"evidence references failed to resolve/verify: {refs}"
                )

        if readiness_rank(target) >= readiness_rank(ENTITLEMENT_REQUIRED_FROM):
            if self._entitlement_checker is None:
                raise PromotionPreconditionError(
                    "no entitlement checker registered — promotion to "
                    f"{target.value} denied (fail-closed)"
                )
            if not await self._entitlement_checker(tenant_id, provider, capability):
                raise PromotionPreconditionError(
                    f"tenant {tenant_id} is not entitled to {provider}:{capability}"
                )

        resolved_credential_ref = credential_version_ref
        if credential_slot:
            if self._credential_checker is None:
                raise PromotionPreconditionError(
                    "no credential checker registered — promotion with a declared "
                    "credential slot denied (fail-closed)"
                )
            active_version = await self._credential_checker(
                tenant_id, provider, environment, credential_slot
            )
            if not active_version:
                raise PromotionPreconditionError(
                    f"no ACTIVE credential for slot {credential_slot!r} at "
                    f"({tenant_id}, {provider}, {environment})"
                )
            resolved_credential_ref = active_version

        return await self._advance(
            current,
            tenant_id=tenant_id,
            provider=provider,
            domain=domain or (current or {}).get("domain", ""),
            environment=environment,
            capability=capability,
            target=target,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            evidence_refs=evidence_refs or [],
            credential_version_ref=resolved_credential_ref,
            kill_switch=False,
        )

    async def demote(
        self,
        *,
        tenant_id: str,
        provider: str,
        environment: str,
        capability: str,
        target: R,
        actor_type: str,
        actor_id: str,
        reason: str,
        credential_version_ref: Optional[str] = None,
    ) -> dict:
        """Demote to a lower rung or off-ramp (legal edges only)."""
        current = await self.get_state(tenant_id, provider, environment, capability)
        current_state = R(current["readiness_state"]) if current else R.CREDENTIAL_WAITING
        if readiness_rank(target) >= readiness_rank(current_state):
            raise IllegalTransitionError(
                f"demote requires a downward move: {current_state.value} -> {target.value}"
            )
        self._require_legal(current_state, target)
        return await self._advance(
            current,
            tenant_id=tenant_id,
            provider=provider,
            domain=(current or {}).get("domain", ""),
            environment=environment,
            capability=capability,
            target=target,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            evidence_refs=[],
            credential_version_ref=credential_version_ref
            or (current or {}).get("credential_version_ref"),
            kill_switch=False,
        )

    async def suspend(
        self,
        *,
        tenant_id: str,
        provider: str,
        environment: str,
        capability: str,
        actor_type: str,
        actor_id: str,
        reason: str,
        kill_switch: bool = False,
    ) -> dict:
        current = await self.get_state(tenant_id, provider, environment, capability)
        current_state = R(current["readiness_state"]) if current else R.CREDENTIAL_WAITING
        self._require_legal(current_state, R.SUSPENDED)
        return await self._advance(
            current,
            tenant_id=tenant_id,
            provider=provider,
            domain=(current or {}).get("domain", ""),
            environment=environment,
            capability=capability,
            target=R.SUSPENDED,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            evidence_refs=[],
            credential_version_ref=(current or {}).get("credential_version_ref"),
            kill_switch=kill_switch,
        )

    async def resume(
        self,
        *,
        tenant_id: str,
        provider: str,
        environment: str,
        capability: str,
        actor_type: str,
        actor_id: str,
        reason: str = "",
    ) -> dict:
        """Resume a SUSPENDED (or recover a DEGRADED) capability to the
        progression state it interrupted (``prior_state``)."""
        current = await self.get_state(tenant_id, provider, environment, capability)
        if current is None:
            raise IllegalTransitionError("nothing to resume — no persisted state")
        current_state = R(current["readiness_state"])
        if current_state not in (R.SUSPENDED, R.DEGRADED):
            raise IllegalTransitionError(
                f"resume only applies to suspended/degraded (got {current_state.value})"
            )
        prior = current.get("prior_state")
        if not prior:
            raise IllegalTransitionError("no prior state recorded to resume to")
        target = R(prior)
        self._require_legal(current_state, target)
        return await self._advance(
            current,
            tenant_id=tenant_id,
            provider=provider,
            domain=current.get("domain", ""),
            environment=environment,
            capability=capability,
            target=target,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason or f"resumed from {current_state.value}",
            evidence_refs=[],
            credential_version_ref=current.get("credential_version_ref"),
            kill_switch=False,
        )

    async def on_credential_event(
        self,
        *,
        tenant_id: str,
        provider: str,
        environment: str,
        event: str,
        credential_version_ref: Optional[str] = None,
        actor_id: str = "credential-authority",
    ) -> list[dict]:
        """Apply a credential lifecycle event to every capability bound to the
        (tenant, provider, environment) coordinate.

        * ``rotated``   → certified capabilities demote to CREDENTIAL_SUPPLIED
                          bound to the NEW credential version (re-certify);
        * ``revoked``   → everything above CREDENTIAL_WAITING demotes to REVOKED;
        * ``activated`` → CREDENTIAL_WAITING coordinates advance to
                          CREDENTIAL_SUPPLIED;
        * ``deleted``   → treated as ``revoked``.
        """
        if event not in ("rotated", "revoked", "activated", "deleted"):
            raise ValueError(f"unknown credential event {event!r}")
        outcomes: list[dict] = []
        for row in await self._repo.current_for_tenant(tenant_id):
            if row.get("provider") != provider or row.get("environment") != environment:
                continue
            state = R(row["readiness_state"])
            try:
                if event == "activated" and state == R.CREDENTIAL_WAITING:
                    outcomes.append(
                        await self._advance(
                            row,
                            tenant_id=tenant_id,
                            provider=provider,
                            domain=row.get("domain", ""),
                            environment=environment,
                            capability=row["capability"],
                            target=R.CREDENTIAL_SUPPLIED,
                            actor_type="system_worker",
                            actor_id=actor_id,
                            reason="credential activated",
                            evidence_refs=[],
                            credential_version_ref=credential_version_ref,
                            kill_switch=False,
                        )
                    )
                elif event == "rotated" and readiness_rank(state) > readiness_rank(
                    R.CREDENTIAL_SUPPLIED
                ):
                    outcomes.append(
                        await self._advance(
                            row,
                            tenant_id=tenant_id,
                            provider=provider,
                            domain=row.get("domain", ""),
                            environment=environment,
                            capability=row["capability"],
                            target=R.CREDENTIAL_SUPPLIED,
                            actor_type="system_worker",
                            actor_id=actor_id,
                            reason="credential rotated — re-certification required",
                            evidence_refs=[],
                            credential_version_ref=credential_version_ref,
                            kill_switch=False,
                        )
                    )
                elif event in ("revoked", "deleted") and readiness_rank(
                    state
                ) > readiness_rank(R.CREDENTIAL_WAITING):
                    outcomes.append(
                        await self._advance(
                            row,
                            tenant_id=tenant_id,
                            provider=provider,
                            domain=row.get("domain", ""),
                            environment=environment,
                            capability=row["capability"],
                            target=R.REVOKED,
                            actor_type="system_worker",
                            actor_id=actor_id,
                            reason=f"credential {event}",
                            evidence_refs=[],
                            credential_version_ref=credential_version_ref,
                            kill_switch=False,
                        )
                    )
            except IllegalTransitionError:
                logger.warning(
                    "credential event %s produced no legal move for %s/%s state=%s",
                    event, provider, row.get("capability"), state.value,
                )
        return outcomes

    # ── Internals ─────────────────────────────────────────────────────────

    def _require_legal(self, current: R, target: R) -> None:
        if not is_legal_transition(current, target):
            raise IllegalTransitionError(
                f"illegal lifecycle transition {current.value} -> {target.value}"
            )

    async def _advance(
        self,
        prior_row: Optional[dict],
        *,
        tenant_id: str,
        provider: str,
        domain: str,
        environment: str,
        capability: str,
        target: R,
        actor_type: str,
        actor_id: str,
        reason: str,
        evidence_refs: list[str],
        credential_version_ref: Optional[str],
        kill_switch: bool,
    ) -> dict:
        if actor_type not in ACTOR_TYPES:
            raise ValueError(f"unknown actor_type {actor_type!r}")
        if environment not in ACTIVATION_ENVIRONMENTS:
            raise ValueError(f"unknown environment {environment!r}")
        prior_state = prior_row.get("readiness_state") if prior_row else None
        # prior_state records the interrupted PROGRESSION state so resume()
        # restores certification level across chained off-ramps.
        resume_target = prior_state
        if prior_row and R(prior_row["readiness_state"]) in (R.SUSPENDED, R.DEGRADED):
            resume_target = prior_row.get("prior_state")
        row = {
            "tenant_id": tenant_id,
            "provider": provider,
            "domain": domain,
            "environment": environment,
            "capability": capability,
            "state_version": int((prior_row or {}).get("state_version", 0)) + 1,
            "readiness_state": target.value,
            "prior_state": resume_target if target in (R.SUSPENDED, R.DEGRADED) else prior_state,
            "credential_version_ref": credential_version_ref,
            "evidence_refs": list(evidence_refs),
            "reason": reason,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "kill_switch": kill_switch,
            "superseded": False,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        assert set(row) == set(ACTIVATION_STATE_FIELDS), "activation row shape drifted"
        stored = await self._repo.advance(prior_row, row)
        metrics.increment(
            "capability_lifecycle_transitions",
            labels={
                "to": target.value,
                "from": (prior_state or "none"),
                "actor_type": actor_type,
            },
        )
        logger.info(
            "capability transition tenant=%s provider=%s env=%s capability=%s %s->%s by %s",
            tenant_id, provider, environment, capability,
            prior_state or "none", target.value, actor_type,
        )
        return stored


_authority: Optional[CapabilityLifecycleAuthority] = None


def get_lifecycle_authority() -> CapabilityLifecycleAuthority:
    global _authority
    if _authority is None:
        _authority = CapabilityLifecycleAuthority()
    return _authority


def reset_lifecycle_authority() -> None:
    global _authority
    _authority = None


__all__ = [
    "CapabilityLifecycleAuthority",
    "ConcurrentTransitionError",
    "IllegalTransitionError",
    "PromotionPreconditionError",
    "get_lifecycle_authority",
    "reset_lifecycle_authority",
]
