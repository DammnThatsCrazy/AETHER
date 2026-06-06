---
title: Noesis Operator Runbook
slug: noesis-operator-runbook
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
---

# Noesis Operator Runbook

## What is Noesis?

Noesis is a read-only natural-language intelligence layer for querying the Aether intelligence graph. It supports both tenant users (via Aether) and internal operators (via Kyber).

## Operator Capabilities (Kyber)

Operators with `admin` or `kyber:read` permission can:
- Query any specific tenant's data by providing `tenant_id`.
- Query across all tenants using phrases like "all tenants", "across tenants".
- View `query_debug` output showing the resolved plan and validation status.
- Access tenant summaries (Kyber-only intent).

## Supported Questions

| Category | Example prompts |
|----------|----------------|
| Entity search | "Find users matching Alice", "Show me entities of type wallet" |
| Graph lookup | "What is connected to entity X?", "Show neighbors of wallet Y" |
| Alerts | "Show unresolved alerts", "What incidents are open?" |
| Tenant summary | "Summarize tenant X", "Show tenant status" |
| Profiles | "Find profile for user Z", "Show identity clusters" |
| Wallets | "Show wallet 0xABC...", "Find wallets for this user" |
| Agents | "Show agent configurations", "Which agents are active?" |
| Health | "Show SDK telemetry health", "What's failing?", "Show unhealthy providers" |
| Campaigns/Rewards | "Show campaign performance", "List rewards in scope" |
| Risk clusters | "Find high-risk entities", "Show abnormal clusters" |

## Unsupported Questions

Noesis will return a fallback response for:
- Questions outside the supported intent list.
- Write/mutation requests (delete, modify, export, execute).
- Raw query requests (SQL, GraphQL, Gremlin).
- Billing, configuration, or admin action requests.
- Prompt injection attempts.

## Cross-Tenant Access Policy

- Only operators with `admin` role or `kyber:read` permission may query other tenants.
- All cross-tenant queries are logged with both requested and effective tenant IDs.
- Cross-tenant mode can be disabled via `NOESIS_CROSS_TENANT_ENABLED=false`.

## Audit Trail

Every Noesis query generates a structured audit log entry containing:
- Request ID and correlation ID
- User ID and tenant ID
- Requested vs. effective tenant ID
- Surface, role, permissions
- Resolved intent and mode
- Result count
- Whether debug was returned
- Whether fallback was triggered
- Whether the request was rejected (and reason)

## Debug Output

The `query_debug` field (visible only to operators) contains:
- The resolved `QueryPlan` with intent, target, filters, limit, confidence, source.
- `read_only: true` confirmation.
- `validated: true` confirmation.

## Troubleshooting

### "Noesis returned fallback for a valid question"
1. Check the exact prompt text — the deterministic classifier uses keyword matching.
2. Review the audit log for the resolved intent.
3. If the LLM provider is enabled, check provider metrics for timeouts or failures.
4. Consider adding the keyword pattern to the classifier.

### "Cross-tenant query was rejected"
1. Verify the caller has `admin` role or `kyber:read` permission.
2. Check `NOESIS_CROSS_TENANT_ENABLED` is not set to `false`.
3. Review the audit log for the rejection reason.

### "No results returned"
1. The intent was classified correctly but the backing repository returned no data.
2. Check that the target tenant has data in the relevant store.
3. Check the effective tenant filter in the audit log.

### "LLM mode not working"
1. Verify `NOESIS_LLM_ENABLED=true`.
2. Verify `NOESIS_LLM_PROVIDER` is set.
3. Check provider metrics for errors, timeouts, or cost limit exceeded.
4. The system falls back to deterministic mode if the provider fails.

## Monitoring

Key metrics to watch:
- `noesis_query` — total queries by surface, intent, mode.
- `noesis_rejected` — rejected prompts by reason.
- `noesis_safety` — safety events (write attempts, injection attempts, cross-tenant blocks).
- `noesis_provider` — LLM provider usage, timeouts, failures (when enabled).

## Kill Switches

| Switch | Effect |
|--------|--------|
| `NOESIS_ENABLED=false` | Disables the entire Noesis endpoint |
| `NOESIS_LLM_ENABLED=false` | Disables LLM planning, keeps deterministic mode |
| `NOESIS_CROSS_TENANT_ENABLED=false` | Disables all cross-tenant Kyber queries |
| `NOESIS_DEBUG_ENABLED=false` | Disables debug output even for operators |
