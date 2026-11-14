import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { AetherLockup, LoadingState } from '@aether/ui';
import { AeBackdrop } from '@aether-app/components/ae-backdrop';
import { InlineNotice, LinkButton, PrimaryButton, SecondaryButton } from '@aether-app/components/ae-ui';
import { readStoredFlag, useViewportWidth, writeStoredFlag } from '@aether-app/components/use-viewport-width';
import { useAuth } from '@aether-app/features/auth';
import {
  useActivationStatus,
  useCompleteActivation,
  useFirstValue,
  useSendTestEvent,
} from '@aether-app/features/activation/use-activation';
import {
  useActivationIntentsCatalog,
  useActivationPlan,
  useSaveActivationIntents,
} from '@aether-app/features/activation/use-activation-intents';
import { useTenantReadiness } from '@aether-app/features/activation/use-tenant-readiness';
import { useTenantIntegrations } from '@aether-app/features/integrations';
import {
  useAnalyticsSummary,
  useOrganizationProfile,
  useSaveTenantTimezone,
  useTenantTemporalDefaults,
  useUpdateOrganizationProfile,
} from '@aether-app/features/onboarding/use-workspace-setup';
import { getEnvironment } from '@aether-app/lib/env';
import {
  SDK_OPTIONS,
  STEP_GLYPHS,
  STEP_NAMES,
  browserTimezone,
  deriveResumeStep,
  hasReceivedEvent,
  isRestartRequested,
  sdkIdsForPlatforms,
  workspaceSlug,
  type OnboardingStep,
} from './onboarding-model';
import { GraphStep } from './step-graph';
import { SdksStep, useSdkFleet } from './step-sdks';
import { SourcesStep } from './step-sources';
import { WorkspaceStep } from './step-workspace';

const RAIL_PREF_KEY = 'aether:onboarding-rail-expanded';
const STEPS: readonly OnboardingStep[] = [1, 2, 3, 4];

/**
 * Workspace onboarding — the first screen after signup/confirmation.
 *
 *   1 Workspace   name, goals (activation intents), timezone
 *   2 Sources     recommended connect plan + CSV import
 *   3 SDKs/keys   one SDK = one key, first event
 *   4 Graph       readiness checks → complete activation → Home
 *
 * Every step reads and writes the existing activation, organization, imports
 * and readiness endpoints; the visible state is always the server's.
 */
export function OnboardingFlow() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const width = useViewportWidth();
  const restart = isRestartRequested(location.search, getEnvironment());

  const status = useActivationStatus();
  const intents = useActivationIntentsCatalog();
  const plan = useActivationPlan();
  const saveIntents = useSaveActivationIntents();
  const org = useOrganizationProfile();
  const updateOrg = useUpdateOrganizationProfile();
  const temporal = useTenantTemporalDefaults();
  const saveTimezone = useSaveTenantTimezone();
  const integrations = useTenantIntegrations();
  const complete = useCompleteActivation();
  const sendTest = useSendTestEvent();

  const [step, setStep] = useState<OnboardingStep>(1);
  const [name, setName] = useState('');
  const [goals, setGoals] = useState<readonly string[]>([]);
  const [timezone, setTimezone] = useState<string | null>(null);
  const [sdks, setSdks] = useState<readonly string[]>([]);
  const [saving, setSaving] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const [railPref, setRailPref] = useState<boolean | null>(() => readStoredFlag(RAIL_PREF_KEY));

  const onGraph = step === 4;
  const readiness = useTenantReadiness();
  const firstValue = useFirstValue();
  const summary = useAnalyticsSummary(onGraph ? { pollInterval: 10_000 } : undefined);
  const fleet = useSdkFleet(status.data, sdks);

  // ── Seed drafts once from server truth ─────────────────────────────────────
  const seeded = useRef({ step: false, name: false, goals: false, tz: false, sdks: false });

  useEffect(() => {
    if (seeded.current.step || !status.data) return;
    seeded.current.step = true;
    setStep(deriveResumeStep(status.data, restart));
  }, [status.data, restart]);

  useEffect(() => {
    if (seeded.current.name || !org.data) return;
    seeded.current.name = true;
    setName(org.data.name);
  }, [org.data]);
  useEffect(() => {
    // No organization profile (404 for legacy principals): fall back to the
    // signed-in display name so the field is never blank.
    if (seeded.current.name || !org.error) return;
    seeded.current.name = true;
    setName(user?.displayName ?? '');
  }, [org.error, user?.displayName]);

  useEffect(() => {
    if (seeded.current.goals || !status.data || intents.data === null) return;
    const saved = status.data.intents ?? [];
    if (saved.length > 0) {
      seeded.current.goals = true;
      setGoals(saved);
      return;
    }
    // Marketing hand-off (?intent=<token> / ?experience=<category>) preselects
    // a DRAFT only; it is saved when the visitor continues.
    const intentParam = searchParams.get('intent');
    const experienceParam = searchParams.get('experience');
    const options = intents.data?.intents ?? [];
    if (options.length === 0) return;
    seeded.current.goals = true;
    const matched = options
      .filter(o => o.token === intentParam || (experienceParam !== null && o.recommended_categories.includes(experienceParam)))
      .map(o => o.token);
    if (matched.length) setGoals(matched);
  }, [status.data, intents.data, searchParams]);

  useEffect(() => {
    if (seeded.current.tz) return;
    if (temporal.data) {
      seeded.current.tz = true;
      setTimezone(temporal.data.business_time_zone ?? temporal.data.default_display_time_zone ?? browserTimezone());
    } else if (temporal.error) {
      seeded.current.tz = true;
      setTimezone(browserTimezone());
    }
  }, [temporal.data, temporal.error]);

  // SDK selection resumes from the recorded platforms, told apart by the
  // per-SDK key labels (Web and React share the `web` platform).
  const keyNames = fleet.keys.data?.api_keys.map(k => k.name);
  useEffect(() => {
    if (seeded.current.sdks || !status.data) return;
    if (!keyNames && !fleet.keys.error) return;
    seeded.current.sdks = true;
    const fromRecord = sdkIdsForPlatforms(status.data.sdk_selection, keyNames ?? []);
    // Nothing is preselected: every SDK is the visitor's choice.
    setSdks(fromRecord);
  }, [status.data, keyNames, fleet.keys.error]);

  // Re-evaluate first value while the graph step is open (the GET reconciles
  // from durable Bronze evidence), and refresh the readiness checklist.
  useEffect(() => {
    if (!onGraph) return;
    const t = window.setInterval(() => {
      firstValue.refetch();
      readiness.refetch();
      status.refetch();
    }, 8_000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onGraph]);

  // ── Derived ───────────────────────────────────────────────────────────────
  const state = status.data?.state;
  const built = state === 'complete' || state === 'first_value_ready' || firstValue.data?.ready === true;
  const connected = (integrations.data?.items ?? []).filter(i => i.connected);
  const timezoneAvailable = !temporal.error;
  const slug = workspaceSlug(name);

  const railSub: Record<OnboardingStep, string> = {
    1: (name || 'workspace').slice(0, 10),
    2: connected.length ? `${connected.length} on` : 'none',
    3: fleet.selectedCount ? `${fleet.issuedCount}/${fleet.selectedCount} keys` : 'none',
    4: built ? 'done' : 'build',
  };

  const nextAllowed = useMemo(() => {
    if (step === 1) return name.trim().length > 0 && goals.length > 0;
    // Every SDK is optional (activation proves first value from any ingestion
    // path). Whatever is selected must have its key issued and stored.
    if (step === 3) return fleet.readyCount === fleet.selectedCount;
    if (step === 4) return built;
    return true;
  }, [step, name, goals, fleet.selectedCount, fleet.readyCount, built]);

  const hint =
    step === 1
      ? goals.length === 0
        ? 'Pick at least one goal.'
        : ''
      : step === 2
        ? connected.length
          ? ''
          : 'Optional. You can connect sources later.'
        : step === 3
          ? fleet.selectedCount === 0
            ? 'Optional. Events from connected sources, imports or the API also build your graph.'
            : fleet.readyCount === fleet.selectedCount
              ? ''
              : `${fleet.readyCount} of ${fleet.selectedCount} keys ready. Generate and confirm each key.`
          : built
            ? 'Your graph is ready.'
            : hasReceivedEvent(state)
              ? 'Events received. Verifying first value…'
              : 'Waiting for the first event.';

  async function saveWorkspace(): Promise<boolean> {
    const trimmed = name.trim();
    // Save whenever the name differs from the stored profile, including when
    // the profile read failed: an edited name is never dropped silently.
    if (trimmed && trimmed !== org.data?.name) {
      if (!(await updateOrg.mutate({ name: trimmed }))) {
        setStepError('Could not save the workspace name. Try again, or ask the workspace owner to rename it in Settings.');
        return false;
      }
    }
    const saved = status.data?.intents ?? [];
    const changed = goals.length !== saved.length || goals.some(g => !saved.includes(g));
    if (changed && !(await saveIntents.mutate(goals))) {
      setStepError('Could not save your goals. Try again.');
      return false;
    }
    const currentTz = temporal.data?.business_time_zone ?? null;
    if (timezoneAvailable && timezone && timezone !== currentTz) {
      // Display preference only: a failure is reported but never blocks setup.
      if (!(await saveTimezone.mutate({ timezone, current: temporal.data ?? null }))) {
        setStepError('Your timezone was not saved. You can set it later in Settings.');
      }
    }
    return true;
  }

  async function next() {
    if (!nextAllowed || saving) return;
    setStepError(null);
    setSaving(true);
    try {
      if (step === 1) {
        if (await saveWorkspace()) setStep(2);
      } else if (step === 2) {
        setStep(3);
      } else if (step === 3) {
        setStep(4);
      } else {
        if (state !== 'complete') {
          const done = await complete.mutate(undefined);
          if (!done) {
            setStepError('Activation could not complete yet. First value is still being verified.');
            return;
          }
        }
        void navigate('/home', { replace: true });
      }
    } finally {
      setSaving(false);
    }
  }

  // ── Layout ────────────────────────────────────────────────────────────────
  const small = width < 760;
  const wide = !small && (railPref ?? width >= 1100);
  const railCols = small ? 'minmax(0,1fr)' : wide ? '240px minmax(0,1fr)' : '76px minmax(0,1fr)';
  const pad = small ? 10 : 20;

  if (status.isLoading && !status.data) {
    return (
      <div className="ae-app">
        <AeBackdrop />
        <LoadingState lines={6} className="relative p-8" />
      </div>
    );
  }

  return (
    <div className="ae-app" data-testid="onboarding-flow">
      <AeBackdrop />
      <div
        className="relative mx-auto grid min-h-screen max-w-[1360px] items-start"
        style={{ gridTemplateColumns: railCols, gap: pad, padding: pad }}
      >
        {!small && (
          <aside
            className="ae-glass sticky flex flex-col overflow-hidden rounded-[28px]"
            style={{ top: pad, height: `calc(100vh - ${pad * 2}px)`, padding: '14px 10px 12px' }}
            aria-label="Workspace setup"
          >
            <div className="flex h-11 items-center gap-2.5" style={{ padding: wide ? '0 10px' : 0, justifyContent: wide ? 'flex-start' : 'center' }}>
              <AetherLockup variant="mark" size={26} />
              {wide && (
                <>
                  <div className="flex flex-1 flex-col whitespace-nowrap leading-tight">
                    <span className="text-[15px] font-medium tracking-[-0.2px]">Aether</span>
                    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Olympus Labs</span>
                  </div>
                  <span className="h-2 w-2 flex-none rounded-full" style={{ background: 'var(--ae-sage)' }} />
                </>
              )}
            </div>
            {wide && <div className="ae-eyebrow px-2.5 pb-2 pt-3.5">Workspace setup</div>}
            <ol className="flex min-h-0 flex-1 flex-col gap-0.5" style={{ paddingTop: wide ? 0 : 14 }}>
              {STEPS.map(n => {
                const current = n === step;
                const done = n < step;
                return (
                  <li key={n}>
                    <button
                      type="button"
                      disabled={!done}
                      aria-current={current ? 'step' : undefined}
                      title={STEP_NAMES[n]}
                      onClick={() => done && setStep(n)}
                      className="ae-focus relative flex h-10 w-full items-center gap-3 whitespace-nowrap rounded-xl border text-[13px] disabled:cursor-default"
                      style={{
                        padding: wide ? '0 12px' : 0,
                        justifyContent: wide ? 'flex-start' : 'center',
                        background: current ? 'var(--ae-card)' : 'transparent',
                        borderColor: current ? 'var(--ae-edge)' : 'transparent',
                        color: n > step ? 'var(--ae-mute)' : 'var(--ae-ink)',
                      }}
                    >
                      <span
                        className="absolute rounded-r-[3px]"
                        style={{ left: -10, top: 9, bottom: 9, width: 3, background: current ? 'var(--ae-blue)' : 'transparent' }}
                      />
                      <span
                        className="ae-mono w-5 flex-none text-center text-[14px]"
                        style={{ color: done ? 'var(--ae-sage)' : current ? 'var(--ae-blue-ink)' : 'var(--ae-mute)' }}
                      >
                        {done ? '✓' : STEP_GLYPHS[n]}
                      </span>
                      {wide && (
                        <>
                          <span className="flex-1 text-left" style={{ fontWeight: current ? 500 : 400 }}>{STEP_NAMES[n]}</span>
                          <span
                            className="ae-mono rounded-full px-[7px] py-px text-[11px]"
                            style={{
                              color: done ? 'var(--ae-sage)' : current ? 'var(--ae-blue-ink)' : 'var(--ae-mute)',
                              background: current ? 'var(--ae-blue-tint)' : done ? 'var(--ae-sage-tint)' : 'transparent',
                            }}
                          >
                            {railSub[n]}
                          </span>
                        </>
                      )}
                    </button>
                  </li>
                );
              })}
            </ol>
            <button
              type="button"
              onClick={() => {
                setRailPref(!wide);
                writeStoredFlag(RAIL_PREF_KEY, !wide);
              }}
              aria-label={wide ? 'Collapse sidebar' : 'Expand sidebar'}
              className="ae-focus mb-1.5 flex h-9 items-center gap-3 whitespace-nowrap rounded-xl text-[13px]"
              style={{ padding: wide ? '0 12px' : 0, justifyContent: wide ? 'flex-start' : 'center', color: 'var(--ae-mute)' }}
            >
              <span className="ae-mono w-5 text-center text-[14px]">{wide ? '◂' : '▸'}</span>
              {wide && <span className="flex-1 text-left">Collapse</span>}
            </button>
            <div
              className="mt-2 flex items-center gap-3 whitespace-nowrap border-t pt-3"
              style={{ borderColor: 'var(--ae-edge)', padding: wide ? '12px 6px 0' : '12px 0 0', justifyContent: wide ? 'flex-start' : 'center' }}
            >
              <span className="ae-card flex h-7 w-7 flex-none items-center justify-center rounded-full text-[12px]">
                {(name || 'W').charAt(0).toUpperCase()}
              </span>
              {wide && (
                <span className="flex min-w-0 flex-1 flex-col leading-tight">
                  <span className="truncate text-[13px]">{name || 'Your workspace'}</span>
                  <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>workspace owner</span>
                </span>
              )}
            </div>
          </aside>
        )}

        <section
          className="ae-glass flex min-w-0 flex-col gap-[18px] rounded-[28px]"
          style={{ padding: small ? '18px 16px 16px' : '26px 28px 24px', minHeight: `calc(100vh - ${pad * 2}px)` }}
        >
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-[13px]" style={{ color: 'var(--ae-mute)' }}>
              Setup <span style={{ color: 'var(--ae-faint)' }}>/</span>{' '}
              <span style={{ color: 'var(--ae-ink)' }}>{STEP_NAMES[step]}</span>
            </span>
            <span className="flex flex-wrap items-center gap-2">
              {restart && (
                <span className="ae-mono rounded-full px-3 py-1.5 text-[12px]" style={{ color: 'var(--ae-amber)', background: 'var(--ae-amber-tint)' }}>
                  tester walk-through
                </span>
              )}
              <span className="ae-card ae-mono whitespace-nowrap rounded-xl px-3 py-2 text-[12px]">workspace:{slug}</span>
              <span className="ae-card whitespace-nowrap rounded-full px-3 py-2 text-[13px]">
                <span style={{ color: 'var(--ae-sage)' }}>●</span> read-only
              </span>
            </span>
          </div>

          {small && (
            <div className="flex flex-col gap-1.5">
              <span className="flex justify-between text-[12px]" style={{ color: 'var(--ae-mute)' }}>
                <span>Step {step} of 4</span>
                <span>{STEP_NAMES[step]}</span>
              </span>
              <span className="h-[3px] overflow-hidden rounded-sm" style={{ background: 'var(--ae-edge-soft)' }}>
                <span className="block h-full" style={{ width: `${step * 25}%`, background: 'var(--ae-blue)' }} />
              </span>
            </div>
          )}

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="my-auto flex w-full flex-col gap-[22px]">
              {step === 1 && (
                <WorkspaceStep
                  name={name}
                  onName={setName}
                  goals={goals}
                  onToggleGoal={token => setGoals(prev => (prev.includes(token) ? prev.filter(t => t !== token) : [...prev, token]))}
                  intents={intents.data?.intents ?? []}
                  intentsLoading={intents.isLoading}
                  intentsError={intents.error ? String(intents.error) : null}
                  onRetryIntents={intents.refetch}
                  timezone={timezone}
                  onTimezone={setTimezone}
                  timezoneAvailable={timezoneAvailable}
                  browserTz={browserTimezone()}
                />
              )}
              {step === 2 && (
                <SourcesStep
                  plan={plan.data}
                  loading={plan.isLoading}
                  error={plan.error ? String(plan.error) : null}
                  onRetry={plan.refetch}
                  onBackToGoals={() => setStep(1)}
                />
              )}
              {step === 3 && status.data && (
                <SdksStep
                  status={status.data}
                  selected={sdks}
                  onToggle={id => setSdks(prev => (prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]))}
                  onSelectAll={all => setSdks(all ? SDK_OPTIONS.map(sdk => sdk.id) : [])}
                  fleet={fleet}
                />
              )}
              {step === 4 && status.data && (
                <GraphStep
                  status={status.data}
                  readiness={readiness.data}
                  readinessError={readiness.error ? String(readiness.error) : null}
                  summary={summary.data}
                  connections={connected}
                  sdkNames={SDK_OPTIONS.filter(s => sdks.includes(s.id)).map(s => ({ mark: s.mark, name: s.name }))}
                  keysOnRecord={(fleet.keys.data?.api_keys ?? []).length}
                  built={built}
                  canSendTestEvent
                  sendingTestEvent={sendTest.isLoading}
                  onSendTestEvent={() =>
                    void sendTest
                      .mutate({ event_type: 'onboarding_test_event', properties: { source: 'onboarding' } })
                      .then(() => firstValue.refetch())
                  }
                />
              )}
              {status.error && !status.data && (
                <InlineNotice tone="ember">
                  Setup status is unavailable. <LinkButton onClick={status.refetch}>Try again</LinkButton>
                </InlineNotice>
              )}
            </div>
          </div>

          {stepError && <InlineNotice tone={step === 1 && stepError.startsWith('Your timezone') ? 'amber' : 'ember'}>{stepError}</InlineNotice>}

          <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2.5 border-t pt-4" style={{ borderColor: 'var(--ae-edge)' }}>
            <SecondaryButton
              className={step === 1 ? 'invisible' : ''}
              onClick={() => setStep(s => (s > 1 ? ((s - 1) as OnboardingStep) : s))}
            >
              Back
            </SecondaryButton>
            <span
              className="text-center text-[12px]"
              style={{ color: 'var(--ae-mute)', order: small ? 3 : 0, flex: small ? '1 1 100%' : '0 1 auto' }}
              data-testid="onboarding-hint"
            >
              {hint}
              {step === 4 && !built && (
                <>
                  {' '}
                  <LinkButton onClick={() => void navigate('/home')}>Go to Home now</LinkButton>
                </>
              )}
            </span>
            <PrimaryButton disabled={!nextAllowed || saving} onClick={() => void next()} data-testid="onboarding-next">
              {saving ? 'Saving…' : step === 3 ? 'Build my graph' : step === 4 ? 'Open home' : 'Continue'}
            </PrimaryButton>
          </div>
          <span className="flex items-center gap-2 text-[11px]" style={{ color: 'var(--ae-faint)' }}>
            <AetherLockup variant="mark" size={14} /> Olympus Labs · read-only by default
          </span>
        </section>
      </div>
    </div>
  );
}
