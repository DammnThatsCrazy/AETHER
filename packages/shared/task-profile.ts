/**
 * DO NOT EDIT — generated from packages/shared/contracts/task-profile-registry.json
 * Run: python scripts/generate_platform_contracts.py
 */

export const taskProfileRegistryVersion = '1.0.0' as const;

/** Model role a task profile binds. */
export const modelRoles = [
  'planning',
  'reasoning',
  'classification',
  'synthesis',
  'summarization',
  'extraction',
] as const;
export type ModelRole = typeof modelRoles[number];

/** Routing modes available to a task profile. */
export const routingModes = ['auto', 'tenant_default', 'explicit', 'policy_required'] as const;
export type RoutingMode = typeof routingModes[number];

/** Guardrail kinds a task profile may require. */
export const guardrailKinds = [
  'read_only',
  'tenant_scope',
  'allowlist_plan',
  'no_write_keywords',
  'no_injection',
  'redaction',
  'freshness_bounded',
  'evidence_required',
] as const;
export type GuardrailKind = typeof guardrailKinds[number];

/** Output kinds a task profile may produce. */
export const outputKinds = [
  'query_plan',
  'grounded_answer',
  'classification',
  'evidence_set',
  'structured_json',
] as const;
export type OutputKind = typeof outputKinds[number];

/** Canonical task profiles (JSON file order). */
export const taskProfiles = [
  {
    profileId: 'noesis_query_planning',
    version: 1,
    purpose: 'Deterministic, allowlisted text-to-query planning for the Noesis read-only runtime.',
    modelRole: 'planning',
    defaultRoutingMode: 'auto',
    allowedRoutingModes: ['auto', 'tenant_default', 'explicit'],
    outputKind: 'query_plan',
    guardrails: ['read_only', 'tenant_scope', 'allowlist_plan', 'no_write_keywords', 'no_injection'],
    evidenceRequired: false,
    maxTokens: 512,
    timeoutMs: 5000,
    maxRetries: 1,
  },
  {
    profileId: 'grounded_answer_synthesis',
    version: 1,
    purpose: 'Grounded, evidence-cited answer synthesis over Aether-retrieved context.',
    modelRole: 'synthesis',
    defaultRoutingMode: 'auto',
    allowedRoutingModes: ['auto', 'tenant_default', 'explicit'],
    outputKind: 'grounded_answer',
    guardrails: ['read_only', 'tenant_scope', 'evidence_required', 'redaction', 'no_injection'],
    evidenceRequired: true,
    maxTokens: 1024,
    timeoutMs: 10000,
    maxRetries: 1,
  },
  {
    profileId: 'entity_classification',
    version: 1,
    purpose: 'Structured classification of an entity or input against a tenant-policy-driven taxonomy.',
    modelRole: 'classification',
    defaultRoutingMode: 'explicit',
    allowedRoutingModes: ['auto', 'tenant_default', 'explicit'],
    outputKind: 'classification',
    guardrails: ['tenant_scope', 'no_injection'],
    evidenceRequired: false,
    maxTokens: 256,
    timeoutMs: 5000,
    maxRetries: 1,
  },
  {
    profileId: 'evidence_summarization',
    version: 1,
    purpose: 'Compact summarization of a bounded Aether evidence set with source references preserved.',
    modelRole: 'summarization',
    defaultRoutingMode: 'auto',
    allowedRoutingModes: ['auto', 'tenant_default', 'explicit'],
    outputKind: 'structured_json',
    guardrails: ['read_only', 'tenant_scope', 'redaction', 'freshness_bounded'],
    evidenceRequired: true,
    maxTokens: 768,
    timeoutMs: 8000,
    maxRetries: 1,
  },
] as const;
