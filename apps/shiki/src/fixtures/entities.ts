import type {
  Entity,
  EntityType,
  NeedsHelpCard,
  EntityTimeline,
  TimelineEvent,
  Intervention,
  EntityRecommendation,
  EntityNote,
} from '@shiki/types';

const now = new Date();
const ago = (minutes: number) => new Date(now.getTime() - minutes * 60_000).toISOString();

// ---------------------------------------------------------------------------
// Entities — 2+ per type
// ---------------------------------------------------------------------------

export const MOCK_ENTITIES: Entity[] = [
  // --- Customers ---
  {
    id: 'cust-acme-001',
    type: 'customer',
    name: 'Acme Corp',
    displayLabel: 'Acme Corp (Enterprise)',
    createdAt: ago(60 * 24 * 90),
    updatedAt: ago(12),
    health: { status: 'degraded', message: 'Event stream interrupted 15 min ago', lastChecked: ago(1) },
    trustScore: 0.74,
    riskScore: 0.31,
    anomalyScore: 0.42,
    needsHelp: true,
    needsHelpReason: 'Event stream silent for >15 minutes',
    tags: ['enterprise', 'high-value', 'defi'],
    metadata: { tier: 'enterprise', mrr: 48_000, region: 'us-east-1', integrationVersion: '3.2.1' },
  },
  {
    id: 'cust-nebula-002',
    type: 'customer',
    name: 'Nebula Finance',
    displayLabel: 'Nebula Finance',
    createdAt: ago(60 * 24 * 45),
    updatedAt: ago(180),
    health: { status: 'healthy', lastChecked: ago(2) },
    trustScore: 0.91,
    riskScore: 0.08,
    anomalyScore: 0.03,
    needsHelp: false,
    tags: ['mid-market', 'cefi', 'active'],
    metadata: { tier: 'growth', mrr: 12_000, region: 'eu-west-1', integrationVersion: '3.3.0' },
  },
  {
    id: 'cust-orion-003',
    type: 'customer',
    name: 'Orion DAO',
    displayLabel: 'Orion DAO (Community)',
    createdAt: ago(60 * 24 * 200),
    updatedAt: ago(45),
    health: { status: 'healthy', lastChecked: ago(3) },
    trustScore: 0.86,
    riskScore: 0.12,
    anomalyScore: 0.07,
    needsHelp: false,
    tags: ['dao', 'governance', 'staking'],
    metadata: { tier: 'community', mrr: 0, region: 'ap-southeast-1', integrationVersion: '3.1.0' },
  },

  // --- Wallets ---
  {
    id: 'wallet-0x7a3b',
    type: 'wallet',
    name: '0x7a3b...f2e1',
    displayLabel: 'Wallet 0x7a3b (Suspicious)',
    createdAt: ago(60 * 24 * 60),
    updatedAt: ago(25),
    health: { status: 'degraded', message: 'Trust score dropped sharply', lastChecked: ago(1) },
    trustScore: 0.41,
    riskScore: 0.68,
    anomalyScore: 0.72,
    needsHelp: false,
    tags: ['flagged', 'erc20', 'high-volume'],
    metadata: { chain: 'ethereum', txCount: 2847, firstSeen: ago(60 * 24 * 60), lastTx: ago(25) },
  },
  {
    id: 'wallet-0xde4f',
    type: 'wallet',
    name: '0xde4f...a891',
    displayLabel: 'Wallet 0xde4f (Verified)',
    createdAt: ago(60 * 24 * 120),
    updatedAt: ago(300),
    health: { status: 'healthy', lastChecked: ago(5) },
    trustScore: 0.93,
    riskScore: 0.04,
    anomalyScore: 0.01,
    needsHelp: false,
    tags: ['verified', 'institutional', 'multisig'],
    metadata: { chain: 'ethereum', txCount: 9124, firstSeen: ago(60 * 24 * 120), lastTx: ago(300) },
  },

  // --- Agents ---
  {
    id: 'agent-enrich-04',
    type: 'agent',
    name: 'enrichment-agent-04',
    displayLabel: 'Enrichment Agent #04',
    createdAt: ago(60 * 24 * 30),
    updatedAt: ago(8),
    health: { status: 'unhealthy', message: 'Stuck loop detected — 8 retries in 30 min', lastChecked: ago(1) },
    trustScore: 0.52,
    riskScore: 0.55,
    anomalyScore: 0.81,
    needsHelp: true,
    needsHelpReason: 'Stuck loop: retried same objective 8 times',
    tags: ['enrichment', 'stuck', 'backlog'],
    metadata: { objectiveId: 'obj-enrich-774', retryCount: 8, queueDepth: 23, model: 'gpt-4o' },
  },
  {
    id: 'agent-triage-02',
    type: 'agent',
    name: 'triage-agent-02',
    displayLabel: 'Triage Agent #02',
    createdAt: ago(60 * 24 * 30),
    updatedAt: ago(3),
    health: { status: 'healthy', lastChecked: ago(1) },
    trustScore: 0.94,
    riskScore: 0.03,
    anomalyScore: 0.02,
    needsHelp: false,
    tags: ['triage', 'active', 'high-throughput'],
    metadata: { objectiveId: 'obj-triage-212', processedLast1h: 142, model: 'claude-3.5-sonnet' },
  },
  {
    id: 'agent-recovery-01',
    type: 'agent',
    name: 'recovery-agent-01',
    displayLabel: 'Recovery Agent #01',
    createdAt: ago(60 * 24 * 60),
    updatedAt: ago(45),
    health: { status: 'healthy', lastChecked: ago(2) },
    trustScore: 0.89,
    riskScore: 0.06,
    anomalyScore: 0.04,
    needsHelp: false,
    tags: ['recovery', 'idle', 'standby'],
    metadata: { lastRecovery: ago(60 * 24 * 3), totalRecoveries: 17, model: 'claude-3.5-sonnet' },
  },

  // --- Protocols ---
  {
    id: 'proto-uniswap-v3',
    type: 'protocol',
    name: 'Uniswap V3',
    displayLabel: 'Uniswap V3 (Ethereum)',
    createdAt: ago(60 * 24 * 365),
    updatedAt: ago(60),
    health: { status: 'healthy', lastChecked: ago(5) },
    trustScore: 0.97,
    riskScore: 0.02,
    anomalyScore: 0.01,
    needsHelp: false,
    tags: ['dex', 'ethereum', 'amm', 'audited'],
    metadata: { tvl: 3_200_000_000, chain: 'ethereum', version: '3.0', auditor: 'Trail of Bits' },
  },
  {
    id: 'proto-aave-v3',
    type: 'protocol',
    name: 'Aave V3',
    displayLabel: 'Aave V3 (Multi-chain)',
    createdAt: ago(60 * 24 * 300),
    updatedAt: ago(120),
    health: { status: 'healthy', lastChecked: ago(4) },
    trustScore: 0.95,
    riskScore: 0.05,
    anomalyScore: 0.02,
    needsHelp: false,
    tags: ['lending', 'multi-chain', 'audited'],
    metadata: { tvl: 8_700_000_000, chains: ['ethereum', 'polygon', 'arbitrum'], version: '3.0' },
  },

  // --- Contracts ---
  {
    id: 'contract-vault-01',
    type: 'contract',
    name: 'AcmeVault.sol',
    displayLabel: 'Acme Vault Contract',
    createdAt: ago(60 * 24 * 180),
    updatedAt: ago(200),
    health: { status: 'healthy', lastChecked: ago(10) },
    trustScore: 0.88,
    riskScore: 0.09,
    anomalyScore: 0.05,
    needsHelp: false,
    tags: ['vault', 'ethereum', 'upgradeable', 'acme'],
    metadata: { address: '0x1234...abcd', chain: 'ethereum', proxy: true, verified: true },
  },
  {
    id: 'contract-bridge-02',
    type: 'contract',
    name: 'NebulaBridge.sol',
    displayLabel: 'Nebula Bridge Contract',
    createdAt: ago(60 * 24 * 90),
    updatedAt: ago(60),
    health: { status: 'degraded', message: 'Latency spike on cross-chain relay', lastChecked: ago(3) },
    trustScore: 0.72,
    riskScore: 0.34,
    anomalyScore: 0.28,
    needsHelp: false,
    tags: ['bridge', 'cross-chain', 'nebula'],
    metadata: { address: '0x5678...ef01', chains: ['ethereum', 'polygon'], proxy: false, verified: true },
  },

  // --- Clusters ---
  {
    id: 'cluster-c892',
    type: 'cluster',
    name: 'Cluster C-892',
    displayLabel: 'Suspicious Cluster C-892',
    createdAt: ago(60 * 24 * 14),
    updatedAt: ago(25),
    health: { status: 'unhealthy', message: 'Multiple flagged wallets in cluster', lastChecked: ago(1) },
    trustScore: 0.22,
    riskScore: 0.85,
    anomalyScore: 0.91,
    needsHelp: false,
    tags: ['suspicious', 'wash-trading', 'flagged'],
    metadata: { nodeCount: 47, edgeCount: 183, flaggedNodes: 12, detectedPattern: 'wash-trading' },
  },
  {
    id: 'cluster-c340',
    type: 'cluster',
    name: 'Cluster C-340',
    displayLabel: 'Institutional Cluster C-340',
    createdAt: ago(60 * 24 * 60),
    updatedAt: ago(600),
    health: { status: 'healthy', lastChecked: ago(5) },
    trustScore: 0.92,
    riskScore: 0.05,
    anomalyScore: 0.02,
    needsHelp: false,
    tags: ['institutional', 'verified', 'stable'],
    metadata: { nodeCount: 23, edgeCount: 89, flaggedNodes: 0, detectedPattern: 'institutional-custody' },
  },
];

// ---------------------------------------------------------------------------
// NeedsHelp cards
// ---------------------------------------------------------------------------

export const MOCK_NEEDS_HELP_CARDS: NeedsHelpCard[] = [
  {
    entityId: 'cust-acme-001',
    entityType: 'customer',
    entityName: 'Acme Corp',
    reason: 'Event stream silent for >15 minutes. Last event received at 14:32 UTC.',
    evidence: [
      'No events received since 14:32 UTC (gap: 18 min)',
      'SDK heartbeat last seen at 14:30 UTC',
      'Previous gap of >10 min occurred 7 days ago (resolved: SDK restart)',
    ],
    confidence: 0.92,
    recommendedAction: 'Contact Acme Corp integration team; check SDK health endpoint',
    reversible: false,
    owner: 'Commander Bright',
    traceLink: '/traces/trace-evt-001',
    severity: 'P0',
    flaggedAt: ago(5),
  },
  {
    entityId: 'agent-enrich-04',
    entityType: 'agent',
    entityName: 'enrichment-agent-04',
    reason: 'Stuck loop detected: agent retried the same enrichment objective 8 times in 30 minutes with degrading confidence.',
    evidence: [
      'Retry count: 8 over 30 minutes for objective obj-enrich-774',
      'Confidence dropped from 0.87 to 0.52',
      'Downstream queue depth growing: 23 entities waiting',
      'No successful output in last 30 min',
    ],
    confidence: 0.96,
    recommendedAction: 'Pause agent, review objective obj-enrich-774, consider reassigning to different model',
    reversible: true,
    owner: 'Chief Engineer Amuro',
    traceLink: '/traces/trace-agent-004',
    severity: 'P1',
    flaggedAt: ago(8),
  },
  {
    entityId: 'wallet-0x7a3b',
    entityType: 'wallet',
    entityName: '0x7a3b...f2e1',
    reason: 'Trust score dropped from 0.82 to 0.41 after new edges connected to suspicious cluster C-892.',
    evidence: [
      'Trust score delta: -0.41 in 2 hours',
      '3 new edges to cluster C-892 (flagged: wash-trading)',
      'Transaction volume spike: 340% above 7-day average',
      'Source of funds trace leads to known mixer contract',
    ],
    confidence: 0.88,
    recommendedAction: 'Review wallet neighborhood in graph; escalate if mixer usage confirmed',
    reversible: false,
    traceLink: '/traces/trace-trust-012',
    severity: 'P2',
    flaggedAt: ago(25),
  },
  {
    entityId: 'contract-bridge-02',
    entityType: 'contract',
    entityName: 'NebulaBridge.sol',
    reason: 'Cross-chain relay latency spiked to 12s (baseline: 800ms). Bridge deposits may be delayed.',
    evidence: [
      'Relay latency p99: 12,400ms (baseline p99: 800ms)',
      'Polygon RPC provider returning 503 intermittently',
      '14 pending bridge deposits in queue',
      'Last successful relay: 6 min ago',
    ],
    confidence: 0.79,
    recommendedAction: 'Check Polygon RPC provider status; consider switching to backup provider',
    reversible: true,
    traceLink: '/traces/trace-bridge-002',
    severity: 'P2',
    flaggedAt: ago(18),
  },
];

// ---------------------------------------------------------------------------
// Timelines
// ---------------------------------------------------------------------------

export const MOCK_TIMELINES: EntityTimeline[] = [
  {
    entityId: 'cust-acme-001',
    events: [
      {
        id: 'tl-acme-001',
        timestamp: ago(5),
        type: 'alert',
        title: 'Event stream interrupted',
        description: 'No events received from Acme Corp SDK for 15 minutes.',
        severity: 'P0',
        controller: 'zeong',
        traceId: 'trace-evt-001',
        metadata: { lastEventAt: ago(20), gapMinutes: 15 },
      },
      {
        id: 'tl-acme-002',
        timestamp: ago(60),
        type: 'enrichment',
        title: 'Entity profile enriched',
        description: 'Added 3 new metadata fields from CRM sync.',
        severity: 'info',
        controller: 'intake',
        traceId: 'trace-enrich-091',
        metadata: { fieldsAdded: ['industry', 'employee_count', 'funding_stage'] },
      },
      {
        id: 'tl-acme-003',
        timestamp: ago(60 * 24),
        type: 'review',
        title: 'Trust score recalculated',
        description: 'Trust score updated from 0.81 to 0.74 following anomaly detection.',
        severity: 'P2',
        controller: 'gouf',
        traceId: 'trace-trust-088',
        metadata: { previousScore: 0.81, newScore: 0.74 },
      },
      {
        id: 'tl-acme-004',
        timestamp: ago(60 * 48),
        type: 'onboarding',
        title: 'SDK version upgraded',
        description: 'Customer upgraded from SDK v3.1.0 to v3.2.1.',
        severity: 'info',
        metadata: { fromVersion: '3.1.0', toVersion: '3.2.1' },
      },
      {
        id: 'tl-acme-005',
        timestamp: ago(60 * 24 * 7),
        type: 'alert',
        title: 'Previous event gap resolved',
        description: 'Event gap of 12 minutes resolved after SDK auto-restart.',
        severity: 'P1',
        controller: 'zeong',
        traceId: 'trace-evt-prev-001',
        metadata: { gapMinutes: 12, resolution: 'SDK auto-restart' },
      },
    ],
  },
  {
    entityId: 'agent-enrich-04',
    events: [
      {
        id: 'tl-agent-001',
        timestamp: ago(8),
        type: 'stuck-loop',
        title: 'Stuck loop detected',
        description: 'Agent retried objective obj-enrich-774 for the 8th time.',
        severity: 'P1',
        controller: 'zeong',
        traceId: 'trace-agent-004',
        metadata: { retryCount: 8, objectiveId: 'obj-enrich-774' },
      },
      {
        id: 'tl-agent-002',
        timestamp: ago(15),
        type: 'agent-lifecycle',
        title: 'Confidence degrading',
        description: 'Agent confidence dropped from 0.72 to 0.52 on current objective.',
        severity: 'P2',
        controller: 'triage',
        metadata: { previousConfidence: 0.72, newConfidence: 0.52 },
      },
      {
        id: 'tl-agent-003',
        timestamp: ago(38),
        type: 'agent-lifecycle',
        title: 'Objective assigned',
        description: 'Assigned enrichment objective obj-enrich-774 (batch of 23 entities).',
        severity: 'info',
        controller: 'triage',
        metadata: { objectiveId: 'obj-enrich-774', entityCount: 23 },
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Interventions
// ---------------------------------------------------------------------------

export const MOCK_INTERVENTIONS: Intervention[] = [
  {
    id: 'intv-001',
    entityId: 'agent-enrich-04',
    type: 'pause',
    description: 'Paused enrichment agent due to stuck loop. Queue redistributed to agent-enrich-05.',
    performedBy: 'Chief Engineer Amuro',
    performedAt: ago(6),
    reversible: true,
    revertId: 'revert-intv-001',
    outcome: 'Agent paused; 23 queued entities reassigned',
  },
  {
    id: 'intv-002',
    entityId: 'wallet-0x7a3b',
    type: 'flag-escalation',
    description: 'Escalated wallet to P1 review after trust score drop and mixer adjacency.',
    performedBy: 'Commander Bright',
    performedAt: ago(20),
    reversible: false,
    outcome: 'Wallet flagged for enhanced monitoring',
  },
  {
    id: 'intv-003',
    entityId: 'cust-acme-001',
    type: 'notification',
    description: 'Sent P0 notification to Acme Corp integration team via Slack and email.',
    performedBy: 'relay',
    performedAt: ago(5),
    reversible: false,
  },
  {
    id: 'intv-004',
    entityId: 'contract-bridge-02',
    type: 'config-change',
    description: 'Switched Polygon RPC to backup provider (Alchemy) to reduce relay latency.',
    performedBy: 'Chief Engineer Amuro',
    performedAt: ago(15),
    reversible: true,
    revertId: 'revert-intv-004',
    outcome: 'Latency p99 decreased from 12.4s to 1.2s',
  },
];

// ---------------------------------------------------------------------------
// Recommendations
// ---------------------------------------------------------------------------

export const MOCK_RECOMMENDATIONS: EntityRecommendation[] = [
  {
    id: 'rec-001',
    title: 'Restart Acme Corp SDK heartbeat',
    description: 'Send a remote restart signal to the Acme Corp SDK integration to restore event flow.',
    confidence: 0.85,
    rationale: 'Previous event gaps for this customer were resolved by SDK restart. Current gap matches the same pattern.',
    actionClass: 2,
    reversible: true,
  },
  {
    id: 'rec-002',
    title: 'Reassign enrichment objective to different model',
    description: 'Move objective obj-enrich-774 from gpt-4o to claude-3.5-sonnet, which has better success rate on similar entity types.',
    confidence: 0.78,
    rationale: 'claude-3.5-sonnet has 94% success rate on similar enrichment tasks vs 71% for gpt-4o in last 7 days.',
    actionClass: 2,
    reversible: true,
  },
  {
    id: 'rec-003',
    title: 'Freeze wallet 0x7a3b outbound transfers',
    description: 'Temporarily freeze outbound transfers from wallet 0x7a3b pending investigation of mixer adjacency.',
    confidence: 0.72,
    rationale: 'Wallet connected to 3 nodes in suspicious cluster C-892. Mixer contract in transaction path.',
    actionClass: 4,
    reversible: true,
  },
  {
    id: 'rec-004',
    title: 'Add Cluster C-892 to watch list',
    description: 'Elevate monitoring frequency for all nodes in cluster C-892 from hourly to every 5 minutes.',
    confidence: 0.91,
    rationale: 'Cluster has 12 flagged nodes and growing edge count. Pattern matches wash-trading with 91% confidence.',
    actionClass: 1,
    reversible: true,
  },
];

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

export const MOCK_NOTES: EntityNote[] = [
  {
    id: 'note-001',
    entityId: 'cust-acme-001',
    author: 'Commander Bright',
    content: 'Spoke with Acme integration team. They are aware of the SDK issue and deploying a fix within the hour. Monitoring closely.',
    createdAt: ago(3),
    updatedAt: ago(3),
  },
  {
    id: 'note-002',
    entityId: 'cust-acme-001',
    author: 'Specialist Sayla',
    content: 'Acme Corp renewed their enterprise contract last month. High priority to maintain SLA compliance.',
    createdAt: ago(60 * 24 * 2),
    updatedAt: ago(60 * 24 * 2),
  },
  {
    id: 'note-003',
    entityId: 'wallet-0x7a3b',
    author: 'Chief Engineer Amuro',
    content: 'Cross-referencing on-chain data with off-chain KYC records. Wallet owner identity pending verification from compliance team.',
    createdAt: ago(20),
    updatedAt: ago(20),
  },
  {
    id: 'note-004',
    entityId: 'agent-enrich-04',
    author: 'Chief Engineer Amuro',
    content: 'This agent has been stuck before on similar entity batches with incomplete metadata. Consider adding fallback data sources.',
    createdAt: ago(6),
    updatedAt: ago(6),
  },
  {
    id: 'note-005',
    entityId: 'cluster-c892',
    author: 'Commander Bright',
    content: 'Flagged for external reporting to compliance. Awaiting legal review before any enforcement action.',
    createdAt: ago(60 * 2),
    updatedAt: ago(60 * 2),
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function getMockEntity(id: string): Entity | undefined {
  return MOCK_ENTITIES.find((e) => e.id === id);
}

export function getMockEntities(type?: EntityType): Entity[] {
  if (!type) return MOCK_ENTITIES;
  return MOCK_ENTITIES.filter((e) => e.type === type);
}

export function getMockNeedsHelpCards(): NeedsHelpCard[] {
  return MOCK_NEEDS_HELP_CARDS;
}

export function getMockTimeline(entityId: string): EntityTimeline | undefined {
  return MOCK_TIMELINES.find((t) => t.entityId === entityId);
}

export function getMockInterventions(entityId?: string): Intervention[] {
  if (!entityId) return MOCK_INTERVENTIONS;
  return MOCK_INTERVENTIONS.filter((i) => i.entityId === entityId);
}

export function getMockRecommendations(): EntityRecommendation[] {
  return MOCK_RECOMMENDATIONS;
}

export function getMockNotes(entityId?: string): EntityNote[] {
  if (!entityId) return MOCK_NOTES;
  return MOCK_NOTES.filter((n) => n.entityId === entityId);
}
