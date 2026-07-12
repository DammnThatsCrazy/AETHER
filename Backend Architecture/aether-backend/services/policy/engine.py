"""ConsentPolicyEngine — evaluate and record consent policy decisions.

Every sensitive path calls `decide(...)`, which:
  - resolves the exact required purpose(s) from the signal-use matrix (by signal
    type) or from the explicit purpose — never a broad-consent fallback,
  - compares against the granted purposes,
  - returns an explainable ConsentPolicyDecision (allow-with-id / deny+reason /
    redact+fields),
  - persists the decision + a tamper-evident audit-ledger entry on denial, for
    explicit opt-in purposes, or for always-evidence actions.

Mirrors services/security/policy_engine.py's _finalize idiom so consent decisions
join the same audit ledger and the existing /v1/audit export surface.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from services.policy import signal_use_matrix as matrix
from services.policy.contracts import ConsentPolicyDecision
from services.policy.repositories import ConsentPolicyDecisionRepository
from services.security.audit_ledger import audit_ledger
from services.security.contracts import ActorType, sanitize_metadata

_CONSENT_REGISTRY = (
    Path(__file__).resolve().parents[4]
    / "packages" / "shared" / "contracts" / "consent-registry.json"
)

# Actions that touch a subject's sensitive data and always warrant an evidence
# record even when allowed.
_ALWAYS_PERSIST_ACTIONS = frozenset({
    "train_model", "serve_inference", "export_data", "process_dsr",
    "operator_remediate", "render_profile360",
})


def _explicit_opt_in_purposes() -> set[str]:
    try:
        data = json.loads(_CONSENT_REGISTRY.read_text(encoding="utf-8"))
        return {p["key"] for p in data.get("purposes", []) if p.get("explicitOptInRequired")}
    except Exception:  # pragma: no cover
        return {"financial_activity", "credit", "location",
                "economic_observability", "cross_chain_observability"}


_EXPLICIT_OPT_IN = _explicit_opt_in_purposes()


class ConsentPolicyEngine:
    def __init__(self, repo: Optional[ConsentPolicyDecisionRepository] = None) -> None:
        self._repo = repo or ConsentPolicyDecisionRepository()

    async def decide(
        self,
        *,
        tenant_id: Optional[str],
        actor_id: str,
        action: str,
        resource_type: str,
        granted_purposes: Iterable[str],
        resource_id: Optional[str] = None,
        subject_ref: Optional[str] = None,
        purpose: Optional[str] = None,
        signal_type: Optional[str] = None,
        consent_snapshot_id: Optional[str] = None,
        consent_policy_version: Optional[str] = None,
        actor_type: ActorType = "system",
        redactable_fields: Optional[Iterable[str]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ConsentPolicyDecision:
        granted = set(granted_purposes or [])
        required = self._required_purposes(signal_type, purpose)
        missing = [p for p in required if p not in granted]
        allowed = not missing
        decision = ConsentPolicyDecision(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_type=actor_type,
            subject_ref=subject_ref,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            purpose=purpose,
            signal_type=signal_type,
            consent_snapshot_id=consent_snapshot_id,
            consent_policy_version=consent_policy_version,
            required_purposes=required,
            missing_purposes=missing,
            granted_purposes=sorted(granted),
            allowed=allowed,
            denied_reason=None if allowed else f"missing_consent:{','.join(missing)}",
            redacted_fields=[] if allowed else sorted(set(redactable_fields or [])),
        )
        return await self._finalize(decision, ip_address=ip_address, user_agent=user_agent)

    def _required_purposes(self, signal_type: Optional[str], purpose: Optional[str]) -> list[str]:
        # Exact purpose resolution — no broad-consent fallback.
        if signal_type and matrix.known_signal(signal_type):
            return matrix.required_purposes(signal_type)
        if purpose:
            return [purpose]
        return []

    def _is_sensitive(self, decision: ConsentPolicyDecision) -> bool:
        if decision.signal_type and matrix.explicit_opt_in_required(decision.signal_type):
            return True
        return any(p in _EXPLICIT_OPT_IN for p in decision.required_purposes)

    async def _finalize(
        self,
        decision: ConsentPolicyDecision,
        *,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> ConsentPolicyDecision:
        if (not decision.allowed) or self._is_sensitive(decision) or decision.action in _ALWAYS_PERSIST_ACTIONS:
            await self._repo.insert(decision.policy_decision_id, decision.model_dump())
            await audit_ledger.record(
                actor_id=decision.actor_id,
                actor_type=decision.actor_type,
                event_type=f"consent_policy.{decision.action}",
                resource_type=decision.resource_type,
                action=decision.action,
                outcome="allowed" if decision.allowed else "blocked",
                tenant_id=decision.tenant_id,
                resource_id=decision.resource_id,
                policy_decision_id=decision.policy_decision_id,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata=sanitize_metadata({
                    "purpose": decision.purpose,
                    "signal_type": decision.signal_type,
                    "required_purposes": decision.required_purposes,
                    "missing_purposes": decision.missing_purposes,
                }),
            )
        return decision

    async def list_decisions(self, tenant_id: str, limit: int = 100) -> list[dict]:
        return await self._repo.list_for_tenant(tenant_id, limit=limit)


consent_policy_engine = ConsentPolicyEngine()
