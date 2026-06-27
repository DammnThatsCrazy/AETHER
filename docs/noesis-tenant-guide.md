---
title: Noesis — Ask Aether
slug: noesis-tenant-guide
section: concepts
visibility: C
audience: [buyer]
status: stable
---

# Noesis — Ask Aether

Noesis lets you ask natural-language questions about your intelligence graph, profiles, campaigns, rewards, wallets, agents, and alerts — directly from the Aether dashboard.

## What you can ask

| Category | Example questions |
|----------|-------------------|
| Find entities | "Find users matching Alice", "Show me wallets" |
| Graph exploration | "What is connected to entity X?", "Show neighbors of wallet Y" |
| Alerts | "Show unresolved alerts", "What incidents are open?" |
| Profiles | "Find this user's profile", "Show identity information" |
| Wallets | "Show wallet 0xABC...", "Find wallets for this user" |
| Agents | "Show agent configurations", "Which agents are active?" |
| Health | "Show SDK health", "What's failing?" |
| Campaigns & Rewards | "Show campaign performance", "List active rewards" |
| Risk | "Find high-risk entities", "Show abnormal behavior clusters" |

## What you cannot ask

Noesis is a **read-only** intelligence tool. It cannot:
- Delete, modify, or create data.
- Export data in bulk.
- Execute raw queries.
- Change configurations or settings.
- Issue rewards or modify campaigns.
- Access another tenant's data.

If you ask an unsupported question, Noesis will suggest how to rephrase it.

## How it works

1. Type a question in natural language.
2. Noesis classifies your question and routes it to the appropriate read-only data source.
3. Results are displayed as cards with key fields, along with navigation actions to explore further.
4. Graph context (nodes, edges, highlights) is shown when relevant.

## Your data is scoped

All answers are scoped to your tenant. You cannot see or query another tenant's data. Results are filtered and redacted before being returned.

## Data freshness

Results reflect the current state of your data stores. Some analytics summaries may be cached for up to 5 minutes.

## Evidence model

Every Noesis answer includes an **evidence envelope** — a structured record of where the answer came from:

- **Sources**: each data service queried (e.g. `entity_repository`, `graph_client`, `profile360_aggregator`) with the resource type and fetch time.
- **Claims**: structured assertions about the answer (`fact`, `computation`, `inference`, or `recommendation`) with confidence scores.
- **Sufficient flag**: `true` when the data supports the answer. When `false`, Noesis explains *why* the graph cannot support the conclusion (e.g. "No profile found for 'entity-123'").

### Insufficient evidence

If no matching records exist for a specific target, Noesis returns an **Insufficient evidence** state with a plain-language reason. This is not an error — it means the graph has been checked and the answer is genuinely absent.

### Profile 360 lookups

When you ask about a specific user or entity (e.g. "Explain this user's Profile 360"), Noesis calls the Profile 360 aggregator directly and returns a full summary: wallet count, agent count, transfer inflow/outflow, active delegations, behavior flags, and risk score — all in one response.

### Campaign performance

Campaign queries include ROAS (return on ad spend) and conversion counts derived from attribution run data, not just the raw campaign record.

## Limitations

- Results are capped at 50 records per query (default 10).
- Complex multi-step analysis is not supported — ask specific, focused questions.
- Noesis uses keyword-based classification. If your question isn't recognized, try rephrasing with specific terms like "wallet", "alert", "profile", "agent", "campaign", "risk", or "health".
- Graph traversal shows direct neighbors only by default. Multi-hop traversal (depth > 1) is available when enabled by your operator.

## Conversation history

Your Noesis conversations are stored for the current session. On the Aether dashboard, the sidebar shows your recent conversations so you can resume a previous inquiry.

## Error messages

| Message | Meaning |
|---------|---------|
| "Noesis could not safely map this request" | Your question doesn't match a supported query type. Try rephrasing. |
| "Which graph node or entity should I inspect?" | Noesis needs a specific entity ID to look up graph connections. |
| Fallback with suggested prompt | Use the suggested prompt to refine your question. |
| Insufficient evidence | The graph was checked but no matching data exists for your query. |
