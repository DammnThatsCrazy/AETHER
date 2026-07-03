import { useState } from 'react';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, ErrorState, LoadingState, Modal,
  ModalBody, ModalFooter, ModalHeader, useToast,
} from '@aether/ui';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useFraudDecisions,
  useReviewFraudDecision,
  useSuppressFraudDecision,
} from '@kyber/features/fraud/use-fraud';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function riskTierVariant(tier: unknown): 'default' | 'warning' | 'danger' {
  const s = String(tier ?? '').toLowerCase();
  if (s === 'critical') return 'danger';
  if (s === 'high' || s === 'elevated') return 'warning';
  return 'default';
}

function reviewStateVariant(state: unknown): 'default' | 'warning' | 'success' | 'danger' {
  const s = String(state ?? '').toLowerCase();
  if (s === 'confirmed_fraud') return 'danger';
  if (s === 'suppressed') return 'success';
  if (s === 'dispute') return 'warning';
  return 'default';
}

const RISK_TIERS = ['', 'critical', 'high', 'elevated', 'low'];
const DECISIONS = ['', 'block', 'flag', 'monitor', 'clear', 'suppress'];
const REVIEW_STATES = ['', 'pending', 'confirmed_fraud', 'dispute', 'review_clear', 'suppressed'];
const REVIEW_STATE_OPTIONS = ['confirmed_fraud', 'dispute', 'review_clear'];

type DecisionRow = Record<string, unknown>;

export function FraudDecisionsPage() {
  const { toast } = useToast();

  const [riskTierFilter, setRiskTierFilter] = useState('');
  const [decisionFilter, setDecisionFilter] = useState('');
  const [reviewStateFilter, setReviewStateFilter] = useState('');

  const [reviewTarget, setReviewTarget] = useState<DecisionRow | null>(null);
  const [reviewState, setReviewState] = useState('confirmed_fraud');
  const [suppressTarget, setSuppressTarget] = useState<DecisionRow | null>(null);
  const [suppressReason, setSuppressReason] = useState('');

  // Build params without explicit undefined values (exactOptionalPropertyTypes).
  const queryParams: Parameters<typeof useFraudDecisions>[0] = { limit: 100 };
  if (riskTierFilter) queryParams.risk_tier = riskTierFilter;
  if (decisionFilter) queryParams.decision = decisionFilter;
  if (reviewStateFilter) queryParams.review_state = reviewStateFilter;

  const { data, isLoading, error } = useFraudDecisions(queryParams);
  const rows: DecisionRow[] = Array.isArray(asRec(data).decisions)
    ? (asRec(data).decisions as DecisionRow[])
    : [];

  const reviewMutation = useReviewFraudDecision();
  const suppressMutation = useSuppressFraudDecision();

  async function submitReview() {
    if (!reviewTarget) return;
    try {
      await reviewMutation.mutate({
        id: String(reviewTarget.decision_id ?? ''),
        review_state: reviewState,
        reviewed_by: 'kyber-operator',
      });
      toast.success('Review saved');
      setReviewTarget(null);
    } catch {
      toast.error('Review failed');
    }
  }

  async function submitSuppress() {
    if (!suppressTarget || !suppressReason.trim()) return;
    try {
      await suppressMutation.mutate({
        id: String(suppressTarget.decision_id ?? ''),
        reviewed_by: 'kyber-operator',
        suppression_reason: suppressReason.trim(),
      });
      toast.success('Decision suppressed');
      setSuppressTarget(null);
      setSuppressReason('');
    } catch {
      toast.error('Suppress failed');
    }
  }

  return (
    <PermissionGate>
      <div className="flex flex-col gap-4 p-4">
        <header>
          <h1 className="text-xl font-semibold text-text-primary">Fraud Decisions</h1>
          <p className="text-sm text-text-muted mt-0.5">
            Durable, versioned fraud decisions. Review and suppress from here.
          </p>
        </header>

        {/* Filters */}
        <Card>
          <CardContent className="pt-4">
            <div className="flex gap-3 flex-wrap items-end">
              <label className="flex flex-col gap-1 text-xs text-text-muted">
                Risk tier
                <select
                  value={riskTierFilter}
                  onChange={e => setRiskTierFilter(e.target.value)}
                  className="border border-border-default rounded px-2 py-1.5 text-sm bg-surface-raised text-text-primary"
                >
                  {RISK_TIERS.map(t => <option key={t} value={t}>{t || 'All'}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-text-muted">
                Decision
                <select
                  value={decisionFilter}
                  onChange={e => setDecisionFilter(e.target.value)}
                  className="border border-border-default rounded px-2 py-1.5 text-sm bg-surface-raised text-text-primary"
                >
                  {DECISIONS.map(d => <option key={d} value={d}>{d || 'All'}</option>)}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-text-muted">
                Review state
                <select
                  value={reviewStateFilter}
                  onChange={e => setReviewStateFilter(e.target.value)}
                  className="border border-border-default rounded px-2 py-1.5 text-sm bg-surface-raised text-text-primary"
                >
                  {REVIEW_STATES.map(s => <option key={s} value={s}>{s || 'All'}</option>)}
                </select>
              </label>
            </div>
          </CardContent>
        </Card>

        {/* Decision table */}
        <Card>
          <CardHeader>
            <CardTitle>Decisions ({rows.length})</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading && <LoadingState lines={5} />}
            {error && <ErrorState title="Failed to load decisions" message={String(error)} />}
            {!isLoading && !error && rows.length === 0 && (
              <EmptyState title="No decisions" description="No fraud decisions match the current filters." />
            )}
            {!isLoading && rows.length > 0 && (
              <DataTable
                data={rows}
                keyExtractor={r => String(r.decision_id ?? Math.random())}
                columns={[
                  {
                    key: 'tier',
                    header: 'Risk tier',
                    render: (r: DecisionRow) => (
                      <Badge variant={riskTierVariant(r.risk_tier)}>
                        {fmt(r.risk_tier)}
                      </Badge>
                    ),
                  },
                  {
                    key: 'score',
                    header: 'Score',
                    render: (r: DecisionRow) => (
                      <span className="font-mono text-xs">
                        {r.risk_score != null ? Number(r.risk_score).toFixed(3) : '—'}
                      </span>
                    ),
                  },
                  {
                    key: 'decision',
                    header: 'Decision',
                    render: (r: DecisionRow) => <span className="text-xs">{fmt(r.decision)}</span>,
                  },
                  {
                    key: 'review',
                    header: 'Review state',
                    render: (r: DecisionRow) => (
                      <Badge variant={reviewStateVariant(r.review_state)}>
                        {fmt(r.review_state, 'pending')}
                      </Badge>
                    ),
                  },
                  {
                    key: 'entity',
                    header: 'Entity',
                    render: (r: DecisionRow) => <span className="font-mono text-xs">{fmt(r.entity_id)}</span>,
                  },
                  {
                    key: 'evaluated',
                    header: 'Evaluated',
                    render: (r: DecisionRow) =>
                      r.evaluated_at ? new Date(String(r.evaluated_at)).toLocaleString() : '—',
                  },
                  {
                    key: 'actions',
                    header: '',
                    render: (r: DecisionRow) => (
                      <PermissionGate>
                        <div className="flex gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => { setReviewTarget(r); setReviewState('confirmed_fraud'); }}
                          >
                            Review
                          </Button>
                          {r.review_state !== 'suppressed' && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => { setSuppressTarget(r); setSuppressReason(''); }}
                            >
                              Suppress
                            </Button>
                          )}
                        </div>
                      </PermissionGate>
                    ),
                  },
                ]}
              />
            )}
          </CardContent>
        </Card>

        {/* Review modal */}
        {reviewTarget && (
          <Modal open onClose={() => setReviewTarget(null)}>
            <ModalHeader>Review Decision</ModalHeader>
            <ModalBody>
              <p className="text-sm text-text-muted mb-3">
                Entity: <code className="font-mono">{fmt(reviewTarget.entity_id)}</code><br />
                Score:{' '}
                <strong>
                  {reviewTarget.risk_score != null ? Number(reviewTarget.risk_score).toFixed(3) : '—'}
                </strong>
                {' / Tier: '}
                <strong>{fmt(reviewTarget.risk_tier)}</strong>
              </p>
              <label className="flex flex-col gap-1 text-sm">
                Review state
                <select
                  value={reviewState}
                  onChange={e => setReviewState(e.target.value)}
                  className="border border-border-default rounded px-2 py-1.5 bg-surface-raised text-text-primary"
                >
                  {REVIEW_STATE_OPTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </label>
            </ModalBody>
            <ModalFooter>
              <Button variant="ghost" size="sm" onClick={() => setReviewTarget(null)}>
                Cancel
              </Button>
              <Button size="sm" onClick={submitReview} disabled={reviewMutation.isLoading}>
                {reviewMutation.isLoading ? 'Saving…' : 'Save review'}
              </Button>
            </ModalFooter>
          </Modal>
        )}

        {/* Suppress modal */}
        {suppressTarget && (
          <Modal open onClose={() => setSuppressTarget(null)}>
            <ModalHeader>Suppress Decision</ModalHeader>
            <ModalBody>
              <p className="text-sm text-text-muted mb-3">
                This will void the decision and mark it suppressed. Provide a reason for the audit trail.
              </p>
              <label className="flex flex-col gap-1 text-sm text-text-primary">
                Suppression reason
                <input
                  value={suppressReason}
                  onChange={e => setSuppressReason(e.target.value)}
                  placeholder="e.g. false positive — verified by analyst"
                  className="border border-border-default rounded px-2 py-1.5 bg-surface-raised text-text-primary"
                />
              </label>
            </ModalBody>
            <ModalFooter>
              <Button variant="ghost" size="sm" onClick={() => setSuppressTarget(null)}>
                Cancel
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={submitSuppress}
                disabled={!suppressReason.trim() || suppressMutation.isLoading}
              >
                {suppressMutation.isLoading ? 'Suppressing…' : 'Suppress'}
              </Button>
            </ModalFooter>
          </Modal>
        )}
      </div>
    </PermissionGate>
  );
}
