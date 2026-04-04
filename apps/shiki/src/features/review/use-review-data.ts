import { useState, useEffect, useCallback } from 'react';
import type { ReviewBatch, ReviewItem, ReviewStatus, AuditEntry, ActionAttribution } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockReviewBatches, getMockAuditTrail } from '@shiki/fixtures/review';

export function useReviewData() {
  const [batches, setBatches] = useState<ReviewBatch[]>([]);
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isLocalMocked()) {
      setBatches([...getMockReviewBatches()]);
      setAuditTrail([...getMockAuditTrail()]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    fetch('/api/v1/intelligence/review/batches')
      .then(r => r.json())
      .then(() => {
        setBatches([...getMockReviewBatches()]);
        setAuditTrail([...getMockAuditTrail()]);
        setIsLoading(false);
      })
      .catch(() => {
        setBatches([]);
        setIsLoading(false);
      });
  }, []);

  const selectedBatch = batches.find(b => b.id === selectedBatchId) ?? null;

  const resolveItem = useCallback((itemId: string, status: ReviewStatus, reason: string, attribution: ActionAttribution) => {
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
  }, [selectedBatchId]);

  return { batches, selectedBatch, selectedBatchId, setSelectedBatchId, auditTrail, resolveItem, isLoading };
}
