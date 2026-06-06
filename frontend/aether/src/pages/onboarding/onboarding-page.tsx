import { Badge, Button, Card, CardContent, CardHeader, CardTitle, EmptyState, GlyphIcon, LoadingState, StatusIndicator, TerminalSeparator } from '@aether/ui';
import { useEventRequirements, useGoLiveReadiness, useOnboardingChecklist, useOnboardingStatus, usePatchOnboardingStep, useSdkInstructions } from '@aether-app/features/onboarding';
import type { ImplementationBlocker, ImplementationStep } from '@aether/shared';

function scoreColor(score: number) {
  if (score >= 80) return 'text-success';
  if (score >= 50) return 'text-warning';
  return 'text-danger';
}

function ProgressBar({ value }: { value: number }) {
  return <div className="h-2 rounded-full bg-surface-sunken overflow-hidden"><div className="h-full bg-accent transition-all" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>;
}

function ChecklistRow({ step, onComplete }: { step: ImplementationStep; onComplete: (stepId: string) => void }) {
  const done = step.status === 'completed' || step.status === 'skipped';
  return (
    <div className="flex items-start justify-between gap-3 rounded-md border border-border-default bg-surface-raised p-3">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <StatusIndicator status={done ? 'healthy' : step.status === 'blocked' ? 'unhealthy' : 'degraded'} />
          <span className="text-sm font-medium text-text-primary">{step.title}</span>
          {step.required && <Badge size="sm" variant="accent">required</Badge>}
        </div>
        <p className="text-xs text-text-muted">{step.description}</p>
        <div className="flex gap-2 text-[10px] font-mono text-text-muted"><span>{step.category}</span><span>owner: {step.owner_type}</span></div>
      </div>
      {step.owner_type !== 'olympus' && !done && <Button size="sm" variant="secondary" onClick={() => onComplete(step.step_id)}>Mark complete</Button>}
    </div>
  );
}

export function OnboardingPage() {
  const status = useOnboardingStatus();
  const checklist = useOnboardingChecklist();
  const sdk = useSdkInstructions();
  const events = useEventRequirements();
  const readiness = useGoLiveReadiness();
  const patchStep = usePatchOnboardingStep();

  if (status.isLoading && !status.data) return <LoadingState lines={6} className="p-8" />;
  const plan = status.data?.plan;
  const steps = checklist.data?.items ?? status.data?.steps ?? [];
  const blockers = checklist.data?.blockers ?? status.data?.blockers ?? [];
  const completion = steps.length ? Math.round((steps.filter((s: ImplementationStep) => ['completed', 'skipped'].includes(s.status)).length / steps.length) * 100) : 0;

  return (
    <div className="p-6 space-y-6" data-testid="aether-onboarding-center">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-text-primary flex items-center gap-2"><GlyphIcon glyph="[on]" className="text-accent" /> Onboarding Center</h1>
          <p className="text-sm text-text-muted">Track SDK install, graph activation, recommendation rollout, playbooks, integrations, outcomes, and value proof.</p>
        </div>
        <Badge variant={plan?.status === 'blocked' ? 'danger' : 'accent'}>{plan?.onboarding_stage ?? 'plan pending'}</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ['Implementation Health', plan?.implementation_health_score ?? 0],
          ['Go-live Readiness', plan?.go_live_readiness_score ?? Number(readiness.data?.['score'] ?? 0)],
          ['Value Readiness', plan?.value_readiness_score ?? 0],
          ['Expansion Readiness', plan?.expansion_readiness_score ?? 0],
        ].map(([label, value]) => <Card key={label}><CardContent className="p-4"><div className="text-xs text-text-muted">{label}</div><div className={`text-2xl font-mono ${scoreColor(Number(value))}`}>{value}%</div></CardContent></Card>)}
      </div>

      <Card>
        <CardHeader><CardTitle>Completion Progress</CardTitle></CardHeader>
        <CardContent className="space-y-2"><ProgressBar value={completion} /><div className="text-xs text-text-muted">{completion}% complete across {steps.length} onboarding steps.</div></CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.3fr_.7fr]">
        <Card>
          <CardHeader><CardTitle>Onboarding Checklist</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {steps.length === 0 ? <EmptyState title="No checklist yet" description="Olympus Labs will create your implementation plan after contract signature." /> : steps.map((step: ImplementationStep) => <ChecklistRow key={step.step_id} step={step} onComplete={(stepId) => patchStep.mutate({ stepId, status: 'completed' })} />)}
          </CardContent>
        </Card>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle>Required Tenant Actions</CardTitle></CardHeader><CardContent className="space-y-2">{(checklist.data?.tenant_actions ?? []).slice(0, 5).map((a: ImplementationStep) => <div key={a.step_id} className="text-xs text-text-secondary">• {a.title}</div>)}{!(checklist.data?.tenant_actions ?? []).length && <EmptyState title="No tenant actions" description="Nothing is waiting on your team." />}</CardContent></Card>
          <Card><CardHeader><CardTitle>SDK Install Instructions</CardTitle></CardHeader><CardContent className="text-xs text-text-secondary space-y-1">{((sdk.data?.['steps'] as string[] | undefined) ?? ['Install the Aether SDK.', 'Initialize with tenant-scoped credentials.']).map(item => <div key={item}>• {item}</div>)}</CardContent></Card>
          <Card><CardHeader><CardTitle>Event Requirements</CardTitle></CardHeader><CardContent className="text-xs text-text-secondary space-y-2"><div>Minimum volume: {String(events.data?.['minimum_event_volume'] ?? 0)}</div><TerminalSeparator />{((events.data?.['required_events'] as string[] | undefined) ?? []).map(e => <Badge key={e} size="sm">{e}</Badge>)}</CardContent></Card>
          <Card><CardHeader><CardTitle>Visible Blockers</CardTitle></CardHeader><CardContent>{blockers.length ? blockers.map((b: ImplementationBlocker) => <div key={b.blocker_id} className="rounded border border-border-default p-2 text-xs"><b>{b.severity}</b> — {b.title}</div>) : <EmptyState title="No blockers" description="There are no tenant-visible blockers." />}</CardContent></Card>
        </div>
      </div>
    </div>
  );
}
