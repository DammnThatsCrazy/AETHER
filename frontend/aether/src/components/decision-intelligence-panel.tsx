import { useState } from 'react';
import { Card, CardHeader, CardContent, Badge, Button, Modal, ModalBody, ModalHeader } from '@aether/ui';
import { useRecommendationInvestigation, useRecommendations, usePlaybooks } from '@aether-app/features/intelligence';

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
  return `${Math.round(Number(value ?? 0) * 100)}%`;
}

export function DecisionIntelligencePanel() {
  const [family, setFamily] = useState<(typeof FAMILIES)[number]>('all');
  const [investigationId, setInvestigationId] = useState('');
  const recommendations = useRecommendations(family === 'all' ? undefined : { family });
  const playbooks = usePlaybooks();
  const recItems = asItems(recommendations.data).slice(0, 6) as Array<Record<string, unknown>>;
  const playbookItems = asItems(playbooks.data).slice(0, 3) as Array<Record<string, unknown>>;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-text-primary font-medium">Decision intelligence feed</h2>
              <p className="text-xs text-text-secondary mt-1">Ranked graph-native recommendations with evidence, confidence, and approval gates.</p>
            </div>
            <Badge variant="info">OODA enabled</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="mb-4 flex flex-wrap gap-2">
            {FAMILIES.map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => setFamily(item)}
                className={`rounded-full border px-3 py-1 text-xs ${family === item ? 'border-accent bg-accent/10 text-accent' : 'border-border-subtle text-text-secondary'}`}
              >
                {item.replace(/_/g, ' ')}
              </button>
            ))}
          </div>
          <div className="space-y-3">
            {recItems.length === 0 ? (
              <div className="rounded-lg border border-border-subtle p-4 text-sm text-text-secondary">
                No active recommendations for this family yet.
              </div>
            ) : recItems.map((rec) => {
              const action = asRecord(rec.recommended_action);
              const confidence = asRecord(rec.confidence);
              return (
                <div key={text(rec.recommendation_id)} className="rounded-lg border border-border-subtle p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium text-text-primary">{text(action.label, 'Recommended action')}</span>
                        <Badge variant="default">{text(rec.recommendation_type).replace(/_/g, ' ')}</Badge>
                      </div>
                      <div className="text-xs text-text-secondary mt-1">{text(rec.expected_outcome)}</div>
                    </div>
                    <Badge variant="success">{pct(confidence.overall)}</Badge>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2 text-xs text-text-muted">
                    <span>Approval: {text(rec.required_approval_level)}</span>
                    <span>Value: {text(rec.expected_value)}</span>
                    <span>Freshness: {text(asRecord(rec.data_freshness).status)}</span>
                  </div>
                  <Button className="mt-3" size="sm" variant="secondary" onClick={() => setInvestigationId(text(rec.recommendation_id, ''))}>
                    Open investigation
                  </Button>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><h2 className="text-text-primary font-medium">Playbooks</h2></CardHeader>
        <CardContent>
          {playbookItems.length === 0 ? <p className="text-sm text-text-secondary">No playbooks configured.</p> : playbookItems.map((pb) => (
            <div key={text(pb.playbook_id)} className="flex items-center justify-between border-b border-border-subtle py-2 last:border-b-0">
              <span className="text-sm text-text-primary">{text(pb.name)}</span>
              <Badge variant={pb.enabled ? 'success' : 'default'}>{pb.enabled ? 'Enabled' : 'Disabled'}</Badge>
            </div>
          ))}
        </CardContent>
      </Card>
      <InvestigationModal recommendationId={investigationId} onClose={() => setInvestigationId('')} />
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
            <Badge variant="default">{text(recommendation.recommendation_type).replace(/_/g, ' ')}</Badge>
            <Badge variant="success">Confidence {pct(confidence.overall)}</Badge>
            <Badge variant="info">Value {text(recommendation.expected_value)}</Badge>
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
