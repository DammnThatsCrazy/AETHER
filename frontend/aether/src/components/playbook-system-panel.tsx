import { useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, formatDecimal, useTimeContext, type LocaleContext } from '@aether/ui';
import { usePlaybookPerformance, usePlaybookPerformanceSummary, usePlaybookRuns, usePlaybookTemplates, usePlaybooks } from '@aether-app/features/intelligence';
import { api } from '@aether-app/lib/api/endpoints';

function asItems(data: unknown): Array<Record<string, unknown>> {
  if (data && typeof data === 'object' && 'items' in data) {
    const items = (data as { items?: unknown }).items;
    return Array.isArray(items) ? items as Array<Record<string, unknown>> : [];
  }
  return [];
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

function numberText(value: unknown, locale: LocaleContext) {
  return formatDecimal(Number(value ?? 0), locale, { maximumFractionDigits: 2 });
}

function pct(value: unknown) {
  return `${Math.round(Number(value ?? 0) * 100)}%`;
}

export function PlaybookSystemPanel() {
  const templates = usePlaybookTemplates();
  const playbooks = usePlaybooks();
  const summary = usePlaybookPerformanceSummary();
  const playbookItems = asItems(playbooks.data);
  const [selectedPlaybookId, setSelectedPlaybookId] = useState('');
  const [creatingTemplateId, setCreatingTemplateId] = useState('');
  const selected = selectedPlaybookId || text(playbookItems[0]?.playbook_id, '');

  async function createFromTemplate(templateId: string) {
    setCreatingTemplateId(templateId);
    try {
      const playbook = await api.intelligence.createPlaybookFromTemplate(templateId) as Record<string, unknown>;
      setSelectedPlaybookId(text(playbook.playbook_id, selected));
    } finally {
      setCreatingTemplateId('');
    }
  }

  return (
    <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-text-primary font-medium">Playbook library</h2>
              <p className="mt-1 text-xs text-text-secondary">Create governed operational workflows from repeatable recommendation patterns.</p>
            </div>
            <Badge variant="info">Templates</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {asItems(templates.data).length === 0 ? <p className="text-sm text-text-secondary">No templates available yet.</p> : asItems(templates.data).map((template) => {
              const outcomes = Array.isArray(template.expected_outcome_types) ? template.expected_outcome_types : [];
              const integrations = Array.isArray(template.recommended_integrations) ? template.recommended_integrations : [];
              return (
                <div key={text(template.template_id)} className="rounded-lg border border-border-subtle p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-sm font-medium text-text-primary">{text(template.name)}</h3>
                        <Badge variant="default">{text(template.category).replace(/_/g, ' ')}</Badge>
                      </div>
                      <p className="mt-1 text-xs text-text-secondary">{text(template.description)}</p>
                    </div>
                    <Button size="sm" variant="secondary" disabled={creatingTemplateId === template.template_id} onClick={() => void createFromTemplate(text(template.template_id, ''))}>
                      {creatingTemplateId === template.template_id ? 'Creating…' : 'Create'}
                    </Button>
                  </div>
                  <div className="mt-3 grid gap-2 text-xs text-text-muted md:grid-cols-3">
                    <span>Approval: {text(template.default_approval_level)}</span>
                    <span>Outcomes: {outcomes.slice(0, 2).join(', ') || 'configured'}</span>
                    <span>Integrations: {integrations.slice(0, 3).join(', ') || 'optional'}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">
        <PlaybookPerformanceSummary data={summary.data} />
        <Card>
          <CardHeader><h2 className="text-text-primary font-medium">Tenant playbooks</h2></CardHeader>
          <CardContent>
            {playbookItems.length === 0 ? <p className="text-sm text-text-secondary">No tenant playbooks created yet.</p> : playbookItems.map((playbook) => (
              <button key={text(playbook.playbook_id)} type="button" onClick={() => setSelectedPlaybookId(text(playbook.playbook_id, ''))} className={`mb-2 block w-full rounded-lg border p-3 text-left ${selected === playbook.playbook_id ? 'border-accent bg-accent/10' : 'border-border-subtle'}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{text(playbook.name)}</span>
                  <Badge variant={playbook.enabled ? 'success' : 'default'}>{playbook.enabled ? 'Enabled' : 'Disabled'}</Badge>
                </div>
                <p className="mt-1 text-xs text-text-secondary">Approval: {text(playbook.approval_level)} · {text(playbook.category, text((playbook.recommendation_types as unknown[] | undefined)?.[0]))}</p>
              </button>
            ))}
          </CardContent>
        </Card>
        <PlaybookDetail playbookId={selected} />
      </div>
    </div>
  );
}

function PlaybookPerformanceSummary({ data }: { readonly data: unknown }) {
  const timeCtx = useTimeContext();
  const record = data && typeof data === 'object' ? data as { summary?: Record<string, unknown> } : {};
  const summary = record.summary ?? {};
  return (
    <Card>
      <CardHeader><h2 className="text-text-primary font-medium">Playbook ROI</h2></CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Metric label="Observed" value={`$${numberText(summary.observed_value_total, timeCtx)}`} />
          <Metric label="Expected" value={`$${numberText(summary.expected_value_total, timeCtx)}`} />
          <Metric label="Pending" value={`$${numberText(summary.pending_value_total, timeCtx)}`} />
          <Metric label="Runs" value={numberText(summary.runs_total, timeCtx)} />
          <Metric label="Stale" value={numberText(summary.stale_run_count, timeCtx)} />
          <Metric label="Incomplete" value={numberText(summary.incomplete_run_count, timeCtx)} />
        </div>
      </CardContent>
    </Card>
  );
}

function PlaybookDetail({ playbookId }: { readonly playbookId: string }) {
  const timeCtx = useTimeContext();
  const runs = usePlaybookRuns(playbookId);
  const performance = usePlaybookPerformance(playbookId);
  const perf = performance.data && typeof performance.data === 'object' ? performance.data as Record<string, unknown> : {};
  const runItems = asItems(runs.data).slice(0, 4);

  if (!playbookId) {
    return null;
  }

  return (
    <Card>
      <CardHeader><h2 className="text-text-primary font-medium">Playbook detail</h2></CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <Metric label="Recommendations" value={numberText(perf.recommendations_generated, timeCtx)} />
          <Metric label="Decisions" value={numberText(perf.decisions_recorded, timeCtx)} />
          <Metric label="Actions" value={numberText(perf.actions_logged, timeCtx)} />
          <Metric label="Outcomes" value={numberText(perf.outcomes_observed, timeCtx)} />
          <Metric label="Success rate" value={pct(perf.success_rate)} />
          <Metric label="Capture rate" value={pct(perf.outcome_capture_rate)} />
          <Metric label="Confidence delta" value={numberText(perf.average_confidence_delta, timeCtx)} />
          <Metric label="Pending value" value={`$${numberText(perf.pending_value_total, timeCtx)}`} />
        </div>
        <h3 className="mt-4 text-xs font-medium uppercase tracking-wide text-text-secondary">Recent runs</h3>
        {runItems.length === 0 ? <p className="mt-2 text-xs text-text-muted">No runs yet.</p> : (
          <div className="mt-2 space-y-2">
            {runItems.map((run) => (
              <div key={text(run.run_id)} className="rounded border border-border-subtle p-2 text-xs text-text-secondary">
                <div className="flex items-center justify-between gap-2">
                  <span>{text(run.status)}</span>
                  <span>{text(run.started_at)}</span>
                </div>
                <div>Recommendations: {Array.isArray(run.generated_recommendation_ids) ? run.generated_recommendation_ids.length : 0}</div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { readonly label: string; readonly value: string }) {
  return (
    <div className="rounded-lg border border-border-subtle p-3">
      <div className="text-xs text-text-secondary">{label}</div>
      <div className="mt-1 text-base font-medium text-text-primary">{value}</div>
    </div>
  );
}
