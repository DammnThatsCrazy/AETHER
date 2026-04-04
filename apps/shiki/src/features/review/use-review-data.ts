import { useState, useEffect, useCallback } from 'react';
import type { ReviewBatch, ReviewItem, ReviewStatus, AuditEntry, ActionAttribution, ActionClass, Severity } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockReviewBatches, getMockAuditTrail } from '@shiki/fixtures/review';
import { api } from '@shiki/lib/api/endpoints';

interface AuditRecord {
  task_id?: string;
  worker_type?: string;
  action?: string;
  status?: string;
  created_at?: string;
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

function mapSeverity(priority?: string): Severity {
  if (priority === 'critical') return 'P0';
  if (priority === 'high') return 'P1';
  if (priority === 'medium') return 'P2';
  if (priority === 'low') return 'P3';
  return 'info';
}

function mapAuditToBatches(audit: AuditResponse): ReviewBatch[] {
  const now = new Date().toISOString();
  // Group audit records into review batches by worker_type
  const batchMap = new Map<string, ReviewItem[]>();

  for (const record of audit.records) {
    const batchKey = record.worker_type ?? 'default';
    if (!batchMap.has(batchKey)) {
      batchMap.set(batchKey, []);
    }

    const item: ReviewItem = {
      id: record.task_id ?? `item-${Date.now()}-${Math.random()}`,
      batchId: `batch-${batchKey}`,
      title: (record.payload?.title as string) ?? record.action ?? 'Review Item',
      description: (record.payload?.description as string) ?? '',
      mutationClass: ((record.payload?.action_class as number) ?? 1) as ActionClass,
      severity: mapSeverity(record.priority),
      before: (record.payload?.before as Record<string, unknown>) ?? {},
      after: (record.payload?.after as Record<string, unknown>) ?? {},
      evidence: ((record.payload?.evidence as string[]) ?? []) as readonly string[],
      rationale: (record.payload?.rationale as string) ?? '',
      confidence: (record.payload?.confidence as number) ?? 0,
      downstreamImpact: (record.payload?.downstream_impact as string) ?? '',
      reversible: (record.payload?.reversible as boolean) ?? true,
      status: (record.status === 'completed' ? 'approved' : record.status === 'failed' ? 'rejected' : 'pending') as ReviewStatus,
    };

    batchMap.get(batchKey)!.push(item);
  }

  return Array.from(batchMap.entries()).map(([key, items], idx) => ({
    id: `batch-${key}-${idx}`,
    title: `${key} Review Batch`,
    description: `Review batch for ${key} controller with ${items.length} item(s)`,
    controller: key,
    createdAt: items[0]?.id ? now : now,
    items,
    status: (items.every(i => i.status !== 'pending') ? 'approved' : 'pending') as ReviewStatus,
    submittedBy: key,
  }));
}

function makeSystemAttribution(workerType: string, timestamp: string): ActionAttribution {
  return {
    userId: `system-${workerType}`,
    displayName: workerType,
    email: '',
    role: 'system',
    timestamp,
    environment: 'production',
    reason: '',
    correlationId: '',
  };
}

function mapAuditToTrail(audit: AuditResponse): AuditEntry[] {
  return audit.records
    .filter((r): r is AuditRecord & { task_id: string } => !!r.task_id && r.status !== 'pending')
    .map(r => {
      const ts = r.completed_at ?? r.created_at ?? new Date().toISOString();
      return {
        id: `audit-${r.task_id}`,
        action: r.action ?? r.status ?? 'unknown',
        timestamp: ts,
        actor: makeSystemAttribution(r.worker_type ?? 'unknown', ts),
        itemId: r.task_id,
        batchId: r.worker_type ?? '',
        previousStatus: 'pending' as ReviewStatus,
        newStatus: (r.status === 'completed' ? 'approved' : r.status === 'failed' ? 'rejected' : 'pending') as ReviewStatus,
        reason: (r.result as Record<string, unknown>)?.reason as string ?? '',
      };
    });
}

export function useReviewData() {
  const [batches, setBatches] = useState<ReviewBatch[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setBatches([...getMockReviewBatches()]);
      setAuditTrail([...getMockAuditTrail()]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    api.agent.audit()
      .then((resp) => {
        const audit = resp as AuditResponse;
        setBatches(mapAuditToBatches(audit));
        setAuditTrail(mapAuditToTrail(audit));
        setIsLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load review data');
        setBatches([]);
        setAuditTrail([]);
        setIsLoading(false);
      });
  }, []);

  const selectedBatch = batches.find(b => b.id === selectedBatchId) ?? null;

  const resolveItem = useCallback((itemId: string, status: ReviewStatus, reason: string, attribution: ActionAttribution) => {
    if (isLocalMocked()) {
      // Local mock: just update state
      setBatches(prev => prev.map(batch => ({
        ...batch,
        items: batch.items.map(item =>
          item.id === itemId ? { ...item, status, resolution: { status, resolvedBy: attribution, reason } } : item
        ),
      })));

      const newEntry: AuditEntry = {
        id: `audit-${Date.now()}`,
        action: status,
        timestamp: new Date().toISOString(),
        actor: attribution,
        itemId,
        batchId: selectedBatchId ?? '',
        previousStatus: 'pending',
        newStatus: status,
        reason,
      };
      setAuditTrail(prev => [newEntry, ...prev]);
      return;
    }

    // Live mode: submit decision to backend, then update local state
    api.agent.submitTask('review', 'high', {
      item_id: itemId,
      decision: status,
      reason,
      actor: attribution,
      batch_id: selectedBatchId ?? '',
    })
      .then(() => {
        setBatches(prev => prev.map(batch => ({
          ...batch,
          items: batch.items.map(item =>
            item.id === itemId ? { ...item, status, resolution: { status, resolvedBy: attribution, reason } } : item
          ),
        })));

        const newEntry: AuditEntry = {
          id: `audit-${Date.now()}`,
          action: status,
          timestamp: new Date().toISOString(),
          actor: attribution,
          itemId,
          batchId: selectedBatchId ?? '',
          previousStatus: 'pending',
          newStatus: status,
          reason,
        };
        setAuditTrail(prev => [newEntry, ...prev]);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to submit review decision');
      });
  }, [selectedBatchId]);

  return { batches, selectedBatch, selectedBatchId, setSelectedBatchId, auditTrail, resolveItem, isLoading, error };
}
