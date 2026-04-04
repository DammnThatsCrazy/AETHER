import type { HealthStatus, Severity } from './common';

export type ControllerName =
  | 'governance'
  | 'char'
  | 'intake'
  | 'gouf'
  | 'zeong'
  | 'triage'
  | 'verification'
  | 'commit'
  | 'recovery'
  | 'chronicle'
  | 'trigger'
  | 'relay';

export type ControllerDisplayMode = 'functional' | 'named' | 'expressive';

export const CONTROLLER_FUNCTIONAL_NAMES: Record<ControllerName, string> = {
  governance: 'Policy & Governance',
  char: 'Top Orchestrator',
  intake: 'Signal Intake',
  gouf: 'Graph Topology',
  zeong: 'Anomaly Watch',
  triage: 'Priority Triage',
  verification: 'Evidence Verification',
  commit: 'Action Commit',
  recovery: 'Recovery & Rollback',
  chronicle: 'Timeline & Memory',
  trigger: 'Schedule & Triggers',
  relay: 'Notification Relay',
};

export const CONTROLLER_EXPRESSIVE_NAMES: Record<ControllerName, string> = {
  governance: 'The Arbiter',
  char: 'CHAR — The Red Comet',
  intake: 'The Gatekeeper',
  gouf: 'GOUF — The Cartographer',
  zeong: 'ZEONG — The Watcher',
  triage: 'The Surgeon',
  verification: 'The Auditor',
  commit: 'The Executor',
  recovery: 'The Restorer',
  chronicle: 'The Chronicler',
  trigger: 'The Clockmaker',
  relay: 'The Herald',
};

export interface Controller {
  readonly name: ControllerName;
  readonly health: HealthStatus;
  readonly queueDepth: number;
  readonly activeObjectives: number;
  readonly blockedItems: number;
  readonly lastActivity: string;
  readonly uptime: string;
  readonly stagedMutations: number;
  readonly recoveryState: 'idle' | 'active' | 'pending';
}

export interface ControllerObjective {
  readonly id: string;
  readonly controller: ControllerName;
  readonly title: string;
  readonly description: string;
  readonly status: 'active' | 'blocked' | 'completed' | 'deferred';
  readonly priority: number;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly blockedReason?: string | undefined;
}

export interface ControllerSchedule {
  readonly id: string;
  readonly controller: ControllerName;
  readonly type: 'cron' | 'interval' | 'one-shot';
  readonly expression: string;
  readonly nextRun: string;
  readonly lastRun?: string | undefined;
  readonly enabled: boolean;
  readonly missedFires: number;
}

export interface CHARStatus {
  readonly overallDirective: string;
  readonly activePriorities: readonly string[];
  readonly escalations: readonly string[];
  readonly briefSummary: string;
  readonly lastBriefAt: string;
  readonly coordinationState: 'nominal' | 'elevated' | 'critical';
}
