"""Consent PolicyDecision contract — the canonical evidence record for whether a
sensitive action was allowed / denied / redacted under purpose-level policy.

Distinct from services/security PolicyDecision (access/egress). This one is
consent/purpose-shaped: it carries the required + missing purposes, the signal
type, and the consent snapshot it was evaluated against.
"""
from __future__ import annotations

import uuid
from typing import Literal, Optional

from pydantic import BaseModel, Field

from services.security.contracts import ActorType, now_iso

# Sensitive actions gated by purpose-level policy (prompt §3.1).
PolicyAction = Literal[
    "collect_event",
    "collect_signal",
    "link_identity",
    "project_graph",
    "generate_feature",
    "train_model",
    "serve_inference",
    "render_profile360",
    "export_data",
    "evaluate_reward",
    "compute_attribution",
    "run_replay",
    "run_backfill",
    "process_dsr",
    "operator_remediate",
]


class ConsentPolicyDecision(BaseModel):
    policy_decision_id: str = Field(default_factory=lambda: f"cpd_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    actor_id: str
    actor_type: ActorType = "system"
    subject_ref: Optional[str] = None
    resource_type: str
    resource_id: Optional[str] = None
    action: str
    purpose: Optional[str] = None
    signal_type: Optional[str] = None
    consent_snapshot_id: Optional[str] = None
    consent_policy_version: Optional[str] = None
    required_purposes: list[str] = Field(default_factory=list)
    missing_purposes: list[str] = Field(default_factory=list)
    granted_purposes: list[str] = Field(default_factory=list)
    allowed: bool
    denied_reason: Optional[str] = None
    redacted_fields: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)
