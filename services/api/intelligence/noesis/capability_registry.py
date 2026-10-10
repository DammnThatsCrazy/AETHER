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
    NoesisCapability(
        intent="communications_insight",
        label="Communications Insight",
        description=(
            "Evidence-backed communications intelligence: deliverability, "
            "human-qualified engagement, machine-activity inflation, and "
            "campaign resolution coverage."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Is our email engagement inflated by machine activity?",
            "How is email deliverability trending?",
            "What share of communications resolve to a campaign?",
        ],
        data_sources=["comms_facts_repository"],
    ),
    NoesisCapability(
        intent="stablecoin_flow_lookup",
        label="Stablecoin Flow Summary",
        description=(
            "Summarize observed stablecoin flow aggregates and peg status "
            "for the tenant, including depeg signals. Read-only; requires "
            "Stablecoin Intelligence to be enabled."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Summarize stablecoin flows this week",
            "Is USDC on peg?",
            "Show depeg signals for tracked stablecoins",
        ],
        data_sources=["stablecoin_flow_aggregates", "stablecoin_valuation_snapshots"],
    ),
    NoesisCapability(
        intent="derivatives_exposure_lookup",
        label="Derivatives Position Exposure",
        description=(
            "Report observed derivatives positions and P&L snapshots for "
            "linked read-only trading accounts. Observation-only — Aether "
            "never places or recommends orders."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "What derivatives exposure do we have?",
            "Show open perp positions for account acct_1",
            "Summarize derivatives P&L snapshots",
        ],
        data_sources=["derivatives_positions", "derivatives_pnl_snapshots"],
    ),
    NoesisCapability(
        intent="derivatives_reconciliation_lookup",
        label="Derivatives Reconciliation Status",
        description=(
            "Show reconciliation variances between venue-reported and "
            "projected derivatives state, plus unrecovered stream gaps."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Are there derivatives reconciliation variances?",
            "Show unrecovered derivatives stream gaps",
        ],
        data_sources=["derivatives_reconciliation_variances", "derivatives_stream_gaps"],
    ),
    NoesisCapability(
        intent="interop_message_trace",
        label="Cross-Chain Message Trace",
        description=(
            "Trace a cross-chain message's observed lifecycle timeline by "
            "correlation key or message id. Observation-only — Aether never "
            "relays or recovers messages."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Trace cross-chain message lz2:0xabc",
            "What is the status of interop message msg_123?",
            "Show recent cross-chain messages",
        ],
        data_sources=["interop_messages", "interop_message_events"],
    ),
    NoesisCapability(
        intent="interop_path_reliability",
        label="Interop Path Reliability",
        description=(
            "Summarize delivery outcomes per cross-chain path: delivered, "
            "failed, and in-flight message counts."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Which cross-chain paths are unreliable?",
            "Show path reliability for LayerZero lanes",
        ],
        data_sources=["interop_messages"],
    ),
    NoesisCapability(
        intent="import_status_lookup",
        label="Tenant Import Status",
        description=(
            "Report observed tenant import sessions and their lifecycle "
            "status. Read-only — Noesis never creates, commits, cancels, or "
            "mutates an import."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "What is the status of our data imports?",
            "Show recent import sessions",
            "Look up import session imp_123",
        ],
        data_sources=["imports_repository"],
    ),
    NoesisCapability(
        intent="job_status_lookup",
        label="Background Job Status",
        description=(
            "Summarize observed background jobs and their status "
            "distribution. Observation-only — Noesis never enqueues, "
            "cancels, retries, or runs jobs."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Show recent background jobs",
            "What jobs are queued?",
            "Look up job job_123",
        ],
        data_sources=["jobs_repository"],
    ),
    NoesisCapability(
        intent="measurement_integrity_lookup",
        label="Measurement Integrity",
        description=(
            "Report observed measurement results and their value_state "
            "distribution for a tenant. Read-only — never recomputes, "
            "restates, or relabels a metric; attributed credit is not causal "
            "and a missing value is never reported as zero."
        ),
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "What is the value_state of our conversion rate metric?",
            "Show measurement integrity for our metrics",
            "Which measurements have insufficient data?",
        ],
        data_sources=["measurement_results_store", "metric_registry"],
    ),
    NoesisCapability(
        intent="relationship_explain",
        label="Relationship Explain",
        description=(
            "Explain the observed basis and evidence for a relationship or "
            "entity pair: canonical relationship predicates, supporting "
            "motifs, persisted relationship-fidelity dims, and any incentive "
            "context that is present. Read-only — relationship fidelity is "
            "reported as persisted; missing values are never zero. Requires "
            "the Relationship Intelligence Noesis surface to be enabled."
        ),
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "Explain the relationship between entity ent_100 and entity ent_200",
            "Why is there a relationship edge between these two profiles?",
            "What is the basis of the relationship between Alice and Bob?",
            "Show the relationship context for profile p_42",
        ],
        data_sources=["relationship_spine", "relationship_fidelity", "incentive_context"],
    ),
    NoesisCapability(
        intent="influence_path",
        label="Influence Path",
        description=(
            "Decompose measured influence along the best evidence-backed path "
            "between subjects, computed from the influence-propagation "
            "substrate. Reports only per-hop values that were actually "
            "measured — never fabricated. Read-only; flag-gated on the "
            "Relationship Intelligence Noesis surface."
        ),
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "Show the influence path between wallet w_a and wallet w_b",
            "Who influences profile p_9 the most?",
            "How does influence propagate from user_a to user_b?",
            "Is there an influence chain from ent_1 to ent_4?",
        ],
        data_sources=["relationship_spine", "influence_propagation", "computation_substrate"],
    ),
    NoesisCapability(
        intent="engagement_fidelity",
        label="Engagement Fidelity",
        description=(
            "Report the latest persisted relationship-fidelity vector for a "
            "subject or relationship: interaction_frequency, interaction_depth, "
            "reciprocity, and persistence engagement dims. Missing dims stay "
            "null — a missing engagement value is never reported as zero. "
            "Read-only; flag-gated."
        ),
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "What is the engagement fidelity of entity ent_789?",
            "Show the fidelity vector for relationship rel_12",
            "How strong is the engagement between Alice and Bob?",
            "Show reciprocity and persistence for profile p_5",
        ],
        data_sources=["relationship_fidelity", "relationship_spine"],
    ),
    NoesisCapability(
        intent="incentive_context_explain",
        label="Incentive Context Explain",
        description=(
            "Explain the persisted incentive-context assessment for a subject "
            "when present — recorded incentive structures and alignment "
            "signals. Observation-only: an incentive is never asserted where "
            "none is persisted, and none of this is causal attribution. "
            "Read-only; flag-gated."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Explain the incentive context for this relationship",
            "What is the incentive context behind Alice's activity?",
            "Why is this user incentivized to share content?",
            "Show the incentive context for profile p_7",
        ],
        data_sources=["incentive_context", "relationship_spine"],
    ),
    NoesisCapability(
        intent="risk_assessment_explain",
        label="Risk Assessment Explain",
        description=(
            "Explain the stored Risk360 assessment for a subject: which risk "
            "dimensions are scored (with value states), the consolidated "
            "claim_state, the referenced decision policy, and any exposure "
            "summary. Read-only — Noesis never mutates risk truth; requires "
            "Risk360 Intelligence to be enabled."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Explain the risk assessment for entity ent_123",
            "What dimensions were scored in the risk assessment for agent ag_1?",
            "Why does entity ent_123 carry this risk assessment?",
        ],
        data_sources=["risk_assessments"],
    ),
    NoesisCapability(
        intent="fraud_hypothesis_summarize",
        label="Fraud Hypothesis Summary",
        description=(
            "Summarize stored Fraud360 hypotheses for a subject: matched "
            "pattern display names and families, lifecycle state and phase, "
            "materiality when set, and risk/network/flow/decision "
            "cross-references. Read-only — Noesis never mutates fraud truth; "
            "requires Fraud360 Intelligence to be enabled."
        ),
        surfaces=["aether", "kyber"],
        requires_target=False,
        example_prompts=[
            "Summarize the fraud hypotheses for entity ent_123",
            "What fraud hypotheses exist for agent ag_1?",
            "Show the state and materiality of fraud hypotheses on entity ent_123",
        ],
        data_sources=["fraud_hypotheses"],
    ),
    NoesisCapability(
        intent="risk_fraud_contradiction_lookup",
        label="Risk/Fraud Contradiction Surface",
        description=(
            "Surface honest contradictions or gaps between a subject's stored "
            "Risk360 assessment and its stored Fraud360 hypotheses — e.g. a "
            "material or confirmed fraud hypothesis whose subject's assessment "
            "has no scored fraud dimension, or recorded contradictory evidence. "
            "Read-only and honest: a contradiction is never invented. Requires "
            "both Risk360 and Fraud360 Intelligence to be enabled."
        ),
        surfaces=["aether", "kyber"],
        requires_target=True,
        example_prompts=[
            "Are the risk and fraud views contradictory for entity ent_123?",
            "Does the fraud hypothesis conflict with the risk assessment for agent ag_1?",
            "Reconcile the risk assessment and fraud hypotheses for entity ent_123",
        ],
        data_sources=["risk_assessments", "fraud_hypotheses"],
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
