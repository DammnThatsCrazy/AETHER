"""Canonical ActorRef (WO-010).

One actor reference shared by decisions, relationships, journeys, Value and
Risk. It does not replace the identity subject model: it is a typed pointer
derived from the identifiers ingestion already carries (``SubjectRef``
identifier types) and from resolved canonical entities. Two equal raw values
in different namespaces are different actors until the resolver says
otherwise, so the namespace is part of the identity.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

from shared.observation.envelope import IDENTIFIER_TYPES

ACTOR_TYPES: tuple[str, ...] = (
    "human", "agent", "organization", "service", "protocol", "device", "unknown",
)

# SubjectRef identifier type -> actor type. A wallet or an account is
# something an actor controls, not an actor kind, so it stays "unknown" until
# the resolver links it to a typed subject.
IDENTIFIER_ACTOR_TYPE: dict[str, str] = {
    "anonymous_id": "human",
    "user_id": "human",
    "email_hash": "human",
    "phone_hash": "human",
    "organization_user_id": "human",
    "external_customer_id": "human",
    "agent_id": "agent",
    "service_account_id": "service",
    "device_id": "device",
    "session_id": "unknown",
    "account_id": "unknown",
    "wallet_address": "unknown",
    "provider_account_id": "unknown",
}
assert set(IDENTIFIER_ACTOR_TYPE) == set(IDENTIFIER_TYPES), "identifier vocabulary drifted"

# Fixed namespace so ActorRef IDs are stable across processes and replays.
_ACTOR_NS = uuid.UUID("6b6a3c1e-2f0c-5d7e-9a51-a0e0be400000")


@dataclass(frozen=True)
class ActorRef:
    tenant_id: str
    actor_id: str
    actor_type: str
    namespace: str
    source_value: str
    resolved_entity_id: Optional[str] = None
    basis: str = "observed"

    def __post_init__(self) -> None:
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(f"unknown actor_type {self.actor_type!r}")
        if not self.tenant_id:
            raise ValueError("ActorRef is tenant scoped")
        if self.basis not in {"observed", "declared", "resolved", "inferred", "unknown"}:
            raise ValueError(f"unknown basis {self.basis!r}")
        if self.resolved_entity_id and self.basis != "resolved":
            raise ValueError("a resolved entity id requires basis 'resolved'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "namespace": self.namespace,
            "source_value": self.source_value,
            "resolved_entity_id": self.resolved_entity_id,
            "basis": self.basis,
        }


def actor_id_for(tenant_id: str, namespace: str, actor_type: str, value: str) -> str:
    return str(uuid.uuid5(_ACTOR_NS, f"{tenant_id}\x1f{namespace}\x1f{actor_type}\x1f{value}"))


def actor_ref(
    tenant_id: str,
    actor_type: str,
    value: str,
    *,
    namespace: str,
    basis: str = "observed",
    resolved_entity_id: Optional[str] = None,
) -> ActorRef:
    value = (value or "").strip()
    if not value:
        raise ValueError("actor value is required")
    return ActorRef(
        tenant_id=tenant_id,
        actor_id=actor_id_for(tenant_id, namespace, actor_type, value),
        actor_type=actor_type,
        namespace=namespace,
        source_value=value,
        resolved_entity_id=resolved_entity_id,
        basis=basis,
    )


def actor_ref_from_identifier(
    tenant_id: str, identifier_type: str, value: str, *, namespace: str,
) -> ActorRef:
    """ActorRef for a SubjectRef-style identifier, without resolving it."""
    if identifier_type not in IDENTIFIER_ACTOR_TYPE:
        raise ValueError(f"unknown identifier_type {identifier_type!r}")
    return actor_ref(tenant_id, IDENTIFIER_ACTOR_TYPE[identifier_type], value,
                     namespace=f"{namespace}:{identifier_type}")


def resolved_actor_ref(tenant_id: str, entity_id: str, actor_type: str) -> ActorRef:
    """ActorRef for a canonical entity the identity resolver already owns."""
    return actor_ref(tenant_id, actor_type, entity_id, namespace="canonical",
                     basis="resolved", resolved_entity_id=entity_id)


def agent_namespace(deployment_id: Optional[str]) -> str:
    """Agent refs are scoped by the deployment that reported them; refs with no
    validated deployment stay in a separate source-reported namespace."""
    return f"deployment:{deployment_id}" if deployment_id else "source_reported"
