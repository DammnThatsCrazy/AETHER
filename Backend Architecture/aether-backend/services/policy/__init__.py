"""Central consent PolicyDecision evidence service.

Produces an explainable, persisted decision (`policy_decision_id`) for every
sensitive collect / link / project / train / infer / export / reward / attribute
/ render / DSR / operator action, derived from the canonical consent registry and
the signal-use matrix. Mirrors — does not overload — the security/egress
`PolicyEngine`; consent decisions land in the same tamper-evident audit ledger.
"""
from services.policy.contracts import ConsentPolicyDecision, PolicyAction
from services.policy.engine import ConsentPolicyEngine, consent_policy_engine

__all__ = [
    "ConsentPolicyDecision",
    "PolicyAction",
    "ConsentPolicyEngine",
    "consent_policy_engine",
]
