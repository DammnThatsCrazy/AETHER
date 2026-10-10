export type NodeKind = 'human' | 'organization' | 'agent' | 'campaign' | 'cluster' | 'journey' | 'system'

export type LifecycleStage = 'observe' | 'detect' | 'explain' | 'predict' | 'decide' | 'act' | 'verify' | 'learn'

export type InvestigationStatus = 'open' | 'monitoring' | 'awaiting approval' | 'verifying' | 'learned'

export type NodeData = {
  id: string
  label: string
  kind: NodeKind
  x: number
  y: number
  radius: number
  signal?: string
  meta: string
  tone: 'violet' | 'teal' | 'amber' | 'blue' | 'pink' | 'slate'
  selected?: boolean
}

export type EdgeData = {
  id: string
  source: string
  target: string
  label: string
  type: 'observed' | 'inferred' | 'predicted' | 'confirmed' | 'disputed'
  confidence: number
  path?: string
}

export const nodes: NodeData[] = [
  { id: 'ent-2041', label: 'Maya Chen', kind: 'human', x: 46, y: 43, radius: 17, signal: 'relationship changed', meta: 'Person · ent_2041', tone: 'violet' },
  { id: 'ent-1870', label: 'Northstar Labs', kind: 'organization', x: 28, y: 25, radius: 13, meta: 'Organization · org_1870', tone: 'teal' },
  { id: 'agent-semantic', label: 'Semantic worker', kind: 'agent', x: 69, y: 26, radius: 12, signal: 'reconciling', meta: 'Agent · wrk_semantic', tone: 'blue' },
  { id: 'cluster-14', label: 'Cluster 14', kind: 'cluster', x: 23, y: 67, radius: 14, meta: '42 entities · high cohesion', tone: 'pink' },
  { id: 'campaign-q3', label: 'Q3 expansion', kind: 'campaign', x: 74, y: 65, radius: 15, signal: 'propagating', meta: 'Campaign · cmp_q3_expansion', tone: 'amber' },
  { id: 'journey-88', label: 'Expansion journey', kind: 'journey', x: 87, y: 45, radius: 10, meta: 'Journey · jny_0088', tone: 'teal' },
  { id: 'system-aether', label: 'Aether core', kind: 'system', x: 52, y: 80, radius: 9, meta: 'System · aether_core', tone: 'slate' },
]

export const edges: EdgeData[] = [
  { id: 'e1', source: 'ent-1870', target: 'ent-2041', label: 'employs', type: 'confirmed', confidence: 0.98 },
  { id: 'e2', source: 'agent-semantic', target: 'ent-2041', label: 'resolved identity', type: 'inferred', confidence: 0.91 },
  { id: 'e3', source: 'campaign-q3', target: 'ent-2041', label: 'exposed to', type: 'observed', confidence: 0.99 },
  { id: 'e4', source: 'campaign-q3', target: 'cluster-14', label: 'influences', type: 'predicted', confidence: 0.74 },
  { id: 'e5', source: 'ent-2041', target: 'journey-88', label: 'progressing', type: 'observed', confidence: 0.87 },
  { id: 'e6', source: 'cluster-14', target: 'ent-1870', label: 'shares signals', type: 'inferred', confidence: 0.68 },
  { id: 'e7', source: 'system-aether', target: 'agent-semantic', label: 'orchestrates', type: 'confirmed', confidence: 0.99 },
  { id: 'e8', source: 'journey-88', target: 'campaign-q3', label: 'converted by', type: 'disputed', confidence: 0.49 },
]

export const navGroups: { label: string; items: [string, string][] }[] = [
  { label: 'Observe', items: [['Fleet', '◌'], ['Live intelligence', '✦'], ['Events', '⌁'], ['Journeys', '↝'], ['Campaign activity', '◒'], ['Agent telemetry', '⌬']] },
  { label: 'Investigate', items: [['Noesis', '◈'], ['Graph', '⊙'], ['Entities', '◍'], ['Clusters', '✺'], ['Fraud', '△'], ['Diagnostics', '⌁'], ['Evidence', '▱']] },
  { label: 'Predict', items: [['Forecasts', '◌'], ['Risk', '△'], ['Journey prediction', '↝']] },
  { label: 'Decide', items: [['Findings', '◒'], ['Review queue', '⊞'], ['Approvals', '✓'], ['Comparison', '⇄']] },
  { label: 'Act', items: [['Commands', '›'], ['Replay', '▶'], ['Recompute', '↻'], ['Repair', '⚒'], ['Campaign intervention', '◉']] },
  { label: 'Govern', items: [['Tenants', '⌘'], ['Consent', '◫'], ['Policies', '◫'], ['Audit', '≋']] },
  { label: 'Build', items: [['Lab', '⌁'], ['Fixtures', '□'], ['Integrations', '⌘'], ['SDK state', '◍'], ['Model validation', '✓']] },
]

export type CommandItem = {
  label: string
  detail: string
  icon: NodeKind
  action: 'entity' | 'investigation' | 'evidence' | 'agent' | 'lens' | 'health'
  value?: string
}

export const commandItems: CommandItem[] = [
  { label: 'Inspect Maya Chen', detail: 'entity · ent_2041', icon: 'human', action: 'entity', value: 'ent-2041' },
  { label: 'Open investigation inv_2041', detail: 'resume saved context', icon: 'journey', action: 'investigation' },
  { label: 'Toggle evidence mode', detail: 'show provenance overlay', icon: 'system', action: 'evidence' },
  { label: 'Jump to semantic-worker', detail: 'agent activity', icon: 'agent', action: 'agent', value: 'agent-semantic' },
  { label: 'Open Fleet lens', detail: 'observe · 4,821 entities', icon: 'cluster', action: 'lens', value: 'Fleet' },
  { label: 'Open Review queue', detail: 'decide · 3 items need judgment', icon: 'journey', action: 'lens', value: 'Review queue' },
  { label: 'Inspect intelligence health', detail: 'trust index · 94', icon: 'system', action: 'health' },
]

export const observations = [
  { time: '11:42', label: 'Identity signal resolved', detail: 'Semantic worker · 3 sources', kind: 'agent' as NodeKind },
  { time: '10:18', label: 'Journey stage advanced', detail: 'Maya Chen · expansion', kind: 'journey' as NodeKind },
  { time: '08:06', label: 'Campaign influence detected', detail: 'Q3 expansion · +12.4%', kind: 'campaign' as NodeKind },
]

export const lifecycle: { stage: LifecycleStage; label: string; short: string }[] = [
  { stage: 'observe', label: 'Observe', short: 'what exists' },
  { stage: 'detect', label: 'Detect', short: 'what changed' },
  { stage: 'explain', label: 'Explain', short: 'why it matters' },
  { stage: 'predict', label: 'Predict', short: 'what may happen' },
  { stage: 'decide', label: 'Decide', short: 'what to do' },
  { stage: 'act', label: 'Act', short: 'make a move' },
  { stage: 'verify', label: 'Verify', short: 'what resulted' },
  { stage: 'learn', label: 'Learn', short: 'what changed' },
]

export const stateCopy = {
  detected: {
    eyebrow: 'Meaningful change · 14 min ago',
    title: 'A relationship is carrying more weight than the evidence suggests.',
    body: 'Maya Chen is moving through the expansion journey faster than her organization’s historical baseline. The shift is connected to Q3 expansion, but attribution is not yet settled.',
  },
  evidence: {
    eyebrow: 'Evidence mode · causal boundary visible',
    title: 'The signal is supported, but one attribution remains contested.',
    body: 'Three observations agree across identity, journey, and campaign systems. A fourth source points to an independent referral, keeping the campaign influence below confirmed confidence.',
  },
  action: {
    eyebrow: 'Recommendation · authority check',
    title: 'Ask the semantic worker to reconcile the disputed edge.',
    body: 'A supervised reconciliation should reduce identity ambiguity without mutating the source systems. It is reversible and scoped to one relationship.',
  },
  verifying: {
    eyebrow: 'Verification running · observed state retained',
    title: 'The workspace is watching for the relationship to settle.',
    body: 'Expected: confidence rises above 0.84 and the referral contradiction is marked stale. New evidence will be added to this investigation as it arrives.',
  },
  learned: {
    eyebrow: 'Learning complete · new baseline established',
    title: 'Kyber updated its understanding of the path.',
    body: 'The relationship is now confirmed at 0.88 confidence. The recommendation changed from reconcile to monitor, and the investigation remains available for review.',
  },
} as const
