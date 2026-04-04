import type {
  Controller,
  ControllerName,
  ControllerObjective,
  ControllerSchedule,
  CHARStatus,
} from '@shiki/types';

const now = new Date();
const ago = (minutes: number) => new Date(now.getTime() - minutes * 60_000).toISOString();
const fromNow = (minutes: number) => new Date(now.getTime() + minutes * 60_000).toISOString();

// ---------------------------------------------------------------------------
// All 12 controllers
// ---------------------------------------------------------------------------

export const MOCK_CONTROLLERS: Controller[] = [
  {
    name: 'char',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 0,
    activeObjectives: 3,
    blockedItems: 0,
    lastActivity: ago(1),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'governance',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 2,
    activeObjectives: 1,
    blockedItems: 0,
    lastActivity: ago(10),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'intake',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 47,
    activeObjectives: 2,
    blockedItems: 0,
    lastActivity: ago(0),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'gouf',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 8,
    activeObjectives: 2,
    blockedItems: 0,
    lastActivity: ago(3),
    uptime: '14d 7h 23m',
    stagedMutations: 4,
    recoveryState: 'idle',
  },
  {
    name: 'zeong',
    health: { status: 'degraded', message: 'Elevated anomaly detection latency', lastChecked: ago(1) },
    queueDepth: 12,
    activeObjectives: 4,
    blockedItems: 1,
    lastActivity: ago(1),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'triage',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 5,
    activeObjectives: 2,
    blockedItems: 0,
    lastActivity: ago(2),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'verification',
    health: { status: 'healthy', lastChecked: ago(2) },
    queueDepth: 3,
    activeObjectives: 1,
    blockedItems: 0,
    lastActivity: ago(15),
    uptime: '14d 7h 23m',
    stagedMutations: 12,
    recoveryState: 'idle',
  },
  {
    name: 'commit',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 0,
    activeObjectives: 0,
    blockedItems: 0,
    lastActivity: ago(20),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'recovery',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 0,
    activeObjectives: 0,
    blockedItems: 0,
    lastActivity: ago(60 * 24 * 3),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'chronicle',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 14,
    activeObjectives: 1,
    blockedItems: 0,
    lastActivity: ago(1),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'trigger',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 0,
    activeObjectives: 0,
    blockedItems: 0,
    lastActivity: ago(5),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
  {
    name: 'relay',
    health: { status: 'healthy', lastChecked: ago(1) },
    queueDepth: 1,
    activeObjectives: 1,
    blockedItems: 0,
    lastActivity: ago(5),
    uptime: '14d 7h 23m',
    stagedMutations: 0,
    recoveryState: 'idle',
  },
];

// ---------------------------------------------------------------------------
// Objectives (4+, some blocked)
// ---------------------------------------------------------------------------

export const MOCK_OBJECTIVES: ControllerObjective[] = [
  {
    id: 'obj-zeong-001',
    controller: 'zeong',
    title: 'Monitor Cluster C-892 wash-trading pattern',
    description: 'Continuous anomaly scan of all 47 nodes in cluster C-892 for wash-trading indicators.',
    status: 'active',
    priority: 1,
    createdAt: ago(60 * 24),
    updatedAt: ago(25),
  },
  {
    id: 'obj-zeong-002',
    controller: 'zeong',
    title: 'Detect event stream gaps for enterprise customers',
    description: 'Real-time detection of event stream interruptions exceeding 10 minutes for tier-1 customers.',
    status: 'active',
    priority: 1,
    createdAt: ago(60 * 24 * 14),
    updatedAt: ago(5),
  },
  {
    id: 'obj-gouf-001',
    controller: 'gouf',
    title: 'Re-index graph topology after wallet cluster merge',
    description: 'Rebuild adjacency indices after merging 3 wallet clusters into unified topology view.',
    status: 'blocked',
    priority: 2,
    createdAt: ago(60 * 6),
    updatedAt: ago(60),
    blockedReason: 'Waiting for verification controller to confirm cluster membership before re-index.',
  },
  {
    id: 'obj-intake-001',
    controller: 'intake',
    title: 'Process Nebula Finance onboarding event batch',
    description: 'Ingest and normalize 2,400 historical events from Nebula Finance initial data load.',
    status: 'active',
    priority: 2,
    createdAt: ago(180),
    updatedAt: ago(30),
  },
  {
    id: 'obj-triage-001',
    controller: 'triage',
    title: 'Prioritize enrichment backlog',
    description: 'Rank and assign 23 queued enrichment tasks to available agents by urgency and entity value.',
    status: 'active',
    priority: 1,
    createdAt: ago(38),
    updatedAt: ago(8),
  },
  {
    id: 'obj-verify-001',
    controller: 'verification',
    title: 'Validate graph enrichment batch #47',
    description: 'Verify 12 entity mutations from automated enrichment cycle against source data.',
    status: 'blocked',
    priority: 1,
    createdAt: ago(60),
    updatedAt: ago(15),
    blockedReason: 'Awaiting human review approval in review queue.',
  },
];

// ---------------------------------------------------------------------------
// Schedules (3+)
// ---------------------------------------------------------------------------

export const MOCK_SCHEDULES: ControllerSchedule[] = [
  {
    id: 'sched-trigger-001',
    controller: 'trigger',
    type: 'cron',
    expression: '0 */6 * * *',
    nextRun: fromNow(120),
    lastRun: ago(240),
    enabled: true,
    missedFires: 0,
  },
  {
    id: 'sched-trigger-002',
    controller: 'trigger',
    type: 'interval',
    expression: 'every 5 minutes',
    nextRun: fromNow(3),
    lastRun: ago(2),
    enabled: true,
    missedFires: 0,
  },
  {
    id: 'sched-chronicle-001',
    controller: 'chronicle',
    type: 'cron',
    expression: '0 0 * * *',
    nextRun: fromNow(60 * 14),
    lastRun: ago(60 * 10),
    enabled: true,
    missedFires: 0,
  },
  {
    id: 'sched-relay-001',
    controller: 'relay',
    type: 'cron',
    expression: '0 8 * * 1-5',
    nextRun: fromNow(60 * 18),
    lastRun: ago(60 * 24),
    enabled: true,
    missedFires: 1,
  },
];

// ---------------------------------------------------------------------------
// CHAR Status
// ---------------------------------------------------------------------------

export const MOCK_CHAR_STATUS: CHARStatus = {
  overallDirective: 'Maintain operational continuity. Prioritize resolution of Acme Corp event stream interruption (P0) and enrichment agent stuck loop (P1).',
  activePriorities: [
    'P0: Restore Acme Corp event stream — coordinate with relay for customer notification',
    'P1: Resolve enrichment-agent-04 stuck loop — reassign objective if not resolved in 15 min',
    'P2: Monitor wallet 0x7a3b trust score — escalate if further degradation detected',
    'P2: Complete review batch #47 — 12 mutations awaiting human approval',
  ],
  escalations: [
    'Acme Corp P0 escalated to Commander Bright at ' + ago(4),
  ],
  briefSummary: 'System is nominal with two active incidents. Acme Corp event stream has been silent for 18 minutes (P0, notified). Enrichment agent #04 is in a stuck loop with 23 entities backlogged (P1, paused). Wallet 0x7a3b under enhanced monitoring after trust score drop. All other controllers operating within normal parameters. Throughput: 34.2 events/sec, stable.',
  lastBriefAt: ago(2),
  coordinationState: 'elevated',
};

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

export function getMockControllers(): Controller[] {
  return MOCK_CONTROLLERS;
}

export function getMockController(name: ControllerName): Controller | undefined {
  return MOCK_CONTROLLERS.find((c) => c.name === name);
}

export function getMockObjectives(controller?: ControllerName): ControllerObjective[] {
  if (!controller) return MOCK_OBJECTIVES;
  return MOCK_OBJECTIVES.filter((o) => o.controller === controller);
}

export function getMockSchedules(controller?: ControllerName): ControllerSchedule[] {
  if (!controller) return MOCK_SCHEDULES;
  return MOCK_SCHEDULES.filter((s) => s.controller === controller);
}

export function getMockCHARStatus(): CHARStatus {
  return MOCK_CHAR_STATUS;
}
