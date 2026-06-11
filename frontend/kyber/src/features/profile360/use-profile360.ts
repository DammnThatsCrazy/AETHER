import { useEffect, useMemo, useState } from 'react';
import { api } from '@kyber/lib/api/endpoints';
import { isLocalMocked } from '@kyber/lib/env';
import { useWebSocket } from '@kyber/hooks/use-websocket';
import { getMockEntity } from '@kyber/fixtures/entities';
import { getMockEntityNeighborhood } from '@kyber/fixtures/graph';
import { getMockTimeline } from '@kyber/fixtures/entities';
import type { Entity, EntityType, GraphEdge, GraphNode, Profile360EntityType, Profile360LiveMessage, Profile360Payload, Profile360Reference, Profile360Section } from '@kyber/types';
import { profile360Actions, profile360Store, toTimelineEvent, useProfile360Store } from './profile360-store';

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function normalizeEntity(raw: unknown, id: string, type: Profile360EntityType): Entity {
  const data = asRecord(raw);
  const now = new Date().toISOString();
  return {
    id: String(data.id ?? data.user_id ?? data.entity_id ?? id),
    type: (data.type ?? type) as EntityType,
    name: String(data.name ?? data.label ?? data.displayLabel ?? id),
    displayLabel: String(data.displayLabel ?? data.label ?? data.name ?? id),
    createdAt: String(data.createdAt ?? data.created_at ?? now),
    updatedAt: String(data.updatedAt ?? data.updated_at ?? now),
    health: { status: String(asRecord(data.health).status ?? 'unknown') as Entity['health']['status'], lastChecked: now },
    trustScore: Number(data.trustScore ?? data.trust_score ?? asRecord(data.intelligence).trust_score ?? 0),
    riskScore: Number(data.riskScore ?? data.risk_score ?? asRecord(data.risk).score ?? 0),
    anomalyScore: Number(data.anomalyScore ?? data.anomaly_score ?? 0),
    needsHelp: Boolean(data.needsHelp ?? data.needs_help ?? false),
    needsHelpReason: data.needsHelpReason || data.needs_help_reason ? String(data.needsHelpReason ?? data.needs_help_reason) : undefined,
    tags: Array.isArray(data.tags) ? data.tags.map(String) : [],
    metadata: data,
  };
}

function normalizeNode(input: unknown, index: number): GraphNode {
  const node = asRecord(input);
  const id = String(node.id ?? node.entity_id ?? `node-${index}`);
  return {
    id,
    type: (node.type ?? node.entity_type ?? 'external') as GraphNode['type'],
    label: String(node.label ?? node.name ?? id),
    trustScore: node.trustScore === undefined && node.trust_score === undefined ? undefined : Number(node.trustScore ?? node.trust_score),
    riskScore: node.riskScore === undefined && node.risk_score === undefined ? undefined : Number(node.riskScore ?? node.risk_score),
    anomalyScore: node.anomalyScore === undefined && node.anomaly_score === undefined ? undefined : Number(node.anomalyScore ?? node.anomaly_score),
    metadata: asRecord(node.metadata ?? node.properties),
  };
}

function normalizeEdge(input: unknown, index: number): GraphEdge {
  const edge = asRecord(input);
  return {
    id: String(edge.id ?? `${edge.source ?? 'source'}-${edge.target ?? 'target'}-${index}`),
    source: String(edge.source ?? edge.from ?? ''),
    target: String(edge.target ?? edge.to ?? ''),
    type: String(edge.type ?? edge.relationship ?? 'related'),
    weight: Number(edge.weight ?? edge.confidence ?? 1),
    label: edge.label ? String(edge.label) : String(edge.type ?? edge.relationship ?? 'related'),
    metadata: asRecord(edge.metadata ?? edge.properties),
  };
}

function normalizeProfile360Payload(raw: Record<string, unknown>, fallbackId: string, fallbackType: Profile360EntityType): Profile360Payload | null {
  const entityRaw = asRecord(raw.entity);
  if (!entityRaw.id && !raw.sections && !raw.graph && !raw.timeline) return null;
  const entity = normalizeEntity(entityRaw.id ? entityRaw : raw, fallbackId, fallbackType);
  const graphRaw = asRecord(raw.graph);
  const timelineRaw = Array.isArray(raw.timeline) ? raw.timeline : [];
  const audit = asRecord(raw.alignment_audit ?? raw.alignmentAudit);
  const tenantId = raw.tenant_id ? String(raw.tenant_id) : raw.tenantId ? String(raw.tenantId) : undefined;
  const surface = raw.surface === 'kyber_internal' || raw.surface === 'end_user' ? raw.surface : undefined;
  const visibility = raw.visibility === 'internal_full' || raw.visibility === 'redacted' ? raw.visibility : undefined;
  return {
    entity,
    ...(tenantId ? { tenantId } : {}),
    ...(surface ? { surface } : {}),
    ...(visibility ? { visibility } : {}),
    sections: asRecord(raw.sections) as Profile360Payload['sections'],
    timeline: timelineRaw.map((event, index) => toTimelineEvent(event, `evt-${index}`)),
    graph: {
      nodes: (Array.isArray(graphRaw.nodes) ? graphRaw.nodes : []).map(normalizeNode),
      edges: (Array.isArray(graphRaw.edges) ? graphRaw.edges : []).map(normalizeEdge),
      alignmentAudit: asRecord(graphRaw.alignment_audit ?? graphRaw.alignmentAudit),
    },
    alignmentAudit: audit,
    raw,
  };
}

function refs(values: unknown[], fallbackType: Profile360EntityType): readonly Profile360Reference[] {
  return values.slice(0, 12).map((item, i) => {
    const v = asRecord(item);
    const id = String(v.id ?? v.entity_id ?? v.wallet_address ?? v.session_id ?? `${fallbackType}-${i}`);
    return { id, type: (v.type ?? v.entity_type ?? fallbackType) as Profile360EntityType, label: String(v.label ?? v.name ?? v.display_name ?? id), metadata: v };
  });
}

function buildSessionsSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const sessData = asRecord(raw.sessions_data);
  const devData = asRecord(raw.devices_data);
  const rawSessions: unknown[] = Array.isArray(sessData.sessions) ? sessData.sessions : Array.isArray(sessData.items) ? sessData.items : Array.isArray(sessData.data) ? sessData.data : [];
  const rawDevices: unknown[] = Array.isArray(devData.devices) ? devData.devices : Array.isArray(devData.items) ? devData.items : Array.isArray(devData.data) ? devData.data : [];

  let vpnCount = 0; let torCount = 0; let durationSum = 0;
  const platformCounts = new Map<string, number>();
  for (const s of rawSessions) {
    const sr = asRecord(s);
    const geo = asRecord(sr.geo ?? sr.location);
    if (Boolean(sr.vpn ?? sr.is_vpn ?? geo.vpn)) vpnCount++;
    if (Boolean(sr.tor ?? sr.is_tor ?? geo.tor)) torCount++;
    durationSum += typeof sr.duration_seconds === 'number' ? sr.duration_seconds : typeof sr.duration === 'number' ? sr.duration : 0;
    const plat = String(sr.platform ?? sr.device_type ?? 'web');
    platformCounts.set(plat, (platformCounts.get(plat) ?? 0) + 1);
  }
  const topPlatform = [...platformCounts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—';
  const avgDuration = rawSessions.length > 0 ? Math.round(durationSum / rawSessions.length) : 0;

  return [
    {
      id: 'sessions-overview',
      title: 'Session intelligence',
      summary: 'Recent sessions — device, OS, browser, platform, geo (VPN/proxy/Tor flags), entry/exit URL, referrer, UTM/campaign context, duration, page-view count.',
      metrics: [
        { id: 'sessions', label: 'Sessions', value: rawSessions.length },
        { id: 'vpn', label: 'VPN/Proxy', value: vpnCount, tone: vpnCount > 0 ? 'warning' : 'default' },
        { id: 'tor', label: 'Tor', value: torCount, tone: torCount > 0 ? 'danger' : 'default' },
        { id: 'avg-dur', label: 'Avg duration', value: `${avgDuration}s` },
        { id: 'top-platform', label: 'Top platform', value: topPlatform },
        { id: 'devices', label: 'Devices', value: rawDevices.length },
      ],
      references: refs(rawSessions, 'session'),
      data: { sessions: rawSessions, devices: rawDevices, raw_sessions: sessData, raw_devices: devData },
    },
  ];
}

function buildJourneysSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const jData = asRecord(raw.journeys_data);
  const rawJourneys: unknown[] = Array.isArray(jData.journeys) ? jData.journeys : Array.isArray(jData.items) ? jData.items : Array.isArray(jData.data) ? jData.data : [];

  let completedCount = 0; let abandonedCount = 0; let totalSteps = 0;
  const campaignSet = new Set<string>();
  for (const j of rawJourneys) {
    const jr = asRecord(j);
    if (Boolean(jr.completed ?? jr.converted)) completedCount++;
    if (Boolean(jr.abandoned ?? jr.dropped)) abandonedCount++;
    const steps = Array.isArray(jr.steps) ? jr.steps : [];
    totalSteps += steps.length;
    const cid = String(jr.campaign_id ?? jr.campaign ?? '');
    if (cid) campaignSet.add(cid);
  }
  const completionRate = rawJourneys.length > 0 ? Math.round((completedCount / rawJourneys.length) * 100) : 0;
  const abandonRate = rawJourneys.length > 0 ? Math.round((abandonedCount / rawJourneys.length) * 100) : 0;

  return [
    {
      id: 'journeys-overview',
      title: 'Journey intelligence',
      summary: 'Cross-session journey chains — steps, conversion, drop-off rates, abandonment flags, and campaign linkage ("where" attribution).',
      metrics: [
        { id: 'journeys', label: 'Journeys', value: rawJourneys.length },
        { id: 'completed', label: 'Completed', value: completedCount, tone: completedCount > 0 ? 'good' : 'default' },
        { id: 'abandoned', label: 'Abandoned', value: abandonedCount, tone: abandonedCount > 0 ? 'warning' : 'default' },
        { id: 'completion-rate', label: 'Completion %', value: completionRate, unit: '%', tone: completionRate > 60 ? 'good' : completionRate > 30 ? 'warning' : 'danger' },
        { id: 'abandon-rate', label: 'Abandon %', value: abandonRate, unit: '%', tone: abandonRate > 40 ? 'danger' : 'default' },
        { id: 'avg-steps', label: 'Avg steps', value: rawJourneys.length > 0 ? Math.round(totalSteps / rawJourneys.length) : 0 },
        { id: 'campaigns', label: 'Campaigns', value: campaignSet.size },
      ],
      references: refs(rawJourneys, 'journey'),
      data: { journeys: rawJourneys, raw: jData },
    },
  ];
}

function buildWalletsSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const wData = asRecord(raw.wallets_data);
  const rawWallets: unknown[] = Array.isArray(wData.wallets) ? wData.wallets : Array.isArray(wData.items) ? wData.items : Array.isArray(wData.data) ? wData.data : [];

  let totalUsd = 0; let txCount = 0;
  for (const w of rawWallets) {
    const wr = asRecord(w);
    if (typeof wr.total_usd === 'number') totalUsd += wr.total_usd;
    else if (typeof wr.balance_usd === 'number') totalUsd += wr.balance_usd;
    const txs = Array.isArray(wr.recent_transactions) ? wr.recent_transactions : Array.isArray(wr.transactions) ? wr.transactions : [];
    txCount += txs.length;
  }

  return [
    {
      id: 'wallets-overview',
      title: 'Web3 wallet profiles',
      summary: 'Linked wallets — token balances (USD), recent on-chain transactions, protocol interactions (DEX swaps, lending, staking, governance), NFT holdings, and Web3 loyalty signals.',
      metrics: [
        { id: 'wallets', label: 'Wallets', value: rawWallets.length },
        { id: 'total-usd', label: 'Total USD', value: totalUsd > 0 ? `$${(totalUsd / 1000).toFixed(1)}k` : '—' },
        { id: 'tx-count', label: 'Transactions', value: txCount },
      ],
      references: rawWallets.slice(0, 12).map((w, i) => {
        const wr = asRecord(w);
        const addr = String(wr.wallet_address ?? wr.address ?? wr.id ?? `wallet-${i}`);
        const chain = String(wr.chain ?? wr.network ?? '');
        return { id: addr, type: 'wallet' as Profile360EntityType, label: `${addr.slice(0, 8)}…${addr.slice(-4)}${chain ? ` (${chain})` : ''}`, metadata: wr };
      }),
      data: { wallets: rawWallets, raw: wData },
    },
  ];
}

function buildBehavioralSections(raw: Record<string, unknown>, entity: Entity): readonly Profile360Section[] {
  const bData = asRecord(raw.behavioral ?? raw.behavioral_data);
  const sigData = asRecord(raw.signals_data);
  const signals: unknown[] = Array.isArray(sigData.signals) ? sigData.signals : Array.isArray(bData.signals) ? bData.signals : [];

  const familyCounts = new Map<string, number>();
  let highSeverity = 0;
  for (const s of signals) {
    const sr = asRecord(s);
    const fam = String(sr.family ?? sr.signal_family ?? 'other');
    familyCounts.set(fam, (familyCounts.get(fam) ?? 0) + 1);
    const sev = String(sr.severity ?? sr.level ?? '');
    if (sev === 'high' || sev === 'critical') highSeverity++;
  }

  const intentScore = Number(asRecord(bData.scores ?? bData).intent_score ?? bData.intent ?? 0);
  const frictionScore = Number(asRecord(bData.scores ?? bData).friction_score ?? bData.friction ?? 0);
  const continuityScore = Number(asRecord(bData.scores ?? bData).continuity_score ?? bData.continuity ?? 0);

  return [
    {
      id: 'behavioral-signals',
      title: 'Behavioral "Why" intelligence',
      summary: 'Signal families explaining entity behavior — intent residue, wallet friction, continuity, trust decay, cross-domain correlation. Human-readable explanations of anomalous patterns.',
      metrics: [
        { id: 'signals', label: 'Signals', value: signals.length },
        { id: 'high-sev', label: 'High severity', value: highSeverity, tone: highSeverity > 0 ? 'danger' : 'default' },
        { id: 'families', label: 'Families', value: familyCounts.size },
        { id: 'intent', label: 'Intent score', value: intentScore > 0 ? intentScore.toFixed(2) : '—', tone: intentScore > 0.7 ? 'good' : intentScore > 0.4 ? 'warning' : 'default' },
        { id: 'friction', label: 'Friction', value: frictionScore > 0 ? frictionScore.toFixed(2) : '—', tone: frictionScore > 0.6 ? 'danger' : 'default' },
        { id: 'continuity', label: 'Continuity', value: continuityScore > 0 ? continuityScore.toFixed(2) : '—', tone: continuityScore > 0.7 ? 'good' : 'warning' },
        { id: 'trust', label: 'Trust', value: Math.round(entity.trustScore * 100), unit: '%', tone: entity.trustScore > 0.75 ? 'good' : 'warning' },
        { id: 'anomaly', label: 'Anomaly', value: Math.round(entity.anomalyScore * 100), unit: '%', tone: entity.anomalyScore > 0.55 ? 'danger' : 'default' },
      ],
      references: refs(signals, 'human'),
      data: { signals, family_counts: Object.fromEntries(familyCounts), behavioral: bData },
    },
  ];
}

function buildClusterSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const clData = asRecord(raw.cluster_data);
  const cluster = asRecord(clData.cluster ?? clData);
  const clustersData = asRecord(raw.clusters_data);
  const allClusters: unknown[] = Array.isArray(clustersData.items) ? clustersData.items : Array.isArray(clustersData.clusters) ? clustersData.clusters : [];
  return [
    {
      id: 'cluster-overview',
      title: 'Identity cluster',
      summary: 'Primary identity cluster membership — linked identifiers, merge/split history, confidence score.',
      metrics: [
        { id: 'found', label: 'In cluster', value: clData.found ? 'Yes' : 'No', tone: clData.found ? 'good' : 'default' },
        { id: 'cluster-id', label: 'Cluster ID', value: String(cluster.cluster_id ?? cluster.id ?? '—') },
        { id: 'confidence', label: 'Confidence', value: cluster.confidence != null ? Number(cluster.confidence).toFixed(2) : '—' },
        { id: 'all-clusters', label: 'Memberships', value: allClusters.length },
      ],
      references: refs(allClusters, 'human'),
      data: { cluster, all_clusters: allClusters, raw: clData },
    },
  ];
}

function buildAgentsSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const aData = asRecord(raw.agents_data);
  const items: unknown[] = Array.isArray(aData.items) ? aData.items : Array.isArray(aData.agents) ? aData.agents : [];
  const summary = asRecord(aData.summary);
  return [
    {
      id: 'agents-overview',
      title: 'Agent ownership',
      summary: 'Agent configurations and executions owned by this entity — execution count, status, and delegation context.',
      metrics: [
        { id: 'agents', label: 'Agents', value: Number(summary.agent_count ?? items.length) },
        { id: 'executions', label: 'Executions', value: Number(summary.execution_count ?? 0) },
      ],
      references: refs(items, 'agent'),
      data: { items, raw: aData },
    },
  ];
}

function buildConsentSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const cData = asRecord(raw.consent_data);
  const status = String(cData.consent_status ?? 'unknown');
  const eligibility = String(cData.activation_eligibility ?? 'observe_only');
  return [
    {
      id: 'consent-overview',
      title: 'Consent & activation',
      summary: 'Consent state, allowed/restricted use cases, DSR state, and activation eligibility.',
      metrics: [
        { id: 'status', label: 'Status', value: status, tone: status === 'granted' ? 'good' : status === 'revoked' ? 'danger' : 'warning' },
        { id: 'eligibility', label: 'Eligibility', value: eligibility },
        { id: 'allowed', label: 'Allowed uses', value: Array.isArray(cData.allowed_use_cases) ? cData.allowed_use_cases.length : 0 },
        { id: 'blocked', label: 'Blocked uses', value: Array.isArray(cData.blocked_use_cases) ? cData.blocked_use_cases.length : 0, tone: Array.isArray(cData.blocked_use_cases) && cData.blocked_use_cases.length > 0 ? 'danger' : 'default' },
        { id: 'dsr', label: 'DSR state', value: String(cData.dsr_state ?? 'none') },
      ],
      references: [],
      data: cData,
    },
  ];
}

function buildQualitySections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const qData = asRecord(raw.quality_data);
  const scores = asRecord(qData.scores ?? qData);
  return [
    {
      id: 'quality-overview',
      title: 'Profile quality',
      summary: 'Data completeness, freshness, confidence, and readiness status across all profile dimensions.',
      metrics: [
        { id: 'readiness', label: 'Readiness', value: String(qData.readiness_status ?? '—') },
        { id: 'completeness', label: 'Completeness', value: scores.completeness != null ? `${Math.round(Number(scores.completeness) * 100)}%` : '—' },
        { id: 'freshness', label: 'Freshness', value: scores.freshness != null ? `${Math.round(Number(scores.freshness) * 100)}%` : '—' },
        { id: 'confidence', label: 'Confidence', value: scores.confidence != null ? `${Math.round(Number(scores.confidence) * 100)}%` : '—' },
        { id: 'missing', label: 'Missing dims', value: Array.isArray(qData.missing_dimensions) ? qData.missing_dimensions.length : 0, tone: Array.isArray(qData.missing_dimensions) && qData.missing_dimensions.length > 0 ? 'warning' : 'default' },
        { id: 'stale', label: 'Stale dims', value: Array.isArray(qData.stale_dimensions) ? qData.stale_dimensions.length : 0, tone: Array.isArray(qData.stale_dimensions) && qData.stale_dimensions.length > 0 ? 'warning' : 'default' },
      ],
      references: [],
      data: qData,
    },
  ];
}

function buildRecommendationsSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const rData = asRecord(raw.recommendations_data);
  const items: unknown[] = Array.isArray(rData.items) ? rData.items : Array.isArray(rData.recommendations) ? rData.recommendations : [];
  return [
    {
      id: 'recommendations-overview',
      title: 'Recommendations',
      summary: 'Active intelligence recommendations — next best actions, retargeting, and playbook suggestions.',
      metrics: [
        { id: 'count', label: 'Recommendations', value: items.length },
        { id: 'viewed', label: 'Viewed', value: items.filter(i => Boolean(asRecord(i).viewed_at)).length },
      ],
      references: refs(items, 'human'),
      data: { items, raw: rData },
    },
  ];
}

function buildOutcomesSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const oData = asRecord(raw.outcomes_data);
  const items: unknown[] = Array.isArray(oData.items) ? oData.items : Array.isArray(oData.outcomes) ? oData.outcomes : [];
  return [
    {
      id: 'outcomes-overview',
      title: 'Outcomes',
      summary: 'Observed outcomes from executed recommendations — success rate, value delivered, and confidence feedback.',
      metrics: [
        { id: 'count', label: 'Outcomes', value: items.length },
        { id: 'success', label: 'Success', value: items.filter(i => asRecord(i).outcome_status === 'success').length, tone: 'good' },
        { id: 'failure', label: 'Failure', value: items.filter(i => asRecord(i).outcome_status === 'failure').length, tone: 'danger' },
      ],
      references: refs(items, 'human'),
      data: { items, raw: oData },
    },
  ];
}

function buildIntelligenceSections(raw: Record<string, unknown>, entity: Entity): readonly Profile360Section[] {
  const iData = asRecord(raw.intelligence_data);
  const predictions: unknown[] = Array.isArray(iData.predictions) ? iData.predictions : [];
  const signals: unknown[] = Array.isArray(iData.signals) ? iData.signals : [];
  return [
    {
      id: 'intelligence-overview',
      title: 'Intelligence',
      summary: 'ML-derived signals, predictions, cluster membership, and behavioral intelligence summaries.',
      metrics: [
        { id: 'trust', label: 'Trust', value: Math.round(entity.trustScore * 100), unit: '%', tone: entity.trustScore > 0.75 ? 'good' : 'warning' },
        { id: 'risk', label: 'Risk', value: Math.round(entity.riskScore * 100), unit: '%', tone: entity.riskScore > 0.55 ? 'danger' : 'default' },
        { id: 'predictions', label: 'Predictions', value: predictions.length },
        { id: 'signals', label: 'Signals', value: signals.length },
      ],
      references: refs(signals, 'human'),
      data: { predictions, signals, raw: iData },
    },
  ];
}

function buildProvenanceSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const pData = asRecord(raw.provenance_data);
  const sources: unknown[] = Array.isArray(pData.sources) ? pData.sources : [];
  return [
    {
      id: 'provenance-overview',
      title: 'Provenance',
      summary: 'Source attribution for every data point in this profile — data origins, collection timestamps, and consent linkage.',
      metrics: [
        { id: 'sources', label: 'Sources', value: sources.length },
        { id: 'status', label: 'Status', value: String(pData.source_status ?? '—') },
      ],
      references: [],
      data: { sources, raw: pData },
    },
  ];
}

function buildAttributionSections(raw: Record<string, unknown>): readonly Profile360Section[] {
  const attrData = asRecord(raw.attribution_data);
  const touchpoints: unknown[] = Array.isArray(attrData.touchpoints) ? attrData.touchpoints : Array.isArray(attrData.items) ? attrData.items : [];

  const channelCredit = new Map<string, number>();
  let totalConversions = 0;
  for (const tp of touchpoints) {
    const tpr = asRecord(tp);
    const channel = String(tpr.channel ?? tpr.source ?? 'direct');
    const credit = typeof tpr.credit === 'number' ? tpr.credit : typeof tpr.attribution_credit === 'number' ? tpr.attribution_credit : 0;
    channelCredit.set(channel, (channelCredit.get(channel) ?? 0) + credit);
    if (Boolean(tpr.is_conversion ?? tpr.converted)) totalConversions++;
  }
  const topChannel = [...channelCredit.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—';

  return [
    {
      id: 'attribution-journey',
      title: 'Attribution "Where" intelligence',
      summary: 'Multi-touch attribution journey — weighted credit per channel/source/campaign. Surfaces where users came from, which touchpoints influenced conversion, and campaign ROI.',
      metrics: [
        { id: 'touchpoints', label: 'Touchpoints', value: touchpoints.length },
        { id: 'conversions', label: 'Conversions', value: totalConversions, tone: totalConversions > 0 ? 'good' : 'default' },
        { id: 'channels', label: 'Channels', value: channelCredit.size },
        { id: 'top-channel', label: 'Top channel', value: topChannel },
      ],
      references: refs(touchpoints, 'journey'),
      data: { touchpoints, channel_credit: Object.fromEntries(channelCredit), raw: attrData },
    },
  ];
}

function buildSections(entity: Entity, raw: Record<string, unknown>): Profile360Payload['sections'] {
  const intelligence = asRecord(raw.intelligence ?? entity.metadata.intelligence);
  const behavioral = asRecord(raw.behavioral ?? entity.metadata.behavioral);
  const financial = asRecord(raw.financial ?? raw.wallet ?? entity.metadata.wallet);
  const system = asRecord(raw.system ?? raw.runtime ?? raw.device);
  const analytics = asRecord(raw.analytics ?? raw.attribution ?? raw.summary);

  return {
    identity: [
      {
        id: 'identity-attribution',
        title: 'Attribution intelligence',
        summary: 'Identifiers, owners, devices, browsers, platforms, regions, and confidence signals unified around this entity.',
        metrics: [
          { id: 'trust', label: 'Trust', value: Math.round(entity.trustScore * 100), unit: '%', tone: entity.trustScore > 0.75 ? 'good' : 'warning' },
          { id: 'risk', label: 'Risk', value: Math.round(entity.riskScore * 100), unit: '%', tone: entity.riskScore > 0.55 ? 'danger' : 'default' },
          { id: 'anomaly', label: 'Anomaly', value: Math.round(entity.anomalyScore * 100), unit: '%', tone: entity.anomalyScore > 0.55 ? 'warning' : 'default' },
        ],
        references: refs([...(Array.isArray(raw.identifiers) ? raw.identifiers : []), ...(Array.isArray(raw.connections) ? raw.connections : [])], 'human'),
        data: intelligence,
      },
    ],
    system: [
      { id: 'system-runtime', title: 'System footprint', summary: 'Device/browser/platform attribution, sessions, uptime, active hours, and automation context.', data: system, references: refs(Array.isArray(raw.sessions) ? raw.sessions : [], 'session') },
      { id: 'automation', title: 'Automation behavior', summary: 'Agent ownership, permissions, delegations, protocol usage, and active execution windows.', data: behavioral, references: refs(Array.isArray(raw.agents) ? raw.agents : [], 'agent') },
    ],
    financial: [
      { id: 'wallet-flows', title: 'Wallet flows', summary: 'Balances, rewards, spending behavior, treasury movements, and protocol interactions.', data: financial, references: refs(Array.isArray(raw.wallets) ? raw.wallets : [], 'wallet') },
      { id: 'rewards', title: 'Rewards and incentives', summary: 'Reward accruals, claims, attribution, and linked journeys.', data: asRecord(raw.rewards), references: refs(Array.isArray(raw.transactions) ? raw.transactions : [], 'transaction') },
    ],
    analytics: [
      { id: 'behavioral-intelligence', title: 'Behavioral intelligence', summary: 'Active hours, regions, cohort behavior, platform usage, automation ratio, and trust/risk drivers.', data: analytics, references: refs(Array.isArray(raw.journeys) ? raw.journeys : [], 'journey') },
    ],
    debug: [
      { id: 'raw-payload', title: 'Raw normalized payload', summary: 'Backend payload, drill references, causality IDs, execution traces, and diagnostics for wiring.', data: raw, references: refs(Array.isArray(raw.traces) ? raw.traces : [], 'execution_trace') },
    ],
    sessions: buildSessionsSections(raw),
    journeys: buildJourneysSections(raw),
    wallets: buildWalletsSections(raw),
    behavioral: buildBehavioralSections(raw, entity),
    attribution: buildAttributionSections(raw),
    cluster: buildClusterSections(raw),
    agents: buildAgentsSections(raw),
    consent: buildConsentSections(raw),
    quality: buildQualitySections(raw),
    recommendations: buildRecommendationsSections(raw),
    outcomes: buildOutcomesSections(raw),
    intelligence: buildIntelligenceSections(raw, entity),
    provenance: buildProvenanceSections(raw),
  };
}

async function fetchProfile360(type: Profile360EntityType, id: string): Promise<Profile360Payload> {
  if (isLocalMocked()) {
    const mock = getMockEntity(id) ?? getMockEntity('cust-acme-001')!;
    const neighborhood = getMockEntityNeighborhood(mock.id);
    const mockRaw = { ...mock.metadata, cluster_data: {}, clusters_data: {}, agents_data: {}, consent_data: {}, quality_data: {}, recommendations_data: {}, outcomes_data: {}, intelligence_data: {}, provenance_data: {} };
    return {
      entity: { ...mock, type: type === 'human' ? 'human' : mock.type },
      sections: buildSections(mock, mockRaw),
      timeline: [...(getMockTimeline(mock.id)?.events ?? [])],
      graph: { nodes: [...neighborhood.nodes], edges: [...neighborhood.edges] },
      raw: mockRaw,
    };
  }

  const [
    profile, timelineResponse, graphResponse, behavioral,
    sessions, devices, journeys, wallets, attributionJourney, signals,
    cluster, clusters, agents, consent, quality, recommendations, outcomes, intelligence, provenance,
  ] = await Promise.all([
    api.profile360.full(type, id).catch(() => api.profile.full(id)),
    api.profile360.timeline(type, id, { limit: 250 }).catch(() => api.profile.timeline(id, { limit: 250 })).catch(() => ({ events: [] })),
    api.profile360.graph(type, id, { limit: 750 }).catch(() => api.profile.graph(id)).catch(() => ({ nodes: [], edges: [] })),
    api.behavioral.entity(id).catch(() => ({})),
    api.profile.sessions(id, 30).catch(() => ({})),
    api.profile.devices(id).catch(() => ({})),
    api.profile.journeys(id).catch(() => ({})),
    api.profile.wallets(id).catch(() => ({})),
    api.attribution.journey(id).catch(() => ({})),
    api.behavioral.signals(id).catch(() => ({ signals: [] })),
    api.profile.cluster(id).catch(() => ({})),
    api.profile.clusters(id).catch(() => ({ items: [] })),
    api.profile.agents(id).catch(() => ({ items: [] })),
    api.profile.consent(id).catch(() => ({ consent_status: 'unknown' })),
    api.profile.quality(id).catch(() => ({})),
    api.profile.recommendations(id).catch(() => ({ items: [] })),
    api.profile.outcomes(id).catch(() => ({ items: [] })),
    api.intelligence.entityCluster(id).catch(() => ({})),
    api.profile.provenance(id).catch(() => ({})),
  ]);

  const extraDimensions = {
    sessions_data: sessions, devices_data: devices, journeys_data: journeys,
    wallets_data: wallets, attribution_data: attributionJourney, signals_data: signals,
    behavioral,
    cluster_data: cluster, clusters_data: clusters,
    agents_data: agents,
    consent_data: consent,
    quality_data: quality,
    recommendations_data: recommendations,
    outcomes_data: outcomes,
    intelligence_data: intelligence,
    provenance_data: provenance,
  };

  const normalized = normalizeProfile360Payload(asRecord(profile), id, type);
  if (normalized) {
    return {
      ...normalized,
      raw: { ...asRecord(normalized.raw), ...extraDimensions },
    };
  }

  const raw: Record<string, unknown> = { ...asRecord(profile), ...extraDimensions };
  const graphRaw = asRecord(graphResponse);
  const rawNodes = (Array.isArray(graphRaw.nodes) ? graphRaw.nodes : Array.isArray(graphRaw.connections) ? graphRaw.connections : []) as unknown[];
  const rawEdges = (Array.isArray(graphRaw.edges) ? graphRaw.edges : []) as unknown[];
  const events = (asRecord(timelineResponse).events ?? raw.timeline ?? raw.events ?? []) as unknown[];
  const entity = normalizeEntity(raw, id, type);

  return {
    entity,
    sections: buildSections(entity, raw),
    timeline: events.map((event, index) => toTimelineEvent(event, `evt-${index}`)),
    graph: {
      nodes: rawNodes.map(normalizeNode),
      edges: rawEdges.map(normalizeEdge),
      alignmentAudit: asRecord(graphRaw.alignment_audit ?? graphRaw.alignmentAudit),
    },
    raw,
  };
}

export function useProfile360(type: Profile360EntityType, id: string) {
  const payload = useProfile360Store((state) => state.payloads[id]);
  const timeline = useProfile360Store((state) => state.timelines[id]);
  const graph = useProfile360Store((state) => state.graphs[id]);
  const highlightedNodeIds = useProfile360Store((state) => state.highlightedNodeIds);
  const activeTimelineFilters = useProfile360Store((state) => state.activeTimelineFilters);
  const [isLoading, setIsLoading] = useState(!payload);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(!profile360Store.getState().payloads[id]);
    setError(null);
    fetchProfile360(type, id)
      .then((nextPayload) => {
        if (!cancelled) profile360Actions.upsertPayload(nextPayload);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load Profile360');
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => { cancelled = true; };
  }, [type, id]);

  const ws = useWebSocket({
    path: `/v1/profile/${id}/stream`,
    enabled: Boolean(id),
    onMessage: (message) => profile360Actions.applyLiveMessage(message as Profile360LiveMessage),
  });

  // Timeline append/prepend stream
  useWebSocket({
    path: `/v1/profile/${id}/timeline/stream`,
    enabled: Boolean(id),
    onMessage: (raw) => {
      const msg = raw as Record<string, unknown>;
      const event = msg.event ?? msg.data;
      if (event) {
        profile360Actions.applyLiveMessage({ entityId: id, event: toTimelineEvent(event, `live-${Date.now()}`) } as Profile360LiveMessage);
      }
    },
  });

  // Graph node/edge mutation stream
  useWebSocket({
    path: `/v1/profile/${id}/graph/stream`,
    enabled: Boolean(id),
    onMessage: (raw) => {
      const msg = raw as Record<string, unknown>;
      const nodeRaw = msg.node as Record<string, unknown> | undefined;
      const edgeRaw = msg.edge as Record<string, unknown> | undefined;
      const node = nodeRaw ? normalizeNode(nodeRaw, 0) : undefined;
      const edge = edgeRaw ? normalizeEdge(edgeRaw, 0) : undefined;
      if (node || edge) {
        profile360Actions.applyLiveMessage({ entityId: id, node, edge } as Profile360LiveMessage);
      }
    },
  });

  useEffect(() => {
    profile360Actions.setWebsocketStatus(ws.status);
  }, [ws.status]);

  const filteredTimeline = useMemo(() => {
    const source = timeline ?? payload?.timeline ?? [];
    if (activeTimelineFilters.length === 0) return source;
    return source.filter((event) => activeTimelineFilters.includes(event.type));
  }, [activeTimelineFilters, payload?.timeline, timeline]);

  return {
    payload,
    entity: payload?.entity,
    sections: payload?.sections ?? {},
    timeline: filteredTimeline,
    graph: graph ?? payload?.graph ?? { nodes: [], edges: [] },
    highlightedNodeIds,
    isLoading,
    error,
    websocketStatus: ws.status,
    actions: profile360Actions,
  };
}
