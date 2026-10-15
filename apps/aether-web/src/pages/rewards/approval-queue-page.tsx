import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  EmptyState, ErrorState, Input, LoadingState,
} from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { useRewardsApprovalQueue } from '@aether-app/features/rewards/use-rewards';

// ── Helpers ───────────────────────────────────────────────────────────────────

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtScore(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return Number(v).toFixed(3);
}

function fmtPct(v: unknown): string {
  if (v === null || v === undefined) return '—';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

export function rewardActionPostcondition(
  result: unknown,
  expectedActionId: string,
  expectedStatus: 'ready' | 'rejected',
): string | null {
  if (!result || typeof result !== 'object') return 'The server did not return the updated reward action.';
  const updated = result as Record<string, unknown>;
  const returnedId = updated.id ?? updated.action_id;
  if (String(returnedId ?? '') !== expectedActionId) return 'The updated reward action has a different action ID.';
  if (updated.status !== expectedStatus) {
    return `The reward action is ${fmt(updated.status, 'in an unknown state')}; expected ${expectedStatus}.`;
  }
  return null;
}

// ── Per-action card ───────────────────────────────────────────────────────────

interface ActionItemProps {
  readonly action: Record<string, unknown>;
  readonly onActioned: () => void;
}

function ActionItem({ action, onActioned }: ActionItemProps) {
  const [confirming, setConfirming] = useState<'approve' | 'reject' | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<'approved' | 'rejected' | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const actionId = fmt(action.id ?? action.action_id, '');
  const displayActionId = actionId || 'ID unavailable';
  const decisionId = fmt(action.decision_id, '');
  const campaignName = fmt(action.campaign_name ?? action.campaign_id);
  const ruleName = fmt(action.rule_name ?? action.rule_id, '');
  const rewardAmount = action.reward_amount !== undefined ? String(action.reward_amount) : '—';
  const rewardUnit = fmt(action.reward_unit ?? action.unit, '');
  const walletAddress = fmt(action.wallet_address ?? action.user_address, '');
  const attributionWeight = action.attribution_weight ?? action.weight;
  const fraudScore = action.fraud_score ?? action.risk_score;
  const rail = fmt(action.rail);

  async function handleApprove() {
    if (!actionId) {
      setErrorMsg('Approval blocked: this row has no tenant-scoped action ID.');
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    try {
      const updated = await api.rewards.approveAction(actionId);
      const failure = rewardActionPostcondition(updated, actionId, 'ready');
      if (failure) throw new Error(failure);
      setDone('approved');
      setConfirming(null);
      setTimeout(onActioned, 800);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Approve failed');
    } finally {
      setBusy(false);
    }
  }

  async function handleReject() {
    if (!rejectReason.trim()) return;
    if (!actionId) {
      setErrorMsg('Rejection blocked: this row has no tenant-scoped action ID.');
      return;
    }
    setBusy(true);
    setErrorMsg(null);
    try {
      const updated = await api.rewards.rejectAction(actionId, rejectReason.trim());
      const failure = rewardActionPostcondition(updated, actionId, 'rejected');
      if (failure) throw new Error(failure);
      setDone('rejected');
      setConfirming(null);
      setTimeout(onActioned, 800);
    } catch (e) {
      setErrorMsg(e instanceof Error ? e.message : 'Reject failed');
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="border border-border-default rounded-lg px-4 py-3 flex items-center gap-3 bg-surface-raised opacity-70">
        <Badge variant={done === 'approved' ? 'success' : 'danger'}>{done}</Badge>
        <span className="text-sm text-text-muted">
          Action payload {displayActionId} {done === 'approved' ? 'confirmed ready for tenant rail delivery' : 'confirmed rejected'}.
        </span>
      </div>
    );
  }

  return (
    <div className="border border-border-default rounded-lg overflow-hidden">
      {/* Main info row */}
      <div className="px-4 py-3 flex items-start gap-4">
        <div className="flex-1 min-w-0 space-y-1">
          {/* Campaign + rule */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-text-primary text-sm">{campaignName}</span>
            {ruleName && <span className="text-xs text-text-muted">· {ruleName}</span>}
          </div>

          {/* Reward info */}
          <div className="flex items-center gap-3 flex-wrap text-xs">
            <span className="text-text-secondary">
              Reward: <span className="font-semibold text-text-primary">{rewardAmount} {rewardUnit}</span>
            </span>
            <Badge variant="default" size="sm">{rail}</Badge>
            {walletAddress && (
              <code className="text-text-muted font-mono">
                {walletAddress.slice(0, 8)}…{walletAddress.slice(-6)}
              </code>
            )}
          </div>

          {/* Risk signals */}
          <div className="flex items-center gap-4 text-xs text-text-muted">
            {attributionWeight !== undefined && (
              <span>Attribution weight: <span className="text-text-secondary">{fmtPct(attributionWeight)}</span></span>
            )}
            {fraudScore !== undefined && (() => {
              const score = Number(fraudScore);
              const color = score > 0.7 ? 'text-danger' : score > 0.4 ? 'text-warning' : 'text-success';
              return (
                <span>
                  Fraud score: <span className={`font-mono ${color}`}>{fmtScore(fraudScore)}</span>
                </span>
              );
            })()}
            {decisionId && (
              <span className="font-mono">Decision: {decisionId.slice(0, 12)}…</span>
            )}
            {!actionId && <span className="text-danger">Action ID unavailable; operations are blocked.</span>}
          </div>
        </div>

        {/* Action buttons */}
        {!confirming && (
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              variant="primary"
              onClick={() => { setConfirming('approve'); setErrorMsg(null); }}
              disabled={busy || !actionId}
              className="bg-success text-white hover:bg-success/90"
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setConfirming('reject'); setErrorMsg(null); }}
              disabled={busy || !actionId}
              className="border-danger text-danger hover:bg-danger/10"
            >
              Reject
            </Button>
          </div>
        )}
      </div>

      {/* Confirm approve */}
      {confirming === 'approve' && (
        <div className="border-t border-border-default px-4 py-3 bg-surface-raised flex items-center justify-between gap-4">
          <p className="text-sm text-text-secondary">
            Approve to make the action payload available for delivery via tenant rail.
            This does not execute the reward — your rail system will handle delivery.
          </p>
          <div className="flex items-center gap-2 shrink-0">
            <Button size="sm" variant="secondary" onClick={() => setConfirming(null)} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => { void handleApprove(); }}
              disabled={busy}
              className="bg-success text-white hover:bg-success/90"
            >
              {busy ? 'Approving…' : 'Confirm Approve'}
            </Button>
          </div>
        </div>
      )}

      {/* Confirm reject */}
      {confirming === 'reject' && (
        <div className="border-t border-border-default px-4 py-3 bg-surface-raised space-y-3">
          <Input
            label="Rejection reason (required)"
            value={rejectReason}
            onChange={e => setRejectReason(e.target.value)}
            placeholder="e.g. Fraud risk exceeds threshold, campaign budget exhausted…"
          />
          <div className="flex items-center justify-end gap-2">
            <Button size="sm" variant="secondary" onClick={() => { setConfirming(null); setRejectReason(''); }} disabled={busy}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => { void handleReject(); }}
              disabled={busy || !rejectReason.trim()}
              className="border-danger text-danger hover:bg-danger/10"
            >
              {busy ? 'Rejecting…' : 'Confirm Reject'}
            </Button>
          </div>
        </div>
      )}

      {/* Error */}
      {errorMsg && (
        <div className="border-t border-border-default px-4 py-2 bg-surface-raised">
          <p className="text-xs text-danger">{errorMsg}</p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function RewardApprovalQueuePage() {
  const { data, isLoading, error, refetch } = useRewardsApprovalQueue();
  const d = asRecord(data);
  const actions = asList(d.actions ?? d.items ?? data).map(asRecord);

  return (
    <div className="p-8 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-semibold text-text-primary">Approval Queue</h1>
            {!isLoading && !error && (
              <Badge variant={actions.length > 0 ? 'warning' : 'default'}>
                {actions.length} pending
              </Badge>
            )}
          </div>
          <p className="text-sm text-text-secondary mt-0.5">
            Review action payloads for <code className="text-xs">manual_approval</code> rail.
            Approve to release to tenant delivery. Aether does not execute rewards.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => { void refetch?.(); }}>
          Refresh
        </Button>
      </div>

      {/* Content */}
      <Card>
        <CardHeader>
          <CardTitle>Pending Actions</CardTitle>
        </CardHeader>
        <CardContent>
          {error ? (
            <ErrorState
              title="Failed to load approval queue"
              message={String(error)}
            />
          ) : isLoading ? (
            <LoadingState lines={6} />
          ) : actions.length === 0 ? (
            <EmptyState
              title="No actions pending approval"
              description="When reward eligibility is verified for manual_approval rail, action payloads will appear here for review."
            />
          ) : (
            <div className="space-y-3">
              {actions.map((action, i) => (
                <ActionItem
                  key={fmt(action.id ?? action.action_id ?? i)}
                  action={action}
                  onActioned={() => { void refetch?.(); }}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* No-custody notice */}
      <p className="text-xs text-text-muted border border-border-default rounded-md px-3 py-2 bg-surface-raised">
        <strong className="text-text-secondary">No-custody platform:</strong> Approving an action makes the payload available for delivery via your configured rail.
        Aether does not hold campaign budgets or execute reward payments. Tenant executes rewards using your own systems.
      </p>
    </div>
  );
}
