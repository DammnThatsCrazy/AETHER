"""Noesis capability registry — single source of truth for all supported intents.

Every entry here drives: LLM system prompt generation, the /v1/noesis/capabilities
API endpoint, and frontend suggested prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NoesisCapability:
    intent: str
    label: str
    description: str
    surfaces: list[str]
    requires_target: bool
    example_prompts: list[str]
    data_sources: list[str]


CAPABILITY_REGISTRY: list[NoesisCapability] = [
    NoesisCapability(
        intent="entity_search",
        label="Entity Search",
        description="Search tenant-scoped entities by name, type, or partial match.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show me all entities",
            "Find entities named Acme",
            "List all wallet entities",
            "Search for human profiles matching 'john'",
        ],
        data_sources=["entity_repository"],
    ),
    NoesisCapability(
        intent="graph_lookup",
        label="Graph Lookup",
        description="Traverse graph neighbors for a specific entity ID.",
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "Show connections for entity ent_123",
            "What is linked to wallet w_abc?",
            "Graph neighbors of agent ag_xyz",
        ],
        data_sources=["graph_client"],
    ),
    NoesisCapability(
        intent="alert_lookup",
        label="Alert Lookup",
        description="List unresolved alerts or incidents for the tenant.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show me open alerts",
            "What incidents are unresolved?",
            "List high-severity alerts from the last 24 hours",
        ],
        data_sources=["alert_repository"],
    ),
    NoesisCapability(
        intent="tenant_summary",
        label="Tenant Summary",
        description="Aggregate a tenant's health, entity counts, and event statistics. Kyber operators only.",
        surfaces=["kyber"],
        requires_target=False,
        example_prompts=[
            "Summarize tenant health",
            "What is the overall status of this tenant?",
            "Give me a dashboard overview",
        ],
        data_sources=["admin_repository", "analytics"],
    ),
    NoesisCapability(
        intent="profile_lookup",
        label="Profile Lookup",
        description="Look up human or user profile records.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show me user profiles",
            "Look up the profile for user ent_456",
            "Find profiles with high identity confidence",
        ],
        data_sources=["entity_repository"],
    ),
    NoesisCapability(
        intent="wallet_lookup",
        label="Wallet Lookup",
        description="Search wallet records by address or linked entity.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show all wallets",
            "Find wallet 0xABC",
            "Which wallets have high risk scores?",
        ],
        data_sources=["wallet_repository"],
    ),
    NoesisCapability(
        intent="agent_lookup",
        label="Agent Lookup",
        description="Find agent configuration or execution records.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "List active agents",
            "Show me failed agent executions",
            "What agents ran in the last 7 days?",
        ],
        data_sources=["agent_config_repository", "agent_execution_repository"],
    ),
    NoesisCapability(
        intent="health_lookup",
        label="Health Lookup",
        description="Show SDK provider health, failed agents, or system diagnostics.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "What is the system health?",
            "Show me provider failures",
            "Are any agents unhealthy?",
        ],
        data_sources=["providers_repository", "agent_execution_repository", "analytics"],
    ),
    NoesisCapability(
        intent="campaign_reward_lookup",
        label="Campaign & Reward Lookup",
        description="List campaigns and associated reward records.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show active campaigns",
            "What rewards exist for campaign camp_1?",
            "List campaigns created in the last 30 days",
        ],
        data_sources=["campaign_repository", "wallet_repository"],
    ),
    NoesisCapability(
        intent="risk_cluster_lookup",
        label="Risk Cluster Lookup",
        description="Rank entities by risk score to identify suspicious clusters.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show me the highest risk entities",
            "Which entities have a risk score above 0.8?",
            "Find suspicious clusters",
        ],
        data_sources=["entity_repository"],
    ),
    NoesisCapability(
        intent="suggestion_lookup",
        label="Suggestion Lookup",
        description="Look up individual suggestion records (read-only).",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show me recent suggestions",
            "List suggestions for entity ent_789",
        ],
        data_sources=["suggestion_repository"],
    ),
    NoesisCapability(
        intent="suggestion_summary",
        label="Suggestion Summary",
        description="Summarize suggestion activity and acceptance rates.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Summarize suggestions this week",
            "What is the suggestion acceptance rate?",
        ],
        data_sources=["suggestion_repository"],
    ),
    NoesisCapability(
        intent="suggestion_review_queue",
        label="Suggestion Review Queue",
        description="Show the pending suggestion review queue.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "What suggestions need review?",
            "Show the review queue",
        ],
        data_sources=["suggestion_repository"],
    ),
    NoesisCapability(
        intent="suggestion_explain",
        label="Explain Suggestion",
        description="Explain the rationale behind a specific suggestion.",
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "Explain suggestion sug_123",
            "Why was this suggestion generated?",
        ],
        data_sources=["suggestion_repository"],
    ),
    NoesisCapability(
        intent="suggestion_outcome_lookup",
        label="Suggestion Outcome Lookup",
        description="Look up outcomes and results for processed suggestions.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "What happened with recent suggestions?",
            "Show suggestion outcomes for last 7 days",
        ],
        data_sources=["suggestion_repository"],
    ),
    NoesisCapability(
        intent="agent_inventory_lookup",
        label="Agent Inventory Lookup",
        description="List observed agents from tenant-scoped agentic telemetry.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which agents exist?", "List active agents in the fleet"],
        data_sources=["agent_activity_repository", "silver_agent_activity_facts"],
    ),
    NoesisCapability(
        intent="agent_activity_lookup",
        label="Agent Activity Lookup",
        description="Explain observed agent tasks, tool invocations, and provider action telemetry.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which actions did agent agent_123 attempt?", "Show recent agent activity"],
        data_sources=["agent_activity_repository", "silver_agent_activity_facts"],
    ),
    NoesisCapability(
        intent="mcp_topology_lookup",
        label="MCP Topology Lookup",
        description="Inspect observed MCP clients, servers, connections, and tool topology.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which MCP servers changed tool schemas this week?", "Show MCP topology for agent agent_123"],
        data_sources=["agent_connection_repository", "silver_mcp_connection_facts"],
    ),
    NoesisCapability(
        intent="authorization_lookup",
        label="Authorization Lookup",
        description="Inspect observed external accounts, grants, and permission scopes.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which agents can post to X?", "Which external accounts are delegated?"],
        data_sources=["external_account_repository"],
    ),
    NoesisCapability(
        intent="provider_verification_lookup",
        label="Provider Verification Lookup",
        description="Show provider-confirmed, unverified, or contradicted provider action evidence.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which actions are provider-confirmed?", "Show verified X actions"],
        data_sources=["agent_tool_repository", "silver_agent_tool_invocation_facts"],
    ),
    NoesisCapability(
        intent="verification_mismatch_lookup",
        label="Verification Mismatch Lookup",
        description="Find actions where provider evidence contradicts lower-trust observations.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which actions are not provider-confirmed?", "Show verification mismatches"],
        data_sources=["agent_tool_repository", "silver_agent_tool_invocation_facts"],
    ),
    NoesisCapability(
        intent="permission_risk_lookup",
        label="Permission Risk Lookup",
        description="Explain permission drift, unused write scopes, revoked-grant use, and related recommendations.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which agents have unused write scopes?", "Show permission drift"],
        data_sources=["agent_risk_signal_repository", "silver_agent_risk_facts"],
    ),
    NoesisCapability(
        intent="agent_path_lookup",
        label="Agent Evidence Path Lookup",
        description="Summarize observed evidence paths from agent to action, provider verification, and external object.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Show the evidence path for agent agent_123", "Explain the chain from agent to provider action"],
        data_sources=["agent_activity_repository", "graph_client"],
    ),
    NoesisCapability(
        intent="sentiment_explain",
        label="Sentiment Explain",
        description="Explain tenant-scoped target-specific sentiment with evidence, freshness, model versions, and causal-confidence labels.",
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=["Why did sentiment toward Product X decline?", "What evidence supports sentiment for campaign camp_123?"],
        data_sources=["semantic_intelligence_api", "evidence_envelope"],
    ),
    NoesisCapability(
        intent="narrative_analysis",
        label="Narrative Analysis",
        description="Analyze tenant-scoped narratives, claims, adoption, rejection, and diffusion without unsupported causal claims.",
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=["Which narrative drove Campaign Y conversions?", "How did this narrative move from Web2 to Web3?"],
        data_sources=["semantic_intelligence_api", "graph_traversal"],
    ),
    NoesisCapability(
        intent="semantic_profile_explain",
        label="Semantic Profile Explain",
        description="Summarize semantic state, stance, intent, active topics, evidence and freshness for a Profile360 entity.",
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=["Explain this user's semantic profile", "Which topics and stances are active for profile ent_456?"],
        data_sources=["profile360", "semantic_intelligence_api"],
    ),
]

# Fast lookup by intent name
_REGISTRY_BY_INTENT: dict[str, NoesisCapability] = {cap.intent: cap for cap in CAPABILITY_REGISTRY}


def get_capability(intent: str) -> NoesisCapability | None:
    return _REGISTRY_BY_INTENT.get(intent)


def capabilities_for_surface(surface: str) -> list[NoesisCapability]:
    return [cap for cap in CAPABILITY_REGISTRY if surface in cap.surfaces]


def build_intent_descriptions() -> str:
    lines = ["Supported intents and when to use each:"]
    for cap in CAPABILITY_REGISTRY:
        lines.append(f"- {cap.intent:<28}: {cap.description}")
    lines.append("\nIf none of these intents safely matches the prompt, use intent=\"unsupported\".")
    return "\n".join(lines)
