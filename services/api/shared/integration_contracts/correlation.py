"""Join rules between source roles, keyed by role pair, never by vendor pair.

Each provider maps its records into canonical observations once. Aether then
joins observations from different roles with the rules below, so adding a
vendor adds one module rather than one integration per existing vendor.

Example: a Grok bot changes Shopify inventory through Shopify's AI connector,
which acts through a staff account. The system-of-record stream alone shows
the staff account as the actor. Only a join with the agent runtime or tool
bridge observation shows that an agent acted, and how strong that evidence is.

The verdict's evidence class reuses ``PRINCIPAL_EVIDENCE_CLASSES``. Only the
classes in ``PRINCIPAL_PROOF_EVIDENCE_CLASSES`` produce ``linked``; weaker
matches stay ``candidate`` (weak evidence can cluster but never prove a link).
Pairs of two systems of record are not joined here: cross-provider domain
facts (an order and its payment) belong to domain reconciliation.

This module decides; it does not persist or write the graph. A projector may
turn a ``linked`` verdict into a mutation intent through the graph gateway.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal, Mapping, Optional, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.agent_lineage.vocabulary import PRINCIPAL_PROOF_EVIDENCE_CLASSES
from shared.integration_contracts.correlation_token import TokenVerifier
from shared.integration_contracts.source_roles import SOURCE_ROLES, SourceRole


CORRELATION_CONTRACT_VERSION: Literal["1"] = "1"
DEFAULT_TIME_WINDOW = timedelta(minutes=5)
MAX_TIME_WINDOW = timedelta(hours=1)

JoinKeyKind = Literal[
    "aether_correlation_token",
    "shared_object_ref",
    "provider_signed_request",
    "provider_actor_ref",
    "infrastructure_ref",
    "time_window",
]
JOIN_KEY_KINDS: tuple[str, ...] = get_args(JoinKeyKind)

# Strongest first. The order is the tie-break when several keys match.
JOIN_KEY_EVIDENCE: Mapping[str, str] = MappingProxyType({
    "aether_correlation_token": "DETERMINISTIC_BINDING",
    "shared_object_ref": "DETERMINISTIC_BINDING",
    "provider_signed_request": "CRYPTOGRAPHICALLY_ATTESTED",
    "provider_actor_ref": "PROVIDER_ASSERTED",
    "infrastructure_ref": "INFRASTRUCTURE_CORRELATED",
    "time_window": "TEMPORALLY_CORRELATED",
})


def _pair(a: str, b: str) -> frozenset[str]:
    return frozenset((a, b))


# Which join keys are meaningful between two roles. A pair absent from this
# table has no rule and yields ``no_rule``; it never falls back to timing.
JOIN_RULES: Mapping[frozenset[str], tuple[str, ...]] = MappingProxyType({
    _pair("agent_runtime", "system_of_record"): (
        "aether_correlation_token", "shared_object_ref", "provider_actor_ref", "time_window",
    ),
    _pair("tool_bridge", "system_of_record"): (
        "aether_correlation_token", "shared_object_ref", "provider_actor_ref", "time_window",
    ),
    _pair("agent_runtime", "tool_bridge"): (
        "aether_correlation_token", "shared_object_ref", "infrastructure_ref", "time_window",
    ),
    _pair("network_observer", "agent_runtime"): (
        "aether_correlation_token", "provider_signed_request", "infrastructure_ref", "time_window",
    ),
    _pair("network_observer", "tool_bridge"): (
        "aether_correlation_token", "provider_signed_request", "infrastructure_ref", "time_window",
    ),
    _pair("network_observer", "system_of_record"): ("infrastructure_ref", "time_window"),
    _pair("authority_issuer", "agent_runtime"): (
        "aether_correlation_token", "provider_actor_ref", "time_window",
    ),
    _pair("authority_issuer", "tool_bridge"): ("aether_correlation_token", "provider_actor_ref"),
    _pair("authority_issuer", "system_of_record"): ("shared_object_ref", "provider_actor_ref"),
})

CorrelationStatus = Literal["linked", "candidate", "rejected", "no_rule"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("expected a non-empty value")
    return value


class ObservedObjectRef(_Model):
    """A provider object as an observation names it.

    Unlike ``SourceObjectRef`` this carries no account verification reference:
    an agent-side record can name an object it touched, but only the
    system-of-record stream proves the account. A match therefore requires the
    full scope: family, realm, account, object type, and object ID.
    """

    provider_family: str
    source_account_realm: Literal["live", "test"]
    source_account_key: str
    object_type: str
    object_id: str

    @field_validator("provider_family", "source_account_key", "object_type", "object_id")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        return _nonblank(value)


class SignedRequestRef(_Model):
    request_id: str
    signature_verified: bool

    @field_validator("request_id")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        return _nonblank(value)


class CorrelationObservation(_Model):
    """One canonical observation, in the shape the join rules read."""

    schema_version: Literal["1"] = CORRELATION_CONTRACT_VERSION
    tenant_id: str
    observation_id: str
    source_role: SourceRole
    provider_family: str
    occurred_at: datetime
    object_refs: tuple[ObservedObjectRef, ...] = ()
    correlation_tokens: tuple[str, ...] = Field(default=(), max_length=8)
    signed_request: Optional[SignedRequestRef] = None
    # Namespaced provider-reported actor references, e.g. an OAuth client ID
    # or staff account the provider says performed the action.
    actor_refs: tuple[str, ...] = ()
    # Namespaced infrastructure references, e.g. a gateway request ID.
    infrastructure_refs: tuple[str, ...] = ()

    @field_validator("tenant_id", "observation_id", "provider_family")
    @classmethod
    def _nonblank_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def _namespaced_refs(self) -> "CorrelationObservation":
        for ref in (*self.actor_refs, *self.infrastructure_refs):
            namespace, sep, value = ref.partition(":")
            if not sep or not namespace.strip() or not value.strip():
                raise ValueError("actor and infrastructure refs must be namespace:value")
        return self


class CorrelationVerdict(_Model):
    contract_version: Literal["1"] = CORRELATION_CONTRACT_VERSION
    status: CorrelationStatus
    evidence_class: str
    key_kind: Optional[JoinKeyKind] = None
    supporting_keys: tuple[JoinKeyKind, ...] = ()
    proves_link: bool = False
    reason: str


def join_keys_for(role_a: str, role_b: str) -> tuple[str, ...]:
    """Eligible join keys between two roles, strongest first; () if no rule."""
    for role in (role_a, role_b):
        if role not in SOURCE_ROLES:
            raise ValueError(f"unknown source role {role!r}")
    eligible = JOIN_RULES.get(_pair(role_a, role_b), ())
    return tuple(k for k in JOIN_KEY_KINDS if k in eligible)


def _verified_refs(obs: CorrelationObservation, verifier: Optional[TokenVerifier]) -> set[str]:
    """Task refs from tokens that verify for the observation's own tenant."""
    if verifier is None:
        return set()
    refs = (verifier(token, obs.tenant_id) for token in obs.correlation_tokens)
    return {ref for ref in refs if ref is not None}


def correlate(
    left: CorrelationObservation,
    right: CorrelationObservation,
    *,
    token_verifier: Optional[TokenVerifier] = None,
    time_window: timedelta = DEFAULT_TIME_WINDOW,
) -> CorrelationVerdict:
    """Decide whether two observations from different roles are the same act."""
    if time_window <= timedelta(0) or time_window > MAX_TIME_WINDOW:
        raise ValueError(f"time_window must be positive and at most {MAX_TIME_WINDOW}")
    if left.tenant_id != right.tenant_id:
        return CorrelationVerdict(
            status="rejected", evidence_class="UNKNOWN", reason="cross_tenant_join_forbidden"
        )
    if left.observation_id == right.observation_id:
        return CorrelationVerdict(status="rejected", evidence_class="UNKNOWN", reason="same_observation")
    if left.source_role == right.source_role == "system_of_record":
        return CorrelationVerdict(
            status="no_rule",
            evidence_class="UNKNOWN",
            reason="system_of_record_pairs_belong_to_domain_reconciliation",
        )
    eligible = join_keys_for(left.source_role, right.source_role)
    if not eligible:
        return CorrelationVerdict(status="no_rule", evidence_class="UNKNOWN", reason="no_join_rule_for_role_pair")

    # Object, actor, and infrastructure matches also require proximity: an
    # exact object match binds only when the effect is near the action, or an
    # agent that once read an order would bind to every later change of it.
    near = abs(left.occurred_at - right.occurred_at) <= time_window
    matched: list[str] = []

    if "aether_correlation_token" in eligible:
        left_refs = _verified_refs(left, token_verifier)
        right_refs = _verified_refs(right, token_verifier)
        if left_refs and right_refs:
            if left_refs & right_refs:
                matched.append("aether_correlation_token")
            else:
                # Both sides carry valid tokens for different tasks: this is
                # positive evidence they are different acts, not a weak match.
                return CorrelationVerdict(
                    status="rejected",
                    evidence_class="UNKNOWN",
                    reason="conflicting_correlation_tokens",
                )

    if "shared_object_ref" in eligible and near and set(left.object_refs) & set(right.object_refs):
        matched.append("shared_object_ref")

    if "provider_signed_request" in eligible:
        ls, rs = left.signed_request, right.signed_request
        if (
            ls is not None
            and rs is not None
            and ls.request_id == rs.request_id
            and (ls.signature_verified or rs.signature_verified)
        ):
            matched.append("provider_signed_request")

    if "provider_actor_ref" in eligible and near and set(left.actor_refs) & set(right.actor_refs):
        matched.append("provider_actor_ref")

    if "infrastructure_ref" in eligible and near and set(left.infrastructure_refs) & set(right.infrastructure_refs):
        matched.append("infrastructure_ref")

    if "time_window" in eligible and near:
        matched.append("time_window")

    if not matched:
        return CorrelationVerdict(status="rejected", evidence_class="UNKNOWN", reason="no_join_key_matched")

    ordered = tuple(k for k in JOIN_KEY_KINDS if k in matched)
    strongest = ordered[0]
    evidence = JOIN_KEY_EVIDENCE[strongest]
    proves = evidence in PRINCIPAL_PROOF_EVIDENCE_CLASSES
    return CorrelationVerdict(
        status="linked" if proves else "candidate",
        evidence_class=evidence,
        key_kind=strongest,  # type: ignore[arg-type]
        supporting_keys=ordered,  # type: ignore[arg-type]
        proves_link=proves,
        reason=f"matched_{strongest}",
    )

__all__ = [
    "CORRELATION_CONTRACT_VERSION",
    "CorrelationObservation",
    "CorrelationStatus",
    "CorrelationVerdict",
    "DEFAULT_TIME_WINDOW",
    "JOIN_KEY_EVIDENCE",
    "JOIN_KEY_KINDS",
    "JOIN_RULES",
    "JoinKeyKind",
    "MAX_TIME_WINDOW",
    "ObservedObjectRef",
    "SignedRequestRef",
    "correlate",
    "join_keys_for",
]
