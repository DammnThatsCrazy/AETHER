import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  Input,
} from '@aether/ui';
import { TruthBanner, useExplorationContext } from '@aether/ui/exploration';
import type { ComparisonDefinition } from '@aether/shared/comparison-contract';
import { RestClientError } from '@aether-app/lib/api/rest/client';
import {
  assessFinding,
  comparisonApi,
  definitionRequestFromContext,
  mountedComparisonDimensions,
  mountedComparisonModes,
  preflightComparisonDraft,
  type ComparisonDraft,
  type ComparisonFindingDetail,
  type ComparisonRunDetail,
} from '@aether-app/features/comparison';

const TERMINAL_STATES = new Set([
  'completed',
  'completed_degraded',
  'suppressed',
  'failed',
  'cancelled',
  'expired',
]);

const INITIAL_DRAFT: ComparisonDraft = {
  mode: 'entity_vs_entity',
  subjectId: '',
  baselineEntityId: '',
  historyStart: '',
  historyEnd: '',
  dimension: 'behavior',
};

function pct(value: number | null | undefined): string {
  return value == null ? 'Missing' : `${Math.round(value * 100)}%`;
}

export function ComparisonPage() {
  const context = useExplorationContext();
  const [definitions, setDefinitions] = useState<ComparisonDefinition[]>([]);
  const [draft, setDraft] = useState<ComparisonDraft>(INITIAL_DRAFT);
  const [run, setRun] = useState<ComparisonRunDetail | null>(null);
  const [findings, setFindings] = useState<ComparisonFindingDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [notEnabled, setNotEnabled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draftIssues, setDraftIssues] = useState<string[]>([]);

  const loadDefinitions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDefinitions(await comparisonApi.listDefinitions());
      setNotEnabled(false);
    } catch (cause) {
      setNotEnabled(cause instanceof RestClientError && cause.status === 404);
      setError(cause instanceof Error ? cause.message : 'Comparison definitions unavailable');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDefinitions();
  }, [loadDefinitions]);

  const startRun = useCallback(async (definitionId: string) => {
    setError(null);
    setFindings([]);
    try {
      const created = await comparisonApi.triggerRun(
        definitionId,
        context.temporal.as_of ?? undefined,
      );
      setRun(created);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Comparison run could not start');
    }
  }, [context.temporal.as_of]);

  const createAndRun = useCallback(async () => {
    const issues = preflightComparisonDraft(draft);
    setDraftIssues(issues);
    if (issues.length) return;
    setError(null);
    try {
      const definition = await comparisonApi.createDefinition(
        definitionRequestFromContext(context, draft),
      );
      setDefinitions(current => [definition, ...current]);
      await startRun(definition.definition_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Comparison could not be created');
    }
  }, [context, draft, startRun]);

  useEffect(() => {
    if (!run || TERMINAL_STATES.has(run.state)) {
      if (run && TERMINAL_STATES.has(run.state)) {
        void comparisonApi.listFindings(run.run_id).then(setFindings).catch((cause: unknown) => {
          setError(cause instanceof Error ? cause.message : 'Comparison findings unavailable');
        });
      }
      return;
    }
    const timer = window.setTimeout(() => {
      void comparisonApi.getRun(run.run_id).then(setRun).catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : 'Comparison status unavailable');
      });
    }, 1_000);
    return () => window.clearTimeout(timer);
  }, [run]);

  const assessed = useMemo(
    () => findings.map(finding => assessFinding(finding, run ?? {
      run_id: '',
      definition_id: '',
      tenant_id: context.scope.tenant_id,
      state: 'failed',
    })),
    [context.scope.tenant_id, findings, run],
  );

  const bannerStatus = notEnabled
    ? 'not_enabled'
    : error
      ? 'error'
      : loading
        ? 'loading'
        : 'ready';

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">Comparison Workbench</h1>
        <p className="text-sm text-text-secondary mt-1">
          Tenant-scoped entity and historical comparisons with run-level data-truth preflight.
        </p>
      </div>

      <TruthBanner
        status={bannerStatus}
        surfaceLabel="Comparison intelligence"
        error={error}
        onRetry={loadDefinitions}
      />

      <Card>
        <CardHeader><CardTitle>New comparison</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-xs text-text-secondary">
              Mode
              <select
                value={draft.mode}
                onChange={event => setDraft(current => ({
                  ...current,
                  mode: event.target.value as ComparisonDraft['mode'],
                }))}
                className="w-full rounded border border-border-default bg-surface-base px-3 py-2 text-sm text-text-primary"
              >
                {mountedComparisonModes.map(mode => (
                  <option key={mode} value={mode}>{mode.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-xs text-text-secondary">
              Dimension
              <select
                value={draft.dimension}
                onChange={event => setDraft(current => ({
                  ...current,
                  dimension: event.target.value as ComparisonDraft['dimension'],
                }))}
                className="w-full rounded border border-border-default bg-surface-base px-3 py-2 text-sm text-text-primary"
              >
                {mountedComparisonDimensions.map(dimension => (
                  <option key={dimension} value={dimension}>{dimension.replace(/_/g, ' ')}</option>
                ))}
              </select>
            </label>
            <Input
              aria-label="Subject entity"
              placeholder="Subject entity ID"
              value={draft.subjectId}
              onChange={event => setDraft(current => ({ ...current, subjectId: event.target.value }))}
            />
            {draft.mode === 'entity_vs_entity' ? (
              <Input
                aria-label="Baseline entity"
                placeholder="Baseline entity ID"
                value={draft.baselineEntityId}
                onChange={event => setDraft(current => ({
                  ...current,
                  baselineEntityId: event.target.value,
                }))}
              />
            ) : (
              <>
                <Input
                  aria-label="Historical start"
                  type="datetime-local"
                  value={draft.historyStart}
                  onChange={event => setDraft(current => ({
                    ...current,
                    historyStart: event.target.value,
                  }))}
                />
                <Input
                  aria-label="Historical end"
                  type="datetime-local"
                  value={draft.historyEnd}
                  onChange={event => setDraft(current => ({
                    ...current,
                    historyEnd: event.target.value,
                  }))}
                />
              </>
            )}
          </div>
          {draftIssues.length > 0 && (
            <ul className="text-xs text-danger" aria-label="Comparison preflight blockers">
              {draftIssues.map(issue => <li key={issue}>· {issue}</li>)}
            </ul>
          )}
          <Button onClick={() => void createAndRun()} disabled={notEnabled}>
            Create and run
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Definitions</CardTitle></CardHeader>
        <CardContent>
          {definitions.length === 0 ? (
            <EmptyState
              title="No comparison definitions"
              description="Create an entity or historical comparison to begin."
            />
          ) : (
            <DataTable
              data={definitions}
              keyExtractor={definition => definition.definition_id}
              columns={[
                { key: 'name', header: 'Name', render: definition => definition.name ?? definition.definition_id },
                { key: 'mode', header: 'Mode', render: definition => definition.mode },
                { key: 'subject', header: 'Subject', render: definition => definition.subject.subject_id },
                {
                  key: 'dimensions',
                  header: 'Dimensions',
                  render: definition => definition.dimensions?.join(', ') ?? 'behavior',
                },
                {
                  key: 'run',
                  header: 'Run',
                  render: definition => (
                    <Button size="sm" variant="ghost" onClick={() => void startRun(definition.definition_id)}>
                      Run
                    </Button>
                  ),
                },
              ]}
            />
          )}
        </CardContent>
      </Card>

      {run && (
        <Card>
          <CardHeader><CardTitle>Run preflight</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge>{run.state}</Badge>
              <span>Alignment: {run.alignment_outcome ?? 'pending'}</span>
              {run.degraded_reason && <span className="text-warning">{run.degraded_reason}</span>}
            </div>
            <DataTable
              data={run.data_truth ?? []}
              keyExtractor={entry => entry.dimension}
              emptyMessage="Preflight has not completed."
              columns={[
                { key: 'dimension', header: 'Dimension', render: entry => entry.dimension },
                { key: 'subject', header: 'Subject truth', render: entry => `${entry.subject_state} (${entry.subject_observations})` },
                { key: 'baseline', header: 'Baseline truth', render: entry => `${entry.baseline_state} (${entry.baseline_observations})` },
                { key: 'decision', header: 'Decision', render: entry => <Badge variant={entry.decision === 'compare' ? 'success' : 'danger'}>{entry.decision}</Badge> },
                { key: 'missing', header: 'Missing input', render: entry => entry.refusal_reason ?? '—' },
              ]}
            />
          </CardContent>
        </Card>
      )}

      {run && TERMINAL_STATES.has(run.state) && (
        <Card>
          <CardHeader><CardTitle>Findings</CardTitle></CardHeader>
          <CardContent>
            <DataTable
              data={assessed}
              keyExtractor={row => row.finding.id}
              emptyMessage={run.state === 'suppressed'
                ? 'Comparison suppressed by data-truth preflight.'
                : 'No material differences met the finding threshold.'}
              columns={[
                { key: 'metric', header: 'Metric', render: row => `${row.finding.dimension ?? 'unknown'}.${row.finding.metric ?? 'unknown'}` },
                {
                  key: 'values',
                  header: 'Observed vs baseline',
                  render: row => row.comparable
                    ? `${row.finding.observed_value} vs ${row.finding.baseline_value} ${row.unit}`
                    : <span className="text-danger">Blocked</span>,
                },
                { key: 'confidence', header: 'Confidence', render: row => pct(row.finding.confidence) },
                { key: 'materiality', header: 'Materiality', render: row => pct(row.finding.materiality) },
                { key: 'claim', header: 'Causal claim', render: row => row.finding.causal_claim ?? 'Missing' },
                { key: 'evidence', header: 'Provenance', render: row => row.finding.evidence_basis ?? 'Missing' },
                { key: 'missing', header: 'Missing inputs', render: row => row.missingInputs.join(', ') || 'None' },
              ]}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
