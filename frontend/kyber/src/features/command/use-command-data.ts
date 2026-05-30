import { useState, useEffect } from 'react';
import type { Controller, ControllerObjective, ControllerSchedule, CHARStatus, ControllerDisplayMode } from '@kyber/types';
import { isLocalMocked } from '@kyber/lib/env';
import { getMockControllers, MOCK_OBJECTIVES, MOCK_SCHEDULES, MOCK_CHAR_STATUS } from '@kyber/fixtures/controllers';
import { api } from '@kyber/lib/api/endpoints';

interface AgentStatusResponse {
  active_workers?: number;
  queued_tasks?: number;
  completed_tasks?: number;
  failed_tasks?: number;
  kill_switch?: boolean;
  workers?: {
    worker_type: string;
    status: string;
    current_task?: string | null;
    [key: string]: unknown;
  }[];
  [key: string]: unknown;
}

interface AuditRecord {
  task_id?: string;
  worker_type?: string;
  action?: string;
  status?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  priority?: string;
  payload?: Record<string, unknown>;
  result?: unknown;
  [key: string]: unknown;
}

interface AuditResponse {
  records: AuditRecord[];
  total: number;
}

function mapToControllers(status: AgentStatusResponse): Controller[] {
  const workers = status.workers ?? [];
  return workers.map((w) => ({
    name: w.worker_type as Controller['name'],
    health: {
      status: (w.status === 'active' || w.status === 'running' ? 'healthy' : 'degraded') as 'healthy' | 'degraded',
      lastChecked: new Date().toISOString(),
    },
    queueDepth: 0,
    activeObjectives: w.current_task ? 1 : 0,
    blockedItems: 0,
    lastActivity: new Date().toISOString(),
    uptime: 'unknown',
    stagedMutations: 0,
    recoveryState: 'idle' as const,
  }));
}

function mapToObjectives(audit: AuditResponse): ControllerObjective[] {
  const now = new Date().toISOString();
  return audit.records
    .filter((r): r is AuditRecord & { task_id: string } => !!r.task_id)
    .slice(0, 20)
    .map(r => ({
      id: r.task_id,
      controller: (r.worker_type ?? 'intake') as ControllerObjective['controller'],
      title: r.action ?? r.worker_type ?? 'Task',
      description: (r.payload?.description as string) ?? '',
      status: (r.status === 'completed' ? 'completed' : r.status === 'failed' ? 'blocked' : r.status === 'running' ? 'active' : 'deferred') as ControllerObjective['status'],
      priority: r.priority ? Number(r.priority) : 0,
      createdAt: r.created_at ?? now,
      updatedAt: r.completed_at ?? r.started_at ?? r.created_at ?? now,
      blockedReason: r.status === 'failed' ? (r.result as string) ?? 'Unknown failure' : undefined,
    }));
}

function mapToCHARStatus(status: AgentStatusResponse): CHARStatus {
  const workerCount = status.active_workers ?? 0;
  const queuedCount = status.queued_tasks ?? 0;
  const failedCount = status.failed_tasks ?? 0;
  const coordinationState: CHARStatus['coordinationState'] =
    failedCount > 0 ? 'critical' : queuedCount > 10 ? 'elevated' : 'nominal';

  return {
    overallDirective: status.kill_switch ? 'KILL SWITCH ACTIVE — all operations halted' : 'Normal operations',
    activePriorities: status.workers
      ?.filter(w => w.current_task)
      .map(w => `${w.worker_type}: ${w.current_task}`) ?? [],
    escalations: failedCount > 0 ? [`${failedCount} failed task(s) require attention`] : [],
    briefSummary: `${workerCount} active worker(s), ${queuedCount} queued task(s)`,
    lastBriefAt: new Date().toISOString(),
    coordinationState,
  };
}

export function useCommandData() {
  const [controllers, setControllers] = useState<Controller[]>([]);
  const [objectives, setObjectives] = useState<ControllerObjective[]>([]);
  const [schedules, setSchedules] = useState<ControllerSchedule[]>([]);
  const [charStatus, setCharStatus] = useState<CHARStatus | null>(null);
  const [displayMode, setDisplayMode] = useState<ControllerDisplayMode>('functional');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setControllers(getMockControllers());
      setObjectives(MOCK_OBJECTIVES);
      setSchedules(MOCK_SCHEDULES);
      setCharStatus(MOCK_CHAR_STATUS);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    Promise.all([
      api.agent.status(),
      api.agent.audit(),
    ])
      .then(([statusResp, auditResp]) => {
        const status = statusResp as AgentStatusResponse;
        const audit = auditResp as AuditResponse;

        setControllers(mapToControllers(status));
        setObjectives(mapToObjectives(audit));
        setSchedules([]); // Schedules derived from audit records if available
        setCharStatus(mapToCHARStatus(status));
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load command data');
        setControllers([]);
        setObjectives([]);
        setSchedules([]);
        setCharStatus(null);
        setIsLoading(false);
      });
  }, []);

  return { controllers, objectives, schedules, charStatus, displayMode, setDisplayMode, isLoading, error };
}
