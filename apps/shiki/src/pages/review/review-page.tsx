import { useState, useMemo, useCallback } from 'react';
import {
  Card, CardHeader, CardTitle, CardContent, CardFooter,
  Badge, SeverityBadge, StatusIndicator, Button,
  Tabs, TabsList, TabsTrigger, TabsContent,
  ScrollArea, GlyphIcon, TerminalSeparator,
  Modal, ModalHeader, ModalBody, ModalFooter,
  EmptyState,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { cn, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';
import { useAuth } from '@shiki/features/auth';
import { usePermissions, PermissionGate } from '@shiki/features/permissions';
import type {
  ReviewBatch, ReviewItem, ReviewStatus, AuditEntry,
  ActionClass, ActionAttribution, GraphDiff,
} from '@shiki/types';
import { getMockReviewBatches, getMockAuditTrail } from '@shiki/fixtures/review';

// ─── Status styling ────────────────────────────────────────────────────────

const statusVariant: Record<ReviewStatus, 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info'> = {
  pending: 'info',
  approved: 'success',
  rejected: 'danger',
  deferred: 'warning',
  reverted: 'accent',
};

const mutationClassLabels: Record<ActionClass, { label: string; variant: 'default' | 'accent' | 'success' | 'warning' | 'danger' | 'info' }> = {
  0: { label: 'Class 0 - Observe', variant: 'default' },
  1: { label: 'Class 1 - Annotate', variant: 'info' },
  2: { label: 'Class 2 - Enrich', variant: 'accent' },
  3: { label: 'Class 3 - Modify', variant: 'warning' },
  4: { label: 'Class 4 - Restructure', variant: 'danger' },
  5: { label: 'Class 5 - Override', variant: 'danger' },
};

// ─── Sub-components ────────────────────────────────────────────────────────

function JsonDiffPanel({ label, before, after }: {
  readonly label: string;
  readonly before: Record<string, unknown>;
  readonly after: Record<string, unknown>;
}) {
  const allKeys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));

  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-2">
          <div className="text-xs font-mono text-text-muted mb-1">Before</div>
          <div className="text-xs font-mono text-text-muted mb-1">After</div>
          {allKeys.map(key => {
            const bVal = JSON.stringify(before[key] ?? null);
            const aVal = JSON.stringify(after[key] ?? null);
            const changed = bVal !== aVal;
            return (
              <div key={key} className="contents">
                <div className={cn(
                  'px-2 py-1 rounded text-xs font-mono border',
                  changed ? 'border-danger/30 bg-danger/5 text-danger' : 'border-border-subtle text-text-secondary',
                )}>
                  <span className="text-text-muted">{key}: </span>{bVal}
                </div>
                <div className={cn(
                  'px-2 py-1 rounded text-xs font-mono border',
                  changed ? 'border-success/30 bg-success/5 text-success' : 'border-border-subtle text-text-secondary',
                )}>
                  <span className="text-text-muted">{key}: </span>{aVal}
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function GraphDiffPanel({ diff }: { readonly diff: GraphDiff }) {
  const hasChanges =
    diff.addedNodes.length > 0 ||
    diff.removedNodes.length > 0 ||
    diff.addedEdges.length > 0 ||
    diff.removedEdges.length > 0 ||
    diff.modifiedNodes.length > 0;

  if (!hasChanges) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Graph Diff</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3 text-xs font-mono">
          {diff.addedNodes.length > 0 && (
            <div>
              <div className="text-success font-bold mb-1">+ Added Nodes</div>
              {diff.addedNodes.map(n => (
                <div key={n} className="text-success pl-2">{n}</div>
              ))}
            </div>
          )}
          {diff.removedNodes.length > 0 && (
            <div>
              <div className="text-danger font-bold mb-1">- Removed Nodes</div>
              {diff.removedNodes.map(n => (
                <div key={n} className="text-danger pl-2">{n}</div>
              ))}
            </div>
          )}
          {diff.addedEdges.length > 0 && (
            <div>
              <div className="text-success font-bold mb-1">+ Added Edges</div>
              {diff.addedEdges.map(e => (
                <div key={e} className="text-success pl-2">{e}</div>
              ))}
            </div>
          )}
          {diff.removedEdges.length > 0 && (
            <div>
              <div className="text-danger font-bold mb-1">- Removed Edges</div>
              {diff.removedEdges.map(e => (
                <div key={e} className="text-danger pl-2">{e}</div>
              ))}
            </div>
          )}
          {diff.modifiedNodes.length > 0 && (
            <div>
              <div className="text-warning font-bold mb-1">~ Modified Nodes</div>
              {diff.modifiedNodes.map(mn => (
                <div key={mn.id} className="pl-2 text-warning">
                  <div>{mn.id}</div>
                  {Object.entries(mn.changes).map(([k, v]) => (
                    <div key={k} className="pl-4 text-text-secondary">
                      {k}: {String(v)}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function EvidencePanel({ evidence }: { readonly evidence: readonly string[] }) {
  if (evidence.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Evidence</CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {evidence.map((e, i) => (
            <li key={i} className="flex gap-2 text-xs">
              <span className="text-accent font-mono shrink-0">[{i + 1}]</span>
              <span className="text-text-primary">{e}</span>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ConfidenceBar({ confidence }: { readonly confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color = pct >= 90 ? 'bg-success' : pct >= 70 ? 'bg-warning' : 'bg-danger';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-surface-raised rounded-full overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono font-bold text-text-primary">{pct}%</span>
    </div>
  );
}

function AttributionBlock({ attribution, label }: {
  readonly attribution: ActionAttribution;
  readonly label: string;
}) {
  return (
    <div className="text-xs border border-border-subtle rounded px-3 py-2 bg-surface-default">
      <div className="text-text-muted mb-1">{label}</div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-text-primary font-bold">{attribution.displayName}</span>
        <Badge>{attribution.role}</Badge>
      </div>
      <div className="text-text-secondary mt-0.5">{formatTimestamp(attribution.timestamp)}</div>
      {attribution.reason && (
        <div className="text-text-secondary mt-1 italic">"{attribution.reason}"</div>
      )}
    </div>
  );
}

function AuditTrailPanel({ entries }: { readonly entries: readonly AuditEntry[] }) {
  if (entries.length === 0) {
    return <div className="text-xs text-text-muted text-center py-4">No audit entries</div>;
  }

  return (
    <div className="space-y-3">
      {entries.map(entry => (
        <div key={entry.id} className="flex gap-3 text-xs border-l-2 border-border-default pl-3 py-1">
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono font-bold text-text-primary">{entry.actor.displayName}</span>
              <Badge variant={statusVariant[entry.newStatus]}>{entry.action}</Badge>
            </div>
            <div className="text-text-secondary mt-0.5">
              {formatTimestamp(entry.timestamp)}
            </div>
            <div className="text-text-secondary mt-0.5">
              <span className="text-text-muted">Status:</span>{' '}
              <Badge variant={statusVariant[entry.previousStatus]}>{entry.previousStatus}</Badge>
              {' \u2192 '}
              <Badge variant={statusVariant[entry.newStatus]}>{entry.newStatus}</Badge>
            </div>
            {entry.reason && (
              <div className="text-text-secondary mt-1 italic">"{entry.reason}"</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Action Modal ──────────────────────────────────────────────────────────

type ActionType = 'approve' | 'reject' | 'defer' | 'revert';

interface ActionModalState {
  open: boolean;
  actionType: ActionType;
  itemId: string;
  batchId: string;
}

const actionConfig: Record<ActionType, { label: string; newStatus: ReviewStatus; buttonVariant: 'primary' | 'danger' | 'secondary' }> = {
  approve: { label: 'Approve', newStatus: 'approved', buttonVariant: 'primary' },
  reject: { label: 'Reject', newStatus: 'rejected', buttonVariant: 'danger' },
  defer: { label: 'Defer', newStatus: 'deferred', buttonVariant: 'secondary' },
  revert: { label: 'Revert', newStatus: 'reverted', buttonVariant: 'danger' },
};

// ─── Main Page Component ───────────────────────────────────────────────────

export function ReviewPage() {
  const { user } = useAuth();
  const permissions = usePermissions();

  const [batches, setBatches] = useState<ReviewBatch[]>(() => [...getMockReviewBatches()] as ReviewBatch[]);
  const [auditTrail, setAuditTrail] = useState<AuditEntry[]>(() => [...getMockAuditTrail()] as AuditEntry[]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);

  const [actionModal, setActionModal] = useState<ActionModalState>({
    open: false,
    actionType: 'approve',
    itemId: '',
    batchId: '',
  });
  const [actionReason, setActionReason] = useState('');

  const selectedBatch = batches.find(b => b.id === selectedBatchId) ?? null;
  const selectedItem = selectedBatch?.items.find(i => i.id === selectedItemId) ?? null;
  const batchAuditEntries = useMemo(
    () => auditTrail.filter(a => a.batchId === selectedBatchId).sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
    [auditTrail, selectedBatchId],
  );

  const openActionModal = useCallback((actionType: ActionType, itemId: string, batchId: string) => {
    setActionModal({ open: true, actionType, itemId, batchId });
    setActionReason('');
  }, []);

  const closeActionModal = useCallback(() => {
    setActionModal(prev => ({ ...prev, open: false }));
    setActionReason('');
  }, []);

  const executeAction = useCallback(() => {
    if (!actionReason.trim()) return;

    const { actionType, itemId, batchId } = actionModal;
    const config = actionConfig[actionType];
    const now = new Date().toISOString();

    const attribution: ActionAttribution = {
      userId: user?.id ?? 'unknown',
      displayName: user?.displayName ?? 'Unknown User',
      email: user?.email ?? 'unknown@aether.internal',
      role: user?.role ?? 'shiki_observer',
      timestamp: now,
      environment: 'local-mocked',
      reason: actionReason,
      correlationId: `corr-${actionType}-${Date.now()}`,
    };

    // Update batch and item statuses
    setBatches(prev =>
      prev.map(batch => {
        if (batch.id !== batchId) return batch;
        const updatedItems = batch.items.map(item => {
          if (item.id !== itemId) return item;
          return {
            ...item,
            status: config.newStatus,
            resolution: {
              status: config.newStatus,
              resolvedBy: attribution,
              reason: actionReason,
            },
          } as ReviewItem;
        });
        // Update batch status if all items have same status
        const allSame = updatedItems.every(i => i.status === config.newStatus);
        return {
          ...batch,
          items: updatedItems,
          status: allSame ? config.newStatus : batch.status,
        } as ReviewBatch;
      }),
    );

    // Find the current item to get previous status
    const currentItem = batches
      .find(b => b.id === batchId)
      ?.items.find(i => i.id === itemId);

    // Add audit entry
    const newAudit: AuditEntry = {
      id: `audit-${Date.now()}`,
      action: actionType,
      timestamp: now,
      actor: attribution,
      itemId,
      batchId,
      previousStatus: currentItem?.status ?? 'pending',
      newStatus: config.newStatus,
      reason: actionReason,
    };

    setAuditTrail(prev => [newAudit, ...prev]);
    closeActionModal();
  }, [actionModal, actionReason, user, batches, closeActionModal]);

  return (
    <PageWrapper
      title="Review & Approval"
      subtitle="Review proposed mutations, approve or reject changes, and audit action history"
    >
      <div className="grid grid-cols-12 gap-4">
        {/* Left Panel: Batch List */}
        <div className="col-span-12 lg:col-span-4">
          <Card>
            <CardHeader>
              <CardTitle>Review Batches</CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea maxHeight="calc(100vh - 250px)">
                <div className="space-y-2">
                  {batches.map(batch => (
                    <button
                      key={batch.id}
                      onClick={() => {
                        setSelectedBatchId(batch.id);
                        setSelectedItemId(batch.items[0]?.id ?? null);
                      }}
                      className={cn(
                        'w-full text-left px-3 py-3 rounded border transition-colors',
                        selectedBatchId === batch.id
                          ? 'border-accent bg-accent/10'
                          : 'border-border-subtle bg-surface-default hover:border-accent/30',
                      )}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-mono font-bold text-text-primary truncate mr-2">
                          {batch.title}
                        </span>
                        <Badge variant={statusVariant[batch.status]}>{batch.status}</Badge>
                      </div>
                      <div className="text-xs text-text-secondary space-y-0.5">
                        <div>{batch.items.length} item{batch.items.length !== 1 ? 's' : ''}</div>
                        <div>By: {batch.submittedBy}</div>
                        <div>Controller: {batch.controller}</div>
                        <div>{formatRelativeTime(batch.createdAt)}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Right Panel: Batch Detail */}
        <div className="col-span-12 lg:col-span-8">
          {!selectedBatch ? (
            <Card>
              <CardContent>
                <EmptyState
                  title="No Batch Selected"
                  description="Select a review batch from the list to view its items and take action."
                />
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-4">
              {/* Batch Header */}
              <Card>
                <CardHeader>
                  <CardTitle>
                    <div className="flex items-center justify-between">
                      <span>{selectedBatch.title}</span>
                      <Badge variant={statusVariant[selectedBatch.status]}>{selectedBatch.status}</Badge>
                    </div>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-text-secondary mb-2">{selectedBatch.description}</p>
                  <div className="flex gap-4 text-xs text-text-muted">
                    <span>Submitted by: <span className="text-text-primary">{selectedBatch.submittedBy}</span></span>
                    <span>Controller: <span className="text-text-primary">{selectedBatch.controller}</span></span>
                    <span>Created: <span className="text-text-primary">{formatRelativeTime(selectedBatch.createdAt)}</span></span>
                  </div>
                </CardContent>
              </Card>

              {/* Item Tabs */}
              <Tabs
                defaultValue={selectedBatch.items[0]?.id ?? ''}
                onChange={(val: string) => setSelectedItemId(val)}
              >
                <TabsList>
                  {selectedBatch.items.map((item, idx) => (
                    <TabsTrigger key={item.id} value={item.id}>
                      Item {idx + 1}
                    </TabsTrigger>
                  ))}
                  <TabsTrigger value="__audit__">Audit Trail</TabsTrigger>
                </TabsList>

                {/* Item Detail Panels */}
                {selectedBatch.items.map(item => (
                  <TabsContent key={item.id} value={item.id}>
                    <ScrollArea maxHeight="calc(100vh - 400px)">
                      <div className="space-y-4">
                        {/* Item Header */}
                        <Card>
                          <CardHeader>
                            <CardTitle>
                              <div className="flex items-center justify-between">
                                <span>{item.title}</span>
                                <div className="flex items-center gap-2">
                                  <Badge variant={statusVariant[item.status]}>{item.status}</Badge>
                                </div>
                              </div>
                            </CardTitle>
                          </CardHeader>
                          <CardContent>
                            <p className="text-xs text-text-secondary mb-3">{item.description}</p>
                            <div className="flex flex-wrap gap-3 text-xs">
                              <div className="flex items-center gap-1">
                                <span className="text-text-muted">Mutation:</span>
                                <Badge variant={mutationClassLabels[item.mutationClass].variant}>
                                  {mutationClassLabels[item.mutationClass].label}
                                </Badge>
                              </div>
                              <div className="flex items-center gap-1">
                                <span className="text-text-muted">Severity:</span>
                                <SeverityBadge severity={item.severity} />
                              </div>
                              <div className="flex items-center gap-1">
                                <span className="text-text-muted">Reversible:</span>
                                <Badge variant={item.reversible ? 'success' : 'danger'}>
                                  {item.reversible ? 'Yes' : 'No'}
                                </Badge>
                              </div>
                            </div>
                          </CardContent>
                        </Card>

                        {/* Confidence */}
                        <Card>
                          <CardHeader>
                            <CardTitle>Confidence</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <ConfidenceBar confidence={item.confidence} />
                          </CardContent>
                        </Card>

                        {/* Rationale & Explanation Trace */}
                        <Card>
                          <CardHeader>
                            <CardTitle>Rationale & Explanation</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <div className="text-sm text-text-primary leading-relaxed bg-surface-raised rounded p-3 border border-border-subtle font-mono">
                              {item.rationale}
                            </div>
                          </CardContent>
                        </Card>

                        {/* Downstream Impact */}
                        <Card>
                          <CardHeader>
                            <CardTitle>Downstream Impact</CardTitle>
                          </CardHeader>
                          <CardContent>
                            <div className="text-xs text-text-primary bg-warning/5 border border-warning/20 rounded p-3">
                              {item.downstreamImpact}
                            </div>
                          </CardContent>
                        </Card>

                        {/* JSON Diff */}
                        <JsonDiffPanel label="Before / After Diff" before={item.before} after={item.after} />

                        {/* Graph Diff */}
                        {item.graphDiff && <GraphDiffPanel diff={item.graphDiff} />}

                        {/* Evidence */}
                        <EvidencePanel evidence={item.evidence} />

                        {/* Resolution Attribution */}
                        {item.resolution && (
                          <AttributionBlock attribution={item.resolution.resolvedBy} label="Resolved By" />
                        )}

                        <TerminalSeparator />

                        {/* Action Buttons */}
                        <Card>
                          <CardContent>
                            <div className="flex flex-wrap gap-2">
                              <PermissionGate requires="canApprove">
                                <Button
                                  variant="primary"
                                  size="sm"
                                  disabled={item.status === 'approved'}
                                  onClick={() => openActionModal('approve', item.id, selectedBatch.id)}
                                  className="bg-success text-text-inverse hover:bg-success/80"
                                >
                                  Approve
                                </Button>
                              </PermissionGate>

                              <PermissionGate requires="canApprove">
                                <Button
                                  variant="danger"
                                  size="sm"
                                  disabled={item.status === 'rejected'}
                                  onClick={() => openActionModal('reject', item.id, selectedBatch.id)}
                                >
                                  Reject
                                </Button>
                              </PermissionGate>

                              {permissions.role !== 'shiki_observer' && (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  disabled={item.status === 'deferred'}
                                  onClick={() => openActionModal('defer', item.id, selectedBatch.id)}
                                  className="border-warning/30 text-warning hover:bg-warning/10"
                                >
                                  Defer
                                </Button>
                              )}

                              <PermissionGate requires="canRevert">
                                {item.reversible && item.status === 'approved' && (
                                  <Button
                                    variant="secondary"
                                    size="sm"
                                    onClick={() => openActionModal('revert', item.id, selectedBatch.id)}
                                    className="border-accent/30 text-accent hover:bg-accent/10"
                                  >
                                    Revert
                                  </Button>
                                )}
                              </PermissionGate>
                            </div>
                          </CardContent>
                        </Card>
                      </div>
                    </ScrollArea>
                  </TabsContent>
                ))}

                {/* Audit Trail Tab */}
                <TabsContent value="__audit__">
                  <Card>
                    <CardHeader>
                      <CardTitle>Audit Trail</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <ScrollArea maxHeight="calc(100vh - 400px)">
                        <AuditTrailPanel entries={batchAuditEntries} />
                      </ScrollArea>
                    </CardContent>
                  </Card>
                </TabsContent>
              </Tabs>
            </div>
          )}
        </div>
      </div>

      {/* Action Confirmation Modal */}
      <Modal open={actionModal.open} onClose={closeActionModal}>
        <ModalHeader>
          <h2 className="text-lg font-mono font-bold text-text-primary">
            {actionConfig[actionModal.actionType].label} Confirmation
          </h2>
        </ModalHeader>
        <ModalBody>
          <div className="space-y-4">
            <p className="text-sm text-text-secondary">
              You are about to <strong className="text-text-primary">{actionModal.actionType}</strong> this review item.
              Please provide a reason for this action.
            </p>
            <div>
              <label htmlFor="action-reason" className="block text-xs text-text-secondary mb-1 font-mono">
                Reason (required)
              </label>
              <textarea
                id="action-reason"
                value={actionReason}
                onChange={e => setActionReason(e.target.value)}
                placeholder="Enter your reason for this action..."
                rows={3}
                className="w-full bg-surface-default border border-border-default rounded px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-border-focus font-mono resize-none"
              />
            </div>
            <div className="text-xs text-text-muted">
              Action by: <span className="text-text-primary">{user?.displayName ?? 'Unknown'}</span> ({user?.role ?? 'unknown'})
            </div>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" size="sm" onClick={closeActionModal}>
            Cancel
          </Button>
          <Button
            variant={actionConfig[actionModal.actionType].buttonVariant}
            size="sm"
            disabled={!actionReason.trim()}
            onClick={executeAction}
          >
            {actionConfig[actionModal.actionType].label}
          </Button>
        </ModalFooter>
      </Modal>
    </PageWrapper>
  );
}
