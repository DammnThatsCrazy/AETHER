import type {
  Entity,
  EntityNeighborhood,
  Profile360Analytics,
  Profile360DrillItem,
  Profile360Metric,
  Profile360Relationship,
  Profile360Summary,
  TimelineEvent,
} from '@kyber/types';

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function readArray(value: unknown): readonly unknown[] {
  return Array.isArray(value) ? value : [];
}

function readNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function readString(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback;
}

function readMetric(record: Record<string, unknown>, keys: readonly string[], fallback = 0): number {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return fallback;
}

export function metric(label: string, value: string | number, tone: Profile360Metric['tone'] = 'default', detail?: string): Profile360Metric {
  return { label, value, tone, detail };
}

export function getProfile360Summary(entity: Entity, timeline: readonly TimelineEvent[], neighborhood: EntityNeighborhood | null): Profile360Summary {
  const m = entity.metadata;
  const analytics = readRecord(m['analytics'] ?? m['behavioral'] ?? m['intelligence']);
  const financial = readRecord(m['financial'] ?? m['wallets']);
  const system = readRecord(m['system'] ?? m['automation'] ?? m['orchestration']);
  const devices = readRecord(m['devices'] ?? analytics['devices']);

  const walletCount = readMetric(m, ['walletCount', 'wallet_count', 'wallets'], readArray(m['wallets']).length || neighborhood?.nodes.filter((n) => n.type === 'wallet').length || 0);
  const agentCount = readMetric(m, ['agentCount', 'agent_count', 'agents'], readArray(m['agents']).length || neighborhood?.nodes.filter((n) => n.type === 'agent').length || 0);
  const journeyCount = readMetric(m, ['journeyCount', 'active_journeys', 'journeys'], timeline.filter((event) => event.type.includes('journey')).length);
  const rewardStatus = readString(m['rewardStatus'] ?? financial['reward_status'], entity.tags.includes('rewarded') ? 'eligible' : 'monitoring');
  const automationRatio = readMetric(analytics, ['automation_ratio', 'automationRatio'], readMetric(system, ['automation_ratio', 'automationRatio'], 0));
  const activeRegions = readMetric(analytics, ['active_regions', 'activeRegions', 'regions'], readArray(analytics['regions']).length);
  const platformSummary = readString(m['platformSummary'] ?? devices['summary'] ?? analytics['platform_summary'], 'mixed');
  const spendingSignal = readString(financial['spending_signal'] ?? financial['spendingSignal'], 'steady');

  const base = [
    metric('Wallets', walletCount, walletCount > 0 ? 'good' : 'default'),
    metric('Agents', agentCount, agentCount > 0 ? 'info' : 'default'),
    metric('Last seen', readString(m['lastSeen'] ?? m['last_seen'], entity.updatedAt), 'default'),
  ];

  const typeMetrics: readonly Profile360Metric[] = entity.type === 'agent'
    ? [
      metric('Owner', readString(m['owner'] ?? system['owner'], 'unassigned'), 'info'),
      metric('Executions', readMetric(system, ['execution_count', 'executionCount'], timeline.filter((e) => e.type.includes('execution')).length), 'default'),
      metric('Delegation', readString(m['delegationStatus'] ?? system['delegation_status'], 'bounded'), 'warn'),
      metric('Runtime', readString(m['runtimeStatus'] ?? system['runtime_status'], entity.health.status), 'default'),
    ]
    : entity.type === 'organization'
      ? [
        metric('Treasury', readString(financial['treasury'] ?? m['treasury'], `$${readMetric(financial, ['treasury_usd', 'treasuryUsd'], 0).toLocaleString()}`), 'info'),
        metric('Members', readMetric(system, ['active_members', 'activeMembers'], neighborhood?.nodes.filter((n) => n.type === 'human' || n.type === 'customer').length ?? 0), 'default'),
        metric('Workflows', readMetric(system, ['workflows', 'active_workflows'], 0), 'default'),
        metric('Delegations', readMetric(system, ['delegations', 'permission_delegations'], neighborhood?.edges.filter((e) => e.type.includes('delegation')).length ?? 0), 'warn'),
      ]
      : [
        metric('Rewards', rewardStatus, rewardStatus === 'eligible' ? 'good' : 'default'),
        metric('Automation', `${Math.round(automationRatio * 100)}%`, automationRatio > 0.6 ? 'info' : 'default'),
        metric('Regions', activeRegions, activeRegions > 1 ? 'info' : 'default'),
        metric('Journeys', journeyCount, journeyCount > 0 ? 'info' : 'default'),
      ];

  return {
    status: entity.health.status,
    lastSeen: readString(m['lastSeen'] ?? m['last_seen'], entity.updatedAt),
    walletCount,
    agentCount,
    trust: entity.trustScore,
    risk: entity.riskScore,
    primaryMetrics: [...base, ...typeMetrics],
    secondaryMetrics: [
      metric('Device/platform', platformSummary, 'default'),
      metric('Spend', spendingSignal, spendingSignal === 'elevated' ? 'warn' : 'default'),
      metric('Protocol use', readMetric(analytics, ['protocol_count', 'protocolCount'], neighborhood?.nodes.filter((n) => n.type === 'protocol').length ?? 0), 'default'),
      metric('Graph edges', neighborhood?.edges.length ?? 0, 'default'),
    ],
  };
}

export function getRelationships(entity: Entity, neighborhood: EntityNeighborhood | null): readonly Profile360Relationship[] {
  if (!neighborhood) return [];
  return neighborhood.edges.map((edge) => {
    const targetId = edge.source === entity.id ? edge.target : edge.source;
    const target = neighborhood.nodes.find((node) => node.id === targetId);
    return {
      id: edge.id,
      sourceId: edge.source,
      targetId,
      targetType: target?.type ?? 'external',
      targetLabel: target?.label ?? targetId,
      relationshipType: edge.label ?? edge.type,
      strength: edge.weight,
      trustScore: target?.trustScore,
      riskScore: target?.riskScore,
      firstSeen: readString(edge.metadata['firstSeen'] ?? edge.metadata['first_seen'], ''),
      lastSeen: readString(edge.metadata['lastSeen'] ?? edge.metadata['last_seen'], ''),
      metadata: edge.metadata,
    };
  });
}

export function getAnalytics(entity: Entity, timeline: readonly TimelineEvent[], neighborhood: EntityNeighborhood | null): Profile360Analytics {
  const analytics = readRecord(entity.metadata['analytics'] ?? entity.metadata['behavioral'] ?? entity.metadata['intelligence']);
  const financial = readRecord(entity.metadata['financial']);
  const eventTypes = timeline.reduce<Record<string, number>>((acc, event) => ({ ...acc, [event.type]: (acc[event.type] ?? 0) + 1 }), {});
  const nodeTypes = (neighborhood?.nodes ?? []).reduce<Record<string, number>>((acc, node) => ({ ...acc, [node.type]: (acc[node.type] ?? 0) + 1 }), {});

  const fromRecord = (source: unknown, fallback: readonly Profile360Metric[]): readonly Profile360Metric[] => {
    const record = readRecord(source);
    const entries = Object.entries(record).slice(0, 5);
    return entries.length > 0 ? entries.map(([label, value]) => metric(label, typeof value === 'number' ? value : String(value), 'default')) : fallback;
  };

  return {
    activeHours: fromRecord(analytics['active_hours'], [metric('events', timeline.length), metric('latest', timeline[0]?.type ?? 'none')]),
    regions: fromRecord(analytics['regions'], [metric('active', readNumber(analytics['active_regions']), 'info')]),
    devices: fromRecord(analytics['devices'], [metric('devices', nodeTypes['device'] ?? 0)]),
    browsers: fromRecord(analytics['browsers'], [metric('browsers', nodeTypes['browser'] ?? 0)]),
    protocols: fromRecord(analytics['protocols'], [metric('protocols', nodeTypes['protocol'] ?? 0)]),
    platforms: fromRecord(analytics['platforms'], [metric('platforms', nodeTypes['platform'] ?? 0)]),
    spendingPatterns: fromRecord(financial['spending_patterns'], [metric('financial events', eventTypes['transaction'] ?? eventTypes['financial'] ?? 0)]),
    rewardOpportunities: fromRecord(financial['reward_opportunities'], [metric('reward events', eventTypes['reward'] ?? 0)]),
    trustSignals: [metric('trust', entity.trustScore.toFixed(2), entity.trustScore > 0.7 ? 'good' : 'warn'), metric('risk', entity.riskScore.toFixed(2), entity.riskScore < 0.3 ? 'good' : 'warn')],
    anomalyIndicators: [metric('anomaly', entity.anomalyScore.toFixed(2), entity.anomalyScore > 0.4 ? 'bad' : 'good'), metric('causal chains', new Set(timeline.map((event) => event.causalityId).filter(Boolean)).size)],
  };
}

export function eventToDrillItem(event: TimelineEvent): Profile360DrillItem {
  return {
    id: event.id,
    kind: event.traceId ? 'execution_trace' : 'event',
    label: event.title,
    subtitle: event.description,
    timestamp: event.timestamp,
    entityId: event.entityId,
    metadata: { ...event.metadata, traceId: event.traceId, causalityId: event.causalityId },
  };
}

export function relationshipToDrillItem(relationship: Profile360Relationship): Profile360DrillItem {
  return {
    id: relationship.targetId,
    kind: relationship.targetType === 'external' ? 'relationship' : relationship.targetType,
    label: relationship.targetLabel,
    subtitle: relationship.relationshipType,
    timestamp: relationship.lastSeen,
    entityId: relationship.targetId,
    metadata: relationship.metadata,
  };
}
