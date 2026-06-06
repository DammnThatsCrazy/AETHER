---
title: Noesis Production Security Checklist
slug: internal/noesis-security-checklist
section: security
visibility: I
audience: [dev-senior, security]
status: production
---

# Noesis Production Security Checklist

## Tenant Isolation

- [x] Aether surface always uses authenticated tenant_id; cross-tenant requests rejected
- [x] Kyber cross-tenant requires operator permission (admin or kyber:read)
- [x] Repository filters applied with effective_tenant_id before query execution
- [x] Graph neighbor results filtered by tenant_id
- [x] Graph edges filtered to visible (tenant-scoped) node set
- [x] LLM-generated plans cannot override tenant scope
- [x] Error messages do not reveal other tenants' data
- [x] Fallback responses do not leak cross-tenant information
- [x] Tests: cross_tenant_aether_blocked, cross_tenant_kyber_non_operator_blocked, cross_tenant_kyber_operator_allowed

## Read-Only Enforcement

- [x] All dispatchers use read-only repository methods (find_many, find_by_id, count)
- [x] No mutation methods (create, update, delete) called from dispatch path
- [x] Write-like keywords in prompts rejected at safety layer
- [x] _assert_read_only() validates plan intent before dispatch
- [x] Plan filter values checked for mutation keywords
- [x] Tests: write_prompt_rejected (delete, export, modify, mutate, execute, issue)

## Prompt Safety

- [x] WRITE_LIKE_KEYWORDS checked as main verbs (not adjectives like "deleted alerts")
- [x] INJECTION_PATTERNS checked against message content
- [x] Rejected prompts return safe NoesisResponse (no raise, no leak)
- [x] All rejections logged with metrics (noesis_safety_reject)
- [x] Tests: injection_prompt_rejected (ignore previous, system prompt, jailbreak, developer mode)

## LLM Provider Security

- [x] Provider disabled by default (NOESIS_LLM_ENABLED=false)
- [x] Provider returns only structured QueryPlan, never raw SQL/GraphQL/Gremlin
- [x] Provider plan validated: intent allowlisted, tenant unchanged, filters supported
- [x] Provider plan limit clamped to MAX_LIMIT (50)
- [x] Provider plan time range capped at 90 days
- [x] Unsafe patterns (sql, graphql, gremlin, cypher, mutation, drop, truncate) rejected at provider level
- [x] Provider timeout configurable (NOESIS_LLM_TIMEOUT_MS, default 5000ms)
- [x] Provider token limit configurable (NOESIS_LLM_MAX_TOKENS, default 512)
- [x] ProductionNoesisPlanProvider with double-validation (provider-level + service-level)
- [x] Deterministic fallback if provider fails or returns None
- [x] Tests: llm_plan_cannot_change_tenant, llm_plan_unsupported_intent_rejected, llm_plan_mutation_intent_rejected, llm_plan_unbounded_limit_clamped

## Data Redaction

- [x] Core secrets redacted: api_key, key_hash, secret, token, password, credentials
- [x] Extended secrets redacted: authorization, session_token, refresh_token, private_key, connection_string, oauth_token, webhook_secret, x_api_key
- [x] Case-insensitive key matching in _redact_deep()
- [x] Recursive redaction across nested dicts and lists
- [x] query_debug stripped for non-operator contexts (Aether surface)
- [x] Tests: secrets_redacted_from_response, expanded_secrets_redacted

## RBAC

- [x] read permission required for all queries
- [x] Tenant summary restricted to Kyber surface
- [x] Debug details restricted to operator contexts
- [x] Cross-tenant restricted to admin/operator roles
- [x] Tests: debug_hidden_from_aether_tenant, debug_visible_to_kyber_operator, tenant_summary_from_aether_forbidden

## Observability

- [x] Every query produces a NoesisAuditEntry with structured logging
- [x] Audit fields: request_id, user_id, tenant_id, requested_tenant_id, effective_tenant_id, surface, role, permissions, intent, mode, result_count, debug_returned, fallback_triggered, provider_used, rejected, rejection_reason, correlation_id, timestamp
- [x] Metrics: noesis_query (surface/intent/mode), noesis_safety_reject (reason), noesis_audit (intent/mode/surface), noesis_rejected (reason)
- [x] Request IDs and correlation IDs propagated in headers and logs
- [x] Rate limit headers included (placeholder values)

## Feature Flags & Kill Switches

- [x] NOESIS_ENABLED — master kill-switch
- [x] NOESIS_LLM_ENABLED — provider kill-switch (default off)
- [x] NOESIS_DEBUG_ENABLED — debug output kill-switch
- [x] NOESIS_CROSS_TENANT_ENABLED — cross-tenant kill-switch
- [x] NOESIS_CANARY_TENANTS — staged rollout tenant allowlist
- [x] NOESIS_RATE_LIMIT_QPM — per-tenant rate limit
- [x] NOESIS_DAILY_QUOTA — daily quota
- [x] NOESIS_PROVIDER_TOKEN_BUDGET — LLM token budget
- [x] All flags readable from environment without restart (NoesisFlags class)

## API Contract

- [x] Response shape validated by Pydantic models (NoesisResponse, QueryPlan, NoesisAuditEntry)
- [x] Frontend response validated by Zod schemas (noesisResponsePayloadSchema)
- [x] Structured error responses with request_id on 400/403/500
- [x] Rate limit headers present (x-ratelimit-limit, remaining, reset)
- [x] Conversation store NOT wired into GA query path (deferred)
- [x] conversation_id accepted but not persisted or returned

## Conversation Storage (Deferred)

- [x] Conversation persistence not wired into production query path
- [x] NoesisConversationStore exists but is not used in GA
- [x] Frontend does not imply saved history
- [ ] Formal data retention policy (pending legal/compliance review when conversations enabled)

## Pending Items

- [ ] Production rate limiting implementation (infrastructure dependency)
- [ ] Quota enforcement per tenant (infrastructure dependency)
- [ ] Provider data processing terms (pending legal review when LLM enabled)
- [ ] External provider training opt-out confirmation (pending provider selection)
- [ ] Formal data retention policy sign-off
