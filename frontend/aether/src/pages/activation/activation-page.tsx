import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CapabilityStateBadge,
  EmptyState,
  ErrorState,
  LoadingState,
} from '@aether/ui';
import type { SourcePlatform } from '@aether/shared';
import {
  ACTIVATION_PLAN_TIERS,
  activationCapabilityState,
  activationStateLabel,
  useActivationStatus,
  useCompleteActivation,
  useCreateSdkKeys,
  useFirstValue,
  useSelectPlan,
  useSelectSdks,
  useSendTestEvent,
  type ActivationPlanTier,
  type ActivationStatus,
} from '@aether-app/features/activation/use-activation';

// The five first-party SDK platforms the backend accepts. Sourced from the
// shared SourcePlatform union so this list can never drift from the contract.
const SDK_PLATFORMS: readonly SourcePlatform[] = [
  'web',
  'ios',
  'android',
  'react-native',
  'server',
];

function isSourcePlatform(value: string): value is SourcePlatform {
  return (SDK_PLATFORMS as readonly string[]).includes(value);
}

function evidenceValue(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

// Step components are exported (additive) so the WS-3 guided activate page
// (/activate) can reuse the same proven SDK activation steps — one canonical
// finish path, never a second implementation.
export interface StepShellProps {
  readonly index: number;
  readonly title: string;
  readonly done: boolean;
  readonly available: boolean;
  readonly children: React.ReactNode;
}

/** Uniform step frame with an honest per-step capability badge. */
export function StepShell({ index, title, done, available, children }: StepShellProps) {
  const badgeState = done ? 'live' : available ? 'credential_required' : 'not_configured';
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3 text-sm">
          <span className="text-text-primary">
            {index}. {title}
          </span>
          <CapabilityStateBadge state={badgeState} label={done ? 'Done' : undefined} />
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  );
}

export interface StepProps {
  readonly status: ActivationStatus;
}

export function PlanStep({ status }: StepProps) {
  const selectPlan = useSelectPlan();
  const selected = status.selected_plan_tier;
  const done = Boolean(selected);

  return (
    <StepShell index={1} title="Choose your plan" done={done} available>
      {selectPlan.error && (
        <ErrorState message={`Could not select plan: ${selectPlan.error}`} />
      )}
      <div className="flex flex-wrap gap-2">
        {ACTIVATION_PLAN_TIERS.map(tier => {
          const isCurrent = selected === tier;
          return (
            <Button
              key={tier}
              variant={isCurrent ? 'primary' : 'secondary'}
              size="sm"
              disabled={selectPlan.isLoading}
              onClick={() => void selectPlan.mutate({ plan_tier: tier as ActivationPlanTier })}
            >
              {tier}
            </Button>
          );
        })}
      </div>
      {selectPlan.isLoading && <LoadingState lines={1} />}
      {done && !selectPlan.isLoading && (
        <p className="text-xs font-mono text-text-muted">
          Selected plan tier <span className="text-text-primary">{selected}</span> · billing{' '}
          {status.billing_state}
        </p>
      )}
    </StepShell>
  );
}

export function SdkStep({ status }: StepProps) {
  const selectSdks = useSelectSdks();
  const available = Boolean(status.selected_plan_tier);
  const done = status.sdk_selection.length > 0;
  const [draft, setDraft] = useState<readonly SourcePlatform[]>([]);

  const seed = status.sdk_selection.join(',');
  useEffect(() => {
    setDraft(status.sdk_selection.filter(isSourcePlatform));
    // Reseed only when the backend selection actually changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed]);

  function toggle(platform: SourcePlatform) {
    setDraft(prev =>
      prev.includes(platform) ? prev.filter(p => p !== platform) : [...prev, platform],
    );
  }

  return (
    <StepShell index={2} title="Select your SDKs" done={done} available={available}>
      {!available && (
        <EmptyState title="Select a plan first" description="SDK selection unlocks after a plan is chosen." />
      )}
      {available && (
        <>
          {selectSdks.error && (
            <ErrorState message={`Could not save SDK selection: ${selectSdks.error}`} />
          )}
          <div className="flex flex-wrap gap-2">
            {SDK_PLATFORMS.map(platform => {
              const active = draft.includes(platform);
              return (
                <Button
                  key={platform}
                  variant={active ? 'primary' : 'secondary'}
                  size="sm"
                  disabled={selectSdks.isLoading}
                  onClick={() => toggle(platform)}
                >
                  {platform}
                </Button>
              );
            })}
          </div>
          <Button
            variant="secondary"
            size="sm"
            disabled={selectSdks.isLoading || draft.length === 0}
            onClick={() => void selectSdks.mutate({ platforms: draft })}
          >
            {selectSdks.isLoading ? '[···]' : 'Save SDK selection'}
          </Button>
          {done && (
            <p className="text-xs font-mono text-text-muted">
              Backend has recorded: {status.sdk_selection.join(', ')}
            </p>
          )}
        </>
      )}
    </StepShell>
  );
}

export function KeysStep({ status }: StepProps) {
  const createKeys = useCreateSdkKeys();
  const available = status.sdk_selection.length > 0;
  const done = status.created_key_ids.length > 0;
  const [label, setLabel] = useState('Onboarding key');
  const [count, setCount] = useState(1);

  const minted = createKeys.data?.keys ?? [];

  return (
    <StepShell index={3} title="Create SDK keys" done={done} available={available}>
      {!available && (
        <EmptyState title="Select an SDK first" description="Keys are scoped to your selected platforms." />
      )}
      {available && (
        <>
          {createKeys.error && (
            <ErrorState message={`Could not create keys: ${createKeys.error}`} />
          )}
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Label
              <input
                type="text"
                value={label}
                onChange={e => setLabel(e.target.value)}
                className="bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Count
              <input
                type="number"
                min={1}
                max={5}
                value={count}
                onChange={e => setCount(Math.max(1, Math.min(5, Number(e.target.value) || 1)))}
                className="w-20 bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
            </label>
            <Button
              variant="secondary"
              size="sm"
              disabled={createKeys.isLoading}
              onClick={() => void createKeys.mutate({ count, label })}
            >
              {createKeys.isLoading ? '[···]' : 'Create keys'}
            </Button>
          </div>

          {createKeys.isLoading && <LoadingState lines={1} />}

          {minted.length > 0 ? (
            <div className="rounded border border-warning/30 bg-warning/10 p-3 space-y-2">
              <p className="text-xs font-mono text-warning">
                Copy these keys now — the raw value is shown only once.
              </p>
              {minted.map(k => (
                <div key={k.id} className="flex flex-col gap-0.5">
                  <span className="text-[10px] font-mono text-text-muted">
                    {k.label} · {k.id}
                  </span>
                  <code className="text-xs font-mono text-text-primary break-all select-all">
                    {k.key}
                  </code>
                </div>
              ))}
            </div>
          ) : done ? (
            <p className="text-xs font-mono text-text-muted">
              {status.created_key_ids.length} key
              {status.created_key_ids.length === 1 ? '' : 's'} on record (raw values were shown once at
              creation).
            </p>
          ) : (
            <EmptyState title="No SDK keys created yet" description="Mint at least one key to begin sending events." />
          )}
        </>
      )}
    </StepShell>
  );
}

export function TestEventStep({ status }: StepProps) {
  const sendEvent = useSendTestEvent();
  const available = status.created_key_ids.length > 0;
  const eventFlowed =
    status.state === 'event_received' ||
    status.state === 'first_value_ready' ||
    status.state === 'complete';
  const [eventType, setEventType] = useState('page_view');

  const results = sendEvent.data?.results ?? [];

  return (
    <StepShell index={4} title="Send a test event" done={eventFlowed} available={available}>
      {!available && (
        <EmptyState title="Create a key first" description="A test event needs a live SDK key to authenticate." />
      )}
      {available && (
        <>
          {sendEvent.error && (
            <ErrorState message={`Could not send test event: ${sendEvent.error}`} />
          )}
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-xs text-text-secondary">
              Event type
              <input
                type="text"
                value={eventType}
                onChange={e => setEventType(e.target.value)}
                className="bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
            </label>
            <Button
              variant="secondary"
              size="sm"
              disabled={sendEvent.isLoading || eventType.trim().length === 0}
              onClick={() => void sendEvent.mutate({ event_type: eventType.trim() })}
            >
              {sendEvent.isLoading ? '[···]' : 'Send test event'}
            </Button>
          </div>

          {sendEvent.isLoading && <LoadingState lines={1} />}

          {results.length > 0 ? (
            <div className="space-y-1">
              {results.map((r, i) => (
                <div key={i} className="flex items-center gap-2 text-xs font-mono">
                  <Badge
                    variant={
                      r.status === 'accepted'
                        ? 'success'
                        : r.status === 'duplicate'
                          ? 'warning'
                          : 'danger'
                    }
                    size="sm"
                  >
                    {r.status}
                  </Badge>
                  {r.reason && <span className="text-text-muted">{r.reason}</span>}
                </div>
              ))}
            </div>
          ) : (
            !eventFlowed && (
              <EmptyState
                title="No test event sent yet"
                description={status.waiting_reason ?? 'Send one event to move activation forward.'}
              />
            )
          )}
        </>
      )}
    </StepShell>
  );
}

export function FirstValueStep({ status }: StepProps) {
  const firstValue = useFirstValue();
  const available =
    status.state === 'event_received' ||
    status.state === 'first_value_ready' ||
    status.state === 'complete';
  const fv = firstValue.data;
  const ready = fv?.ready ?? (status.state === 'first_value_ready' || status.state === 'complete');
  const evidenceEntries = fv ? Object.entries(fv.evidence) : [];

  return (
    <StepShell index={5} title="Prove first value" done={ready} available={available}>
      {firstValue.error && (
        <ErrorState message={`Could not evaluate first value: ${firstValue.error}`} onRetry={firstValue.refetch} />
      )}
      {!firstValue.error && (
        <>
          <div className="flex items-center gap-2">
            <CapabilityStateBadge
              state={ready ? 'sandbox_validated' : 'credential_waiting'}
              label={ready ? 'First value ready' : 'Awaiting first value'}
            />
            <Button variant="ghost" size="sm" disabled={firstValue.isLoading} onClick={firstValue.refetch}>
              {firstValue.isLoading ? '[···]' : 'Re-check'}
            </Button>
          </div>
          {firstValue.isLoading && !fv && <LoadingState lines={2} />}
          {!firstValue.isLoading && evidenceEntries.length > 0 ? (
            <div className="rounded border border-border-subtle bg-surface-raised p-3 space-y-1">
              {evidenceEntries.map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-3 text-xs font-mono">
                  <span className="text-text-secondary">{k}</span>
                  <span className="text-text-primary break-all">{evidenceValue(v)}</span>
                </div>
              ))}
            </div>
          ) : (
            !firstValue.isLoading && (
              <EmptyState
                title="First value not proven yet"
                description="First value is derived from real Bronze events — nothing is shown until the backend confirms it."
              />
            )
          )}
        </>
      )}
    </StepShell>
  );
}

export function CompleteStep({ status }: StepProps) {
  const complete = useCompleteActivation();
  const navigate = useNavigate();
  const isComplete = status.state === 'complete';
  const canComplete = status.state === 'first_value_ready';

  return (
    <StepShell index={6} title="Complete activation" done={isComplete} available={canComplete || isComplete}>
      {complete.error && <ErrorState message={`Could not complete activation: ${complete.error}`} />}
      {isComplete ? (
        <div className="space-y-3">
          <p className="text-sm text-text-primary">Activation complete. Your workspace is live.</p>
          <Button variant="primary" size="sm" onClick={() => void navigate('/')}>
            Go to workspace
          </Button>
        </div>
      ) : (
        <div className="space-y-2">
          {!canComplete && (
            <EmptyState
              title="Not ready to complete"
              description="Completion unlocks once the backend reports first value is ready."
            />
          )}
          <Button
            variant="primary"
            size="sm"
            disabled={!canComplete || complete.isLoading}
            onClick={() => void complete.mutate(undefined)}
          >
            {complete.isLoading ? '[···]' : 'Complete activation'}
          </Button>
        </div>
      )}
    </StepShell>
  );
}

export function ActivationPage() {
  const status = useActivationStatus();
  const data = status.data;

  const header = useMemo(
    () => (
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-sans font-semibold text-text-primary">Activate Aether</h1>
          <p className="text-text-secondary text-sm mt-1">
            Go from account to first value — every step reflects real backend state.
          </p>
        </div>
        {data && (
          <CapabilityStateBadge
            state={activationCapabilityState(data.state)}
            label={activationStateLabel(data.state)}
            reason={data.waiting_reason}
            size="md"
          />
        )}
      </div>
    ),
    [data],
  );

  return (
    <div className="min-h-screen bg-surface-base p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        {header}

        {status.isLoading && !data && <LoadingState lines={6} />}

        {!status.isLoading && status.error && (
          <ErrorState message="Failed to load activation status" onRetry={status.refetch} />
        )}

        {data && (
          <div className="space-y-4">
            <PlanStep status={data} />
            <SdkStep status={data} />
            <KeysStep status={data} />
            <TestEventStep status={data} />
            <FirstValueStep status={data} />
            <CompleteStep status={data} />
          </div>
        )}
      </div>
    </div>
  );
}
