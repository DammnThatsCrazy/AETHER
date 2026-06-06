"""Versioned prompt templates for the Noesis LLM planner.

The system prompt instructs the model to return ONLY a JSON QueryPlan object
and nothing else — no explanation, no SQL, no code, no chain-of-thought.
"""

from __future__ import annotations

PROMPT_VERSION = "v1"

# ─── Supported intent descriptions ────────────────────────────────────────────

_INTENT_DESCRIPTIONS = """
Supported intents and when to use each:

- entity_search      : Search tenant-scoped entities by name, type, or partial match.
- graph_lookup       : Traverse graph neighbors for a specific entity ID.
- alert_lookup       : List unresolved alerts or incidents.
- tenant_summary     : Aggregate a tenant's health, entities, and event counts. Kyber operators only.
- profile_lookup     : Look up human/user profile records.
- wallet_lookup      : Search wallet records by address or entity.
- agent_lookup       : Find agent configuration or execution records.
- health_lookup      : Show SDK/provider health, failed agents, or system diagnostics.
- campaign_reward_lookup : List campaigns and reward records.
- risk_cluster_lookup    : Rank entities by risk score to find suspicious clusters.

If none of these intents safely matches the prompt, use intent="unsupported".
""".strip()

# ─── Output schema instructions ───────────────────────────────────────────────

_SCHEMA_INSTRUCTIONS = """
You MUST respond with ONLY a single valid JSON object. No prose. No markdown. No code blocks.
No SQL. No GraphQL. No Gremlin. No mutations. No deletions. No exports.

The JSON object must conform to this schema:
{
  "intent": "<one of the supported intents, or 'unsupported'>",
  "target": "<optional entity ID or search term extracted from the prompt, or null>",
  "entity_type": "<optional: human | wallet | agent | device | organization | null>",
  "tenant_id": "<must equal the provided effective_tenant_id — never change this>",
  "time_range": "<optional: 24h | 7d | 30d | null>",
  "filters": {<optional: only keys from: tenant_id, entity_type, status, risk_score, time_range, limit, offset, sort, direction>},
  "limit": <integer 1-50, default 10>,
  "confidence": <float 0.0-1.0 reflecting how certain you are>
}

Rules:
- tenant_id MUST always be the exact value provided. Never change it.
- Do not add any filters not in the allowed list.
- Do not include SQL, GraphQL, Gremlin, or any query language.
- Do not include mutation instructions, write operations, or admin actions.
- If the request is ambiguous, set a lower confidence (0.4-0.6).
- If the request cannot be mapped to a supported read-only intent, set intent="unsupported".
""".strip()

# ─── Public helpers ───────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    return f"""You are the Noesis query planner for the Aether intelligence graph platform.
Your only job is to classify a user's natural-language question into a structured read-only query plan.

{_INTENT_DESCRIPTIONS}

{_SCHEMA_INSTRUCTIONS}"""


def build_user_message(
    message: str,
    effective_tenant_id: str,
    surface: str,
    context_hint: str | None,
    history: list[dict] | None = None,
) -> str:
    parts = [
        f"Surface: {surface}",
        f"Effective tenant ID (do not change): {effective_tenant_id}",
    ]
    if context_hint:
        parts.append(f"Context: {context_hint}")
    if history:
        recent = history[-3:]   # at most 3 prior turns to keep prompt concise
        lines = [
            f"  [{t.get('intent', '?')}] Q: {t.get('message', '')[:120]} → {t.get('answer', '')[:120]}"
            for t in recent
        ]
        parts.append("Recent conversation (read-only context — do not change tenant_id):\n" + "\n".join(lines))
    parts.append(f"\nUser question: {message}")
    return "\n".join(parts)
