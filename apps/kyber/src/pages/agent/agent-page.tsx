import { useState } from 'react';
import { PageWrapper } from '@kyber/components/layout';
import {
  Card, CardContent, CardHeader, CardTitle,
  Badge, Button, Tabs, TabsList, TabsTrigger, TabsContent,
  EmptyState, LoadingState, ScrollArea, Select,
} from '@aether/ui';
import { cn, formatRelativeTime } from '@kyber/lib/utils';
import { useAgentDispatchView } from '@kyber/features/operator';

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}
function asList(v: unknown): unknown[] { return Array.isArray(v) ? v : []; }
function fmt(v: unknown, fallback = '—'): string { return v == null || v === '' ? fallback : String(v); }

const WORKER_TYPES = [
  { value: 'analysis', label: 'Analysis' },
  { value: 'enrichment', label: 'Enrichment' },
  { value: 'resolution', label: 'Resolution' },
  { value: 'fraud_scan', label: 'Fraud Scan' },
  { value: 'behavioral_scan', label: 'Behavioral Scan' },
  { value: 'oracle_proof', label: 'Oracle Proof' },
];

const PRIORITY_OPTS = [
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'normal', label: 'Normal' },
  { value: 'low', label: 'Low' },
];

function workerStatusColor(status: string) {
  if (status === 'running' || status === 'active') return 'bg-success';
  if (status === 'idle') return 'bg-text-muted';
  if (status === 'error') return 'bg-danger';
  return 'bg-warning';
}

export function AgentPage() {
  const { status, audit, submitTask, killSwitch } = useAgentDispatchView();
  const [workerType, setWorkerType] = useState('analysis');
  const [priority, setPriority] = useState('normal');
  const [entityId, setEntityId] = useState('');
  const [killConfirm, setKillConfirm] = useState(false);

  const agentData = asRecord(status.data);
  const workers = asList(agentData.workers);
  const auditData = asRecord(audit.data);
  const records = asList(auditData.records);

  const handleDispatch = () => {
    if (!entityId.trim()) return;
    void submitTask.mutate({ workerType, priority, payload: { entity_id: entityId } });
    setEntityId('');
  };

  const handleKillSwitch = (action: string) => {
    void killSwitch.mutate(action);
    setKillConfirm(false);
  };

  const isKillActive = Boolean(agentData.kill_switch);

  return (
    <PageWrapper
      title="Agent Dispatch"
      subtitle="Submit tasks, monitor workers, manage kill switch"
      actions={
        isKillActive ? (
          <Button variant="secondary" size="sm" onClick={() => handleKillSwitch('deactivate')} disabled={killSwitch.isLoading}>
            Resume Agents
          </Button>
        ) : (
          <Button variant="danger" size="sm" onClick={() => setKillConfirm(true)}>
            Kill Switch
          </Button>
        )
      }
    >
      {killConfirm && (
        <Card className="border-danger mb-4">
          <CardContent className="flex items-center justify-between py-3">
            <span className="text-sm text-danger font-mono">Halt all agent workers immediately?</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setKillConfirm(false)}>Cancel</Button>
              <Button size="sm" variant="danger" onClick={() => handleKillSwitch('activate')} disabled={killSwitch.isLoading}>
                {killSwitch.isLoading ? 'Halting…' : 'Confirm Halt'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {status.isLoading ? <LoadingState lines={2} /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          {[
            { label: 'Active Workers', value: agentData.active_workers ?? 0 },
            { label: 'Queued Tasks', value: agentData.queued_tasks ?? 0 },
            { label: 'Completed', value: agentData.completed_tasks ?? 0 },
            { label: 'Failed', value: agentData.failed_tasks ?? 0 },
          ].map(({ label, value }) => (
            <div key={label} className="bg-surface-raised border border-border-default rounded px-3 py-2">
              <p className="text-[10px] text-text-muted font-mono">{label}</p>
              <p className="text-xl font-bold font-mono text-text-primary">{String(value)}</p>
            </div>
          ))}
        </div>
      )}

      <Tabs defaultValue="dispatch">
        <TabsList>
          <TabsTrigger value="dispatch">Dispatch</TabsTrigger>
          <TabsTrigger value="workers">Workers</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>

        <TabsContent value="dispatch">
          <Card>
            <CardHeader><CardTitle className="font-mono text-xs">Submit Task</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Select label="Worker Type" options={WORKER_TYPES} value={workerType} onChange={setWorkerType} />
                <Select label="Priority" options={PRIORITY_OPTS} value={priority} onChange={setPriority} />
                <div className="space-y-1">
                  <label className="text-xs text-text-secondary font-mono">Entity ID</label>
                  <input
                    type="text"
                    value={entityId}
                    onChange={e => setEntityId(e.target.value)}
                    placeholder="ent_..."
                    className="w-full bg-surface-sunken border border-border-default rounded px-2 py-1.5 text-xs font-mono text-text-primary focus:outline-none focus:border-accent"
                    onKeyDown={e => e.key === 'Enter' && handleDispatch()}
                  />
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={handleDispatch}
                disabled={submitTask.isLoading || !entityId.trim()}
              >
                {submitTask.isLoading ? 'Dispatching…' : 'Dispatch Task'}
              </Button>
              {submitTask.data != null && (
                <p className="text-xs text-success font-mono">Task queued — {fmt(asRecord(submitTask.data).task_id)}</p>
              )}
              {submitTask.error != null && (
                <p className="text-xs text-danger font-mono">Failed: {String(submitTask.error)}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="workers">
          {workers.length === 0 ? (
            <EmptyState title="No workers" description="No active worker processes." icon="◯" />
          ) : (
            <div className="space-y-2">
              {workers.map((w, i) => {
                const worker = asRecord(w);
                return (
                  <Card key={i}>
                    <CardContent className="flex items-center justify-between py-2">
                      <div className="flex items-center gap-2">
                        <span className={cn('w-2 h-2 rounded-full', workerStatusColor(fmt(worker.status)))} />
                        <span className="text-xs font-mono text-text-primary">{fmt(worker.worker_type)}</span>
                      </div>
                      <div className="flex items-center gap-3 text-[10px] font-mono text-text-muted">
                        {Boolean(worker.current_task) && <span>task: {fmt(worker.current_task)}</span>}
                        <Badge variant={fmt(worker.status) === 'error' ? 'danger' : 'default'}>{fmt(worker.status)}</Badge>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="audit">
          {audit.isLoading ? <LoadingState lines={5} /> : (
            <ScrollArea maxHeight="500px">
              <div className="space-y-1">
                {records.length === 0 ? (
                  <EmptyState title="No audit records" description="No agent activity recorded." icon="○" />
                ) : records.map((r, i) => {
                  const rec = asRecord(r);
                  return (
                    <div key={i} className="flex items-start gap-3 px-2 py-1 text-xs font-mono border-b border-border-default last:border-0">
                      <span className="text-text-muted shrink-0 w-20">{formatRelativeTime(fmt(rec.timestamp ?? rec.created_at))}</span>
                      <span className="text-accent shrink-0">{fmt(rec.worker_type ?? rec.action)}</span>
                      <span className="text-text-secondary truncate">{fmt(rec.entity_id ?? rec.task_id ?? rec.detail)}</span>
                      <Badge variant={fmt(rec.status) === 'failed' ? 'danger' : 'default'} className="ml-auto shrink-0">{fmt(rec.status)}</Badge>
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          )}
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
