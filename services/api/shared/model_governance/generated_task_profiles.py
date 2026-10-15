# DO NOT EDIT — generated from packages/shared/contracts/task-profile-registry.json
# Run: python scripts/generate_platform_contracts.py
"""Generated harness task-profile registry (roles, routing, guardrails, bounds)."""

from __future__ import annotations

from typing import Any

TASK_PROFILE_REGISTRY_VERSION = "1.0.0"

# Model role a task profile binds.
MODEL_ROLES: tuple[str, ...] = (
    "planning",
    "reasoning",
    "classification",
    "synthesis",
    "summarization",
    "extraction",
)

# Routing modes available to a task profile.
ROUTING_MODES: tuple[str, ...] = ("auto", "tenant_default", "explicit", "policy_required")

# Guardrail kinds a task profile may require.
GUARDRAIL_KINDS: tuple[str, ...] = (
    "read_only",
    "tenant_scope",
    "allowlist_plan",
    "no_write_keywords",
    "no_injection",
    "redaction",
    "freshness_bounded",
    "evidence_required",
)

# Output kinds a task profile may produce.
OUTPUT_KINDS: tuple[str, ...] = (
    "query_plan",
    "grounded_answer",
    "classification",
    "evidence_set",
    "structured_json",
)

# Canonical task profiles (JSON file order).
TASK_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "profileId": "noesis_query_planning",
        "version": 1,
        "purpose": "Deterministic, allowlisted text-to-query planning for the Noesis read-only runtime.",
        "modelRole": "planning",
        "defaultRoutingMode": "auto",
        "allowedRoutingModes": ("auto", "tenant_default", "explicit"),
        "outputKind": "query_plan",
        "guardrails": ("read_only", "tenant_scope", "allowlist_plan", "no_write_keywords", "no_injection"),
        "evidenceRequired": False,
        "maxTokens": 512,
        "timeoutMs": 5000,
        "maxRetries": 1,
    },
    {
        "profileId": "grounded_answer_synthesis",
        "version": 1,
        "purpose": "Grounded, evidence-cited answer synthesis over Aether-retrieved context.",
        "modelRole": "synthesis",
        "defaultRoutingMode": "auto",
        "allowedRoutingModes": ("auto", "tenant_default", "explicit"),
        "outputKind": "grounded_answer",
        "guardrails": ("read_only", "tenant_scope", "evidence_required", "redaction", "no_injection"),
        "evidenceRequired": True,
        "maxTokens": 1024,
        "timeoutMs": 10000,
        "maxRetries": 1,
    },
    {
        "profileId": "entity_classification",
        "version": 1,
        "purpose": "Structured classification of an entity or input against a tenant-policy-driven taxonomy.",
        "modelRole": "classification",
        "defaultRoutingMode": "explicit",
        "allowedRoutingModes": ("auto", "tenant_default", "explicit"),
        "outputKind": "classification",
        "guardrails": ("tenant_scope", "no_injection"),
        "evidenceRequired": False,
        "maxTokens": 256,
        "timeoutMs": 5000,
        "maxRetries": 1,
    },
    {
        "profileId": "evidence_summarization",
        "version": 1,
        "purpose": "Compact summarization of a bounded Aether evidence set with source references preserved.",
        "modelRole": "summarization",
        "defaultRoutingMode": "auto",
        "allowedRoutingModes": ("auto", "tenant_default", "explicit"),
        "outputKind": "structured_json",
        "guardrails": ("read_only", "tenant_scope", "redaction", "freshness_bounded"),
        "evidenceRequired": True,
        "maxTokens": 768,
        "timeoutMs": 8000,
        "maxRetries": 1,
    },
)

__all__ = [
    "TASK_PROFILE_REGISTRY_VERSION",
    "MODEL_ROLES",
    "ROUTING_MODES",
    "GUARDRAIL_KINDS",
    "OUTPUT_KINDS",
    "TASK_PROFILES",
]
