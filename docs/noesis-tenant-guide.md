---
title: Noesis — Ask Aether
slug: noesis-tenant-guide
section: product
visibility: E
audience: [tenant]
status: ga
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

## Limitations

- Results are capped at 50 records per query (default 10).
- Complex multi-step analysis is not supported — ask specific, focused questions.
- Noesis uses keyword-based classification. If your question isn't recognized, try rephrasing with specific terms like "wallet", "alert", "profile", "agent", "campaign", "risk", or "health".
- Graph traversal shows direct neighbors only, not multi-hop paths.

## Error messages

| Message | Meaning |
|---------|---------|
| "Noesis could not safely map this request" | Your question doesn't match a supported query type. Try rephrasing. |
| "Which graph node or entity should I inspect?" | Noesis needs a specific entity ID to look up graph connections. |
| Fallback with suggested prompt | Use the suggested prompt to refine your question. |
