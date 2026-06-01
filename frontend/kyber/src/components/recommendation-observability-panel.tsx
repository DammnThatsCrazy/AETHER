import { useState, type ReactNode } from 'react';
import { Card, CardContent, CardHeader, Badge } from '@aether/ui';
import { useRecommendationObservability, type KyberWindow } from '@kyber/features/recommendation-observability';

const windows: KyberWindow[] = ['7d', '30d', '90d', 'lifetime'];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function items(value: unknown): Array<Record<string, unknown>> {
  const data = record(value);
  return Array.isArray(data.items) ? data.items as Array<Record<string, unknown>> : [];
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function numberText(value: unknown) {
  return Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function pct(value: unknown) {
  return `${Math.round(Number(value ?? 0) * 100)}%`;
}

export function RecommendationObservabilityPanel() {
  const [window, setWindow] = useState<KyberWindow>('30d');
  const data = useRecommendationObservability(window);
  if (!data.enabled) return null;

  const overview = record(record(data.strategicOverview.data).overview);
  const drift = record(record(data.modelConfidenceDrift.data).report);
  const tenants = items(data.tenantValueHealth.data).slice(0, 6);
  const families = items(data.familyPerformance.data).slice(0, 6);
  const playbooks = items(data.playbookPerformance.data).slice(0, 5);
  const solutions = items(data.verticalSolutionSignals.data).slice(0, 4);
  const opportunities = items(data.revenueOpportunities.data).slice(0, 6);

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-text-primary font-medium">Kyber Strategic Observability</h2>
            <p className="text-xs text-text-secondary mt-1">Admin-only aggregate OODA health, tenant value, solution signals, and revenue intelligence.</p>
          </div>
          <div className="flex items-center gap-2">
            {windows.map((item) => (
              <button key={item} type="button" onClick={() => setWindow(item)} className={`rounded-full border px-2 py-1 text-[11px] ${window === item ? 'border-accent text-accent' : 'border-border-subtle text-text-secondary'}`}>
                {item}
              </button>
            ))}
            <Badge variant={drift.drift_status === 'drifting' ? 'danger' : drift.drift_status === 'watch' ? 'warning' : 'success'}>{text(drift.drift_status, 'loading')}</Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {data.isLoading ? <p className="text-sm text-text-secondary">Loading strategic observability…</p> : null}
        {data.error ? <p className="text-sm text-danger">Strategic observability unavailable.</p> : null}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <Metric label="Observed value" value={`$${numberText(overview.observed_value_total)}`} />
          <Metric label="Outcome capture" value={pct(overview.outcome_capture_rate)} />
          <Metric label="Top family" value={text(overview.top_recommendation_family)} />
          <Metric label="Expansion / risk" value={`${numberText(overview.tenants_ready_for_expansion)} ready · ${numberText(overview.tenants_at_risk)} at risk`} />
        </div>

        <Section title="Tenant value health">
          {tenants.length === 0 ? <Empty label="No tenant OODA value data yet." /> : tenants.map((tenant) => (
            <Row key={text(tenant.tenant_id)} title={text(tenant.tenant_name, text(tenant.tenant_id))} badge={pct(tenant.tenant_health_score)}>
              <span>Decision {pct(tenant.decision_rate)}</span>
              <span>Capture {pct(tenant.outcome_capture_rate)}</span>
              <span>Observed ${numberText(tenant.observed_value)}</span>
              <span>Action: {text(tenant.recommended_olympus_action)}</span>
            </Row>
          ))}
        </Section>

        <div className="grid gap-4 xl:grid-cols-2">
          <Section title="Recommendation family performance">
            {families.length === 0 ? <Empty label="No recommendation family activity yet." /> : families.map((family) => (
              <Row key={text(family.recommendation_family)} title={text(family.recommendation_family).replace(/_/g, ' ')} badge={text(family.recommended_commercialization_status)}>
                <span>{numberText(family.generated)} generated</span>
                <span>Success {pct(family.success_rate)}</span>
                <span>Capture {pct(family.outcome_capture_rate)}</span>
                <span>Value ${numberText(family.observed_value)}</span>
              </Row>
            ))}
          </Section>

          <Section title="Playbook performance">
            {playbooks.length === 0 ? <Empty label="No playbook adoption yet." /> : playbooks.map((playbook) => (
              <Row key={text(playbook.template_id)} title={text(playbook.template_name, text(playbook.category))} badge={numberText(playbook.tenant_adoption_count)}>
                <span>{numberText(playbook.runs_total)} runs</span>
                <span>Success {pct(playbook.success_rate)}</span>
                <span>Value ${numberText(playbook.observed_value)}</span>
                <span>{text(playbook.recommended_packaging)}</span>
              </Row>
            ))}
          </Section>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <Section title="Model confidence drift">
            <div className="rounded-lg border border-border-subtle p-3 text-xs text-text-secondary">
              <div className="grid grid-cols-2 gap-2">
                <span>Avg confidence: {pct(drift.confidence_average)}</span>
                <span>Median: {pct(drift.confidence_median)}</span>
                <span>Suppression: {pct(drift.suppression_rate)}</span>
                <span>Low confidence: {pct(drift.low_confidence_rate)}</span>
              </div>
              <p className="mt-2 text-text-primary">{text(drift.recommended_operator_action)}</p>
            </div>
          </Section>

          <Section title="Vertical solution signals">
            {solutions.length === 0 ? <Empty label="No solution signals yet." /> : solutions.map((solution) => (
              <Row key={text(solution.solution_key)} title={text(solution.label)} badge={text(solution.commercial_priority)}>
                <span>{numberText(solution.tenant_count)} tenants</span>
                <span>Adoption {pct(solution.adoption_rate)}</span>
                <span>Value ${numberText(solution.observed_value)}</span>
                <span>{text(solution.recommended_next_product_action)}</span>
              </Row>
            ))}
          </Section>
        </div>

        <Section title="Revenue opportunity feed">
          {opportunities.length === 0 ? <Empty label="No revenue opportunities yet." /> : opportunities.map((opportunity) => (
            <Row key={text(opportunity.opportunity_id)} title={`${text(opportunity.tenant_id)} · ${text(opportunity.opportunity_type).replace(/_/g, ' ')}`} badge={pct(opportunity.confidence)}>
              <span>{text(opportunity.reason)}</span>
              <span>Est. ${numberText(opportunity.estimated_value)}</span>
              <span>{text(opportunity.recommended_action)}</span>
            </Row>
          ))}
        </Section>
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle p-3">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-1 text-lg font-medium text-text-primary">{value}</div>
    </div>
  );
}

function Section({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <div className="mt-4">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-secondary">{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function Row({ title, badge, children }: { readonly title: string; readonly badge: string; readonly children: ReactNode }) {
  return (
    <div className="rounded-lg border border-border-subtle p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm font-medium text-text-primary">{title}</div>
        <Badge variant="info">{badge}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-secondary">{children}</div>
    </div>
  );
}

function Empty({ label }: { readonly label: string }) {
  return <div className="rounded-lg border border-border-subtle p-3 text-sm text-text-secondary">{label}</div>;
}
