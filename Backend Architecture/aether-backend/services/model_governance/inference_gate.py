"""InferencePolicyGate (§3.9).

Every model inference records a ``serve_inference`` consent PolicyDecision via
the canonical ``consent_policy_engine`` (so it lands in the same audit ledger and
``/v1/audit`` export as all other consent decisions). When enforcement is active
(operator switch ``ML_INFERENCE_POLICY_ENFORCE`` or the model's registry
``fail_closed_required`` flag), a subject missing the required purpose is denied;
otherwise the gate is evidence-only so enabling it never breaks live inference.
"""
from __future__ import annotations

from typing import Iterable, Optional

from services.model_governance import policy
from services.model_governance.contracts import InferenceGateResult
from services.policy.engine import consent_policy_engine


class InferencePolicyGate:
    def __init__(self, engine=consent_policy_engine) -> None:
        self._engine = engine

    async def evaluate(
        self,
        *,
        tenant_id: Optional[str],
        actor_id: str,
        model_id: str,
        granted_purposes: Iterable[str] = (),
        subject_ref: Optional[str] = None,
        required_purposes: Optional[Iterable[str]] = None,
        enforce: Optional[bool] = None,
        consent_snapshot_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> InferenceGateResult:
        required = (
            list(required_purposes)
            if required_purposes is not None
            else list(policy.serving_required_purposes(model_id))
        )
        enforced = policy.inference_enforcement(model_id, override=enforce)

        # Record one evidence decision per required purpose (or a single
        # no-purpose evidence record when the model is unscoped). The engine
        # persists serve_inference decisions unconditionally.
        decision = None
        missing: list[str] = []
        granted = set(granted_purposes or [])
        for purpose in required or [None]:
            decision = await self._engine.decide(
                tenant_id=tenant_id,
                actor_id=actor_id,
                action="serve_inference",
                resource_type="ml_model",
                resource_id=model_id,
                subject_ref=subject_ref,
                purpose=purpose,
                granted_purposes=granted,
                consent_snapshot_id=consent_snapshot_id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            if not decision.allowed:
                missing.extend(decision.missing_purposes)

        missing = sorted(set(missing))
        allowed = not missing
        blocked = enforced and not allowed
        reason = (
            f"inference_denied:missing_consent:{','.join(missing)}"
            if blocked else None
        )
        return InferenceGateResult(
            model_id=model_id,
            allowed=allowed,
            blocked=blocked,
            enforced=enforced,
            reason=reason,
            policy_decision_id=decision.policy_decision_id if decision else None,
            required_purposes=required,
            missing_purposes=missing,
            decision=decision,
        )


inference_policy_gate = InferencePolicyGate()
