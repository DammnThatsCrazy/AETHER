import { useState } from 'react';
import type { ReactNode } from 'react';
import { Modal, ModalBody, ModalHeader, useQuery } from '@aether/ui';
import { ChoiceChip, Eyebrow, InlineNotice, Spinner, TonePill } from '@aether-app/components/ae-ui';
import { useRecommendationInvestigation, useRecommendations, usePlaybooks } from '@aether-app/features/intelligence';
import { hasDecisionApprovalPermission } from '@aether-app/features/intelligence/decision-permissions';
import { useAuth } from '@aether-app/features/auth';
import { api } from '@aether-app/lib/api/endpoints';

const FAMILIES = [
  'all', 'retention', 'expansion', 'fraud_review', 'attribution_optimization',
  'journey_optimization', 'agent_governance', 'rewards_optimization', 'operational_failure',
] as const;

function asItems(data: unknown): unknown[] {
  if (data && typeof data === 'object' && 'items' in data) {
    const items = (data as { items?: unknown }).items;
    return Array.isArray(items) ? items : [];
  }
  return [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function pct(value: unknown) {
  return value == null ? '—' : `${Math.round(Number(value) * 100)}%`;
}

export function DecisionIntelligencePanel() {
  const { user } = useAuth();
  const [family, setFamily] = useState<(typeof FAMILIES)[number]>('all');
  const [investigationId, setInvestigationId] = useState('');
  const [busyRecommendation, setBusyRecommendation] = useState('');
  const [actionMessage, setActionMessage] = useState<Record<string, string>>({});
  const recommendations = useRecommendations(family === 'all' ? undefined : { family });
  const playbooks = usePlaybooks();
  const approvalPermissions = useQuery<unknown>({
    key: `security:decision-permissions:${user?.id ?? 'anonymous'}`,
    fetcher: () => api.security.myPermissions(),
    staleTime: 60_000,
    enabled: Boolean(user?.id),
  });
  const approvalPermissionResolved = approvalPermissions.data !== null && !approvalPermissions.error;
  const canApproveDecisions = approvalPermissionResolved && hasDecisionApprovalPermission(approvalPermissions.data);
  const recItems = asItems(recommendations.data).slice(0, 6) as Array<Record<string, unknown>>;
  const playbookItems = asItems(playbooks.data).slice(0, 3) as Array<Record<string, unknown>>;

  return (
    <div className="flex min-w-0 flex-col gap-[18px]">
      <GlassCard
        title="Decision intelligence feed"
        sub="Ranked graph-native recommendations with evidence, confidence, and approval gates."
        aside={<TonePill tone="blue">OODA enabled</TonePill>}
        testId="decision-intelligence-feed"
      >
        {recommendations.isLoading && <ReadLoading label="Loading recommendations" />}
        {recommendations.error && <ReadUnavailable message="Recommendations unavailable" onRetry={recommendations.refetch} />}
        {!recommendations.isLoading && !recommendations.error && <>
        <div className="ae-scroll-none -mx-1 flex gap-1.5 overflow-x-auto px-1 pb-0.5" role="group" aria-label="Recommendation family">
          {FAMILIES.map((item) => (
            <ChoiceChip key={item} size="sm" selected={family === item} onClick={() => setFamily(item)}>
              <span className="whitespace-nowrap">{item.replace(/_/g, ' ')}</span>
            </ChoiceChip>
          ))}
        </div>
        <div className="flex flex-col gap-2.5">
          {recItems.length === 0 ? (
            <p className="text-[13px]" style={MUTE} data-state="empty">
              No active recommendations for this family yet.
            </p>
          ) : recItems.map((rec) => {
            const action = asRecord(rec.recommended_action);
            const confidence = asRecord(rec.confidence);
            const recommendationId = text(rec.recommendation_id, '');
            const canApprove = Boolean(recommendationId && text(action.action_key, ''))
              && !['suppressed', 'decided'].includes(text(rec.status, ''))
              && canApproveDecisions;
            const approve = async () => {
              if (!user?.id || !canApprove) return;
              setBusyRecommendation(recommendationId);
              setActionMessage((current) => ({ ...current, [recommendationId]: 'Recording approval…' }));
              try {
                const decision = asRecord(await api.intelligence.recordDecision(recommendationId, {
                  actor_id: user.id,
                  selected_action_key: text(action.action_key, ''),
                  decision_status: 'approved',
                }));
                const decisionId = text(decision.decision_id, '');
                if (!decisionId) throw new Error('Approval did not return a durable decision ID.');
                await api.intelligence.logAction({ decision_id: decisionId, action_type: text(action.action_type, 'manual'), status: 'planned', actor_type: 'human' });
                setActionMessage((current) => ({ ...current, [recommendationId]: 'Approved and planned. Configure a tenant target before dispatch.' }));
              } catch (error) {
                setActionMessage((current) => ({ ...current, [recommendationId]: error instanceof Error ? error.message : 'Approval unavailable.' }));
              } finally {
                setBusyRecommendation('');
              }
            };
            return (
              <div key={recommendationId} className="flex flex-col gap-2.5 rounded-[14px] px-3.5 py-3" style={BOX}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-col gap-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-medium">{text(action.label, 'Recommended action')}</span>
                      <TonePill tone="mute">{text(rec.recommendation_type).replace(/_/g, ' ')}</TonePill>
                    </div>
                    <span className="text-[12px] leading-snug" style={MUTE}>{text(rec.expected_outcome)}</span>
                  </div>
                  <TonePill tone="sage">{pct(confidence.overall)}</TonePill>
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]" style={MUTE}>
                  <span>Approval: {text(rec.required_approval_level)}</span>
                  <span>Value: {text(rec.expected_value)}</span>
                  <span>Freshness: {text(asRecord(rec.data_freshness).status)}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className="ae-btn-secondary ae-focus px-3.5 py-1.5 text-[12px]" onClick={() => setInvestigationId(recommendationId)}>Open investigation</button>
                  <button
                    type="button"
                    className="ae-btn-primary ae-focus px-3.5 py-1.5 text-[12px]"
                    disabled={!canApprove || busyRecommendation === recommendationId}
                    onClick={() => void approve()}
                  >
                    {busyRecommendation === recommendationId ? 'Approving…' : 'Approve & plan action'}
                  </button>
                </div>
                {!approvalPermissions.isLoading && !canApproveDecisions && (
                  <span className="text-[12px]" style={FAINT}>
                    Approval controls are read-only until the tenant grants the decisions:approve permission.
                  </span>
                )}
                {actionMessage[recommendationId] && <span className="text-[12px]" style={MUTE}>{actionMessage[recommendationId]}</span>}
              </div>
            );
          })}
        </div>
        </>}
      </GlassCard>

      <GlassCard title="Playbooks" testId="decision-playbooks">
        {playbooks.isLoading ? <ReadLoading label="Loading playbooks" /> : playbooks.error ? <ReadUnavailable message="Playbooks unavailable" onRetry={playbooks.refetch} /> : playbookItems.length === 0 ? <p className="text-[13px]" style={MUTE} data-state="empty">No playbooks configured.</p> : (
          <div className="flex flex-col">
            {playbookItems.map((pb) => (
              <div key={text(pb.playbook_id)} className="flex items-center justify-between gap-3 border-t py-2 text-[13px]" style={{ borderColor: 'var(--ae-edge)' }}>
                <span className="truncate">{text(pb.name)}</span>
                <TonePill tone={pb.enabled ? 'sage' : 'mute'}>{pb.enabled ? 'Enabled' : 'Disabled'}</TonePill>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
      <InvestigationModal recommendationId={investigationId} onClose={() => setInvestigationId('')} />
    </div>
  );
}

const MUTE = { color: 'var(--ae-mute)' } as const;
const FAINT = { color: 'var(--ae-faint)' } as const;
const BOX = { background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' } as const;

function GlassCard({ title, sub, aside, testId, children }: { readonly title: string; readonly sub?: string; readonly aside?: ReactNode; readonly testId?: string; readonly children: ReactNode }) {
  return (
    <section className="ae-card flex min-w-0 flex-col gap-3 rounded-[20px] px-5 py-[18px]" data-testid={testId}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Eyebrow>{title}</Eyebrow>
          {sub && <span className="text-[12px] leading-snug" style={MUTE}>{sub}</span>}
        </div>
        {aside ? <span className="flex-none">{aside}</span> : null}
      </div>
      {children}
    </section>
  );
}

function ReadLoading({ label }: { readonly label: string }) {
  return (
    <div className="flex items-center gap-2.5 py-3 text-[13px]" style={MUTE} role="status">
      <Spinner size={16} />
      {label}
    </div>
  );
}

function ReadUnavailable({ message, onRetry }: { readonly message: string; readonly onRetry: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2">
      <InlineNotice tone="amber">{message}</InlineNotice>
      <button type="button" onClick={onRetry} className="ae-btn-secondary ae-focus px-3.5 py-1.5 text-[12px]">Retry</button>
    </div>
  );
}

function InvestigationModal({ recommendationId, onClose }: { readonly recommendationId: string; readonly onClose: () => void }) {
  const investigation = useRecommendationInvestigation(recommendationId);
  const data = asRecord(investigation.data);
  const recommendation = asRecord(data.recommendation);
  const confidence = asRecord(data.confidence_breakdown);
  const evidence = asItems(data.evidence) as Array<Record<string, unknown>>;
  const actions = asItems(data.candidate_actions) as Array<Record<string, unknown>>;
  const decisions = asItems(data.decision_history);
  const outcomes = asItems(data.outcome_history);
  const governance = Array.isArray(data.governance_flags) ? data.governance_flags : [];

  return (
    <Modal open={!!recommendationId} onClose={onClose}>
      <ModalHeader><h2 className="text-sm font-medium text-text-primary">Recommendation investigation</h2></ModalHeader>
      <ModalBody className="max-h-[75vh] space-y-4 overflow-y-auto">
        {investigation.isLoading ? <p className="text-sm text-text-secondary">Loading investigation…</p> : null}
        {investigation.error ? <p className="text-sm text-danger">Investigation unavailable.</p> : null}
        <div className="rounded-lg border border-border-subtle p-3">
          <div className="flex flex-wrap items-center gap-2">
            <TonePill tone="mute">{text(recommendation.recommendation_type).replace(/_/g, ' ')}</TonePill>
            <TonePill tone="sage">Confidence {pct(confidence.overall)}</TonePill>
            <TonePill tone="blue">Value {text(recommendation.expected_value)}</TonePill>
          </div>
          <p className="mt-2 text-sm text-text-primary">{text(recommendation.expected_outcome)}</p>
          <p className="mt-1 text-xs text-text-secondary">Risk: {text(recommendation.downside_risk)}</p>
        </div>
        <InvestigationSection title="Evidence" items={evidence.map((item) => `${text(item.source_type)} · ${text(item.summary)}`)} />
        <InvestigationSection title="Candidate actions" items={actions.map((item) => `${text(item.label)} · approval ${text(item.requires_approval_level)}`)} />
        <InvestigationSection title="Governance flags" items={governance.map(String)} />
        <InvestigationSection title="Decision history" items={decisions.map((item) => text(asRecord(item).decision_status))} />
        <InvestigationSection title="Outcome history" items={outcomes.map((item) => `${text(asRecord(item).label)} · ${text(asRecord(item).value)}`)} />
      </ModalBody>
    </Modal>
  );
}

function InvestigationSection({ title, items }: { readonly title: string; readonly items: string[] }) {
  return (
    <div>
      <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">{title}</h3>
      {items.length === 0 ? <p className="mt-2 text-xs text-text-muted">No records yet.</p> : (
        <ul className="mt-2 space-y-1">
          {items.map((item, index) => <li key={`${title}-${index}`} className="rounded border border-border-subtle p-2 text-xs text-text-secondary">{item}</li>)}
        </ul>
      )}
    </div>
  );
}
