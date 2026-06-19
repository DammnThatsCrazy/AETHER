"""
Aether Agentic Observability Repositories.

Postgres-backed repositories for observation-only storage.
All repositories use the obs_ table prefix to distinguish from
execution-layer tables.

INVARIANT: These repositories store OBSERVED data only.
AETHER does not execute, originate, sign, or settle through these.
"""

from __future__ import annotations

from repositories.repos import BaseRepository


class AgentActivityRepository(BaseRepository):
    """Stores observed agent activity records (obs_agent_activities)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_activities")


class AgentConnectionRepository(BaseRepository):
    """Stores observed agent connections / MCP connections (obs_agent_connections)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_connections")


class AgentToolRepository(BaseRepository):
    """Stores observed agent tool invocations (obs_agent_tools)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_tools")


class AgentRiskSignalRepository(BaseRepository):
    """Stores agent risk signals produced from observed activity (obs_agent_risk_signals)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_risk_signals")


class X402InteractionRepository(BaseRepository):
    """Stores observed x402 interactions (obs_x402_interactions)."""
    def __init__(self) -> None:
        super().__init__("obs_x402_interactions")


class X402ChallengeRepository(BaseRepository):
    """Stores observed x402 challenges (obs_x402_challenges)."""
    def __init__(self) -> None:
        super().__init__("obs_x402_challenges")


class X402RequirementRepository(BaseRepository):
    """Stores observed x402 payment requirements (obs_x402_requirements)."""
    def __init__(self) -> None:
        super().__init__("obs_x402_requirements")


class X402SignatureRepository(BaseRepository):
    """Stores observed x402 signatures (obs_x402_signatures). Signature is external."""
    def __init__(self) -> None:
        super().__init__("obs_x402_signatures")


class X402VerificationRepository(BaseRepository):
    """Stores observed x402 verification results (obs_x402_verifications)."""
    def __init__(self) -> None:
        super().__init__("obs_x402_verifications")


class X402SettlementObsRepository(BaseRepository):
    """Stores observed x402 settlements (obs_x402_settlements_obs). Settlement is external."""
    def __init__(self) -> None:
        super().__init__("obs_x402_settlements_obs")


class X402ResourceAccessRepository(BaseRepository):
    """Stores observed x402 resource access outcomes (obs_x402_resource_access)."""
    def __init__(self) -> None:
        super().__init__("obs_x402_resource_access")


class AgentInboxRepository(BaseRepository):
    """Stores observed agent inboxes (obs_agent_inboxes)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_inboxes")


class AgentMessageRepository(BaseRepository):
    """Stores observed agent messages (obs_agent_messages)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_messages")


class AgentAttachmentRepository(BaseRepository):
    """Stores observed agent message attachments (obs_agent_attachments)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_attachments")


class ExtractedEntityRepository(BaseRepository):
    """Stores entities extracted from observed messages (obs_extracted_entities)."""
    def __init__(self) -> None:
        super().__init__("obs_extracted_entities")


class ExternalAccountRepository(BaseRepository):
    """Stores observed external agentic accounts (obs_external_accounts)."""
    def __init__(self) -> None:
        super().__init__("obs_external_accounts")


class ExternalBrokerageRepository(BaseRepository):
    """Stores observed external brokerage accounts (obs_external_brokerages)."""
    def __init__(self) -> None:
        super().__init__("obs_external_brokerages")


class TradeObservationRepository(BaseRepository):
    """Stores observed trade intents and orders (obs_trade_observations)."""
    def __init__(self) -> None:
        super().__init__("obs_trade_observations")


class PortfolioSnapshotRepository(BaseRepository):
    """Stores observed portfolio snapshots (obs_portfolio_snapshots)."""
    def __init__(self) -> None:
        super().__init__("obs_portfolio_snapshots")


class AgentBudgetRepository(BaseRepository):
    """Stores observed agent budget states (obs_agent_budgets)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_budgets")


class AgentPerformanceRepository(BaseRepository):
    """Stores observed agent performance snapshots (obs_agent_performance)."""
    def __init__(self) -> None:
        super().__init__("obs_agent_performance")
