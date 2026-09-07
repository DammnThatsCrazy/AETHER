import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Badge,
  Button,
  CapabilityStateBadge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  type CapabilityState,
} from '@aether/ui';
import {
  useActivationConnectAction,
  useActivationIntentsCatalog,
  useActivationPlan,
  useSaveActivationIntents,
  type ActivationConnectAction,
  type ActivationPlan,
  type ActivationPlanCategory,
  type ActivationPlanIntegration,
} from '@aether-app/features/activation/use-activation-intents';
import {
  activationCapabilityState,
  activationStateLabel,
  useActivationStatus,
} from '@aether-app/features/activation/use-activation';
import {
  CompleteStep,
  FirstValueStep,
  KeysStep,
  PlanStep,
  SdkStep,
  TestEventStep,
} from './activation-page';

/**
 * WS-3 guided activation ("/activate"): intent-driven connect over the shared
 * connect contracts.
 *
 * A tenant says what they are trying to do (grow revenue, engage customers, …)
 * and the backend derives the recommended connect plan per experience from the
 * SAME tenant connector rows Settings reads. Every per-integration next step is
 * proposed from real state (create integration → add credential → enable →
 * first sync); nothing is ever dressed as "Ready". The proven SDK activation
 * steps are re-used below to take the tenant the rest of the way to first value.
 */

/** Map a ConnectionState token onto the shared honest capability palette. */
export function connectionCapabilityState(
  connectionState: ActivationPlanIntegration['connection_state'],
): CapabilityState {
  switch (connectionState) {
    case 'available':
      return 'not_configured';
    case 'credential_waiting':
      return 'credential_required';
    case 'disabled':
      return 'disabled';
    case 'initial_sync_pending':
      return 'provisioning';
    case 'initial_sync_running':
      return 'connection_testing';
    case 'connected':
      return 'live';
    case 'degraded':
      return 'degraded';
    case 'sync_failed':
      return 'error';
    default:
      return 'unavailable';
  }
}

export function connectionStateLabel(
  connectionState: ActivationPlanIntegration['connection_state'],
): string {
  switch (connectionState) {
    case 'available':
      return 'Available to connect';
    case 'credential_waiting':
      return 'Credential needed';
    case 'disabled':
      return 'Disabled';
    case 'initial_sync_pending':
      return 'Ready for first sync';
    case 'initial_sync_running':
      return 'Initial sync running';
    case 'connected':
      return 'Connected';
    case 'degraded':
      return 'Degraded';
    case 'sync_failed':
      return 'Sync failed';
    default:
      return connectionState;
  }
}

const CONNECT_ACTION_LABELS: Record<ActivationConnectAction, string> = {
  create_tenant_integration: 'Connect',
  configure_credential: 'Add credential',
  enable_connection: 'Enable connection',
  first_sync: 'Run first sync',
};

function isConnectAction(value: string | null): value is ActivationConnectAction {
  return (
    value === 'create_tenant_integration' ||
    value === 'configure_credential' ||
    value === 'enable_connection' ||
    value === 'first_sync'
  );
}

// ── Intent picker ────────────────────────────────────────────────────────────

interface IntentPickerSectionProps {
  readonly loading: boolean;
  readonly error: string | null;
  readonly refetch: () => void;
  readonly options: ReadonlyArray<{
    readonly token: string;
    readonly label: string;
    readonly description: string;
  }>;
  readonly selected: readonly string[];
  readonly onToggle: (token: string) => void;
  readonly onSave: (intents: readonly string[]) => void;
  readonly saving: boolean;
  readonly saveError: string | null;
}

function IntentPickerSection({
  loading,
  error,
  refetch,
  options,
  selected,
  onToggle,
  onSave,
  saving,
  saveError,
}: IntentPickerSectionProps) {
  if (loading && options.length === 0) return <LoadingState lines={4} />;
  if (error) {
    return <ErrorState message="Could not load the activation intents" onRetry={refetch} />;
  }
  if (options.length === 0) {
    return (
      <EmptyState
        title="No activation intents available"
        description="The intent catalog is empty right now — no recommendations can be made."
      />
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          What are you trying to do? <span className="text-text-muted">(pick any)</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {saveError && <ErrorState message={`Could not save your goals: ${saveError}`} />}
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map(option => {
            const active = selected.includes(option.token);
            return (
              <button
                key={option.token}
                type="button"
                aria-pressed={active}
                onClick={() => onToggle(option.token)}
                className={[
                  'text-left rounded border px-3 py-2 transition-colors',
                  active
                    ? 'border-border-focus bg-surface-raised'
                    : 'border-border-default bg-surface-base hover:border-border-focus',
                ].join(' ')}
              >
                <div className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-text-primary font-medium">{option.label}</span>
                  {active && (
                    <Badge variant="success" size="sm">
                      Selected
                    </Badge>
                  )}
                </div>
                <p className="text-xs text-text-secondary mt-0.5">{option.description}</p>
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="primary" size="sm" disabled={saving} onClick={() => onSave(selected)}>
            {saving ? '[···]' : selected.length === 0 ? 'Save my goals (none yet)' : 'Save my goals'}
          </Button>
          {selected.length > 0 && (
            <Button variant="ghost" size="sm" disabled={saving} onClick={() => onToggle('__clear')}>
              Clear
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ── One integration row (honest next-step CTA) ───────────────────────────────

function IntegrationRow({
  integration,
}: {
  readonly integration: ActivationPlanIntegration;
}) {
  const connect = useActivationConnectAction();
  const badgeState = connectionCapabilityState(integration.connection_state);
  const label = connectionStateLabel(integration.connection_state);
  const record = integration.record;
  const errorCount = record ? Number(record.error_count ?? 0) : 0;
  const [draft, setDraft] = useState('');

  // Never keep a typed credential around once the row has moved past the
  // configure_credential step (the value must not sit in component state).
  useEffect(() => {
    if (integration.next_action !== 'configure_credential') setDraft('');
  }, [integration.next_action]);

  function run() {
    if (!integration.can_act || !isConnectAction(integration.next_action)) return;
    if (integration.next_action === 'configure_credential') {
      const value = draft.trim();
      if (!value) return;
      connect.mutate({
        family: integration.family,
        action: 'configure_credential',
        credential: value,
      });
      return;
    }
    connect.mutate({ family: integration.family, action: integration.next_action });
  }

  const actionLabel = isConnectAction(integration.next_action)
    ? CONNECT_ACTION_LABELS[integration.next_action]
    : null;

  return (
    <div className="flex items-start justify-between gap-3 py-3 border-b border-border-subtle last:border-b-0">
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-text-primary truncate">
            {integration.display_name}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-text-muted font-mono">
            {integration.authentication}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <CapabilityStateBadge state={badgeState} label={label} size="sm" />
        </div>
        {errorCount > 0 && (
          <p className="text-xs font-mono text-warning">
            {errorCount} failed attempt{errorCount === 1 ? '' : 's'}
          </p>
        )}
        {!integration.connectable && (
          <p className="text-xs text-text-muted">
            {integration.connect_unavailable_reason === 'managed_by_other_flow'
              ? 'This connects through its own flow (not through activation).'
              : 'Not available to connect in activation yet.'}
          </p>
        )}
        {connect.error && (
          <p className="text-xs font-mono text-danger break-words">{connect.error}</p>
        )}
      </div>

      <div className="shrink-0 space-y-2">
        {integration.connectable &&
          integration.can_act &&
          integration.next_action === 'configure_credential' && (
            <div className="flex flex-col items-end gap-1">
              <label
                className="text-[10px] uppercase tracking-wide text-text-muted"
                htmlFor={`cred-${integration.family}`}
              >
                Credential
              </label>
              <input
                id={`cred-${integration.family}`}
                type="password"
                autoComplete="off"
                value={draft}
                onChange={e => setDraft(e.target.value)}
                placeholder="provider key"
                className="w-48 bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-border-focus"
              />
            </div>
          )}
        {integration.connectable &&
          integration.can_act &&
          isConnectAction(integration.next_action) && (
            <Button
              variant={integration.next_action === 'first_sync' ? 'secondary' : 'primary'}
              size="sm"
              disabled={
                connect.isLoading ||
                (integration.next_action === 'configure_credential' && !draft.trim())
              }
              onClick={run}
            >
              {connect.isLoading ? '[···]' : actionLabel}
            </Button>
          )}
        {integration.connectable && integration.connection_state === 'connected' && (
          <Link
            to="/integrations"
            className="text-xs text-text-secondary hover:text-text-primary underline"
          >
            Manage
          </Link>
        )}
        {!integration.connectable && (
          <Link
            to="/integrations"
            className="text-xs text-text-secondary hover:text-text-primary underline"
          >
            Settings
          </Link>
        )}
      </div>
    </div>
  );
}

// ── One recommended experience category ──────────────────────────────────────

function PlanCategoryBlock({
  category,
}: {
  readonly category: ActivationPlanCategory;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-3 text-sm">
          <span className="text-text-primary">{category.display_name}</span>
          <span className="text-xs font-mono text-text-muted">
            {category.connected_count}/{category.integration_count} connected
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {category.integrations.length === 0 ? (
          <EmptyState
            title="Nothing to connect yet"
            description="No self-serve integrations are available under this experience right now."
          />
        ) : (
          <div className="divide-y divide-border-subtle">
            {category.integrations.map(integration => (
              <IntegrationRow key={integration.family} integration={integration} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function ActivatePage() {
  const status = useActivationStatus();
  const picker = useActivationIntentsCatalog();
  const plan = useActivationPlan();
  const saveIntents = useSaveActivationIntents();

  // Durable selection is the seed for the picker toggles. Reseed only when the
  // backend-reported selection actually changes (e.g. after a save), never while
  // the user is editing the draft.
  const seededKey = (plan.data?.selected_intents ?? status.data?.intents ?? []).join(',');
  const lastSeed = useRef('');
  const [toggles, setToggles] = useState<readonly string[]>([]);
  useEffect(() => {
    if (seededKey !== lastSeed.current) {
      lastSeed.current = seededKey;
      setToggles(seededKey ? seededKey.split(',').filter(Boolean) : []);
    }
  }, [seededKey]);

  function toggleToken(token: string) {
    if (token === '__clear') {
      setToggles([]);
      return;
    }
    setToggles(prev =>
      prev.includes(token) ? prev.filter(t => t !== token) : [...prev, token],
    );
  }

  const header = (
    <div className="flex items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-sans font-semibold text-text-primary">
          Set up Aether around your goals
        </h1>
        <p className="text-text-secondary text-sm mt-1">
          Tell us what you are trying to do — we recommend the integrations to
          connect, in the order that matters. Every step reflects real connection state.
        </p>
      </div>
      {status.data && (
        <CapabilityStateBadge
          state={activationCapabilityState(status.data.state)}
          label={activationStateLabel(status.data.state)}
          reason={status.data.waiting_reason}
          size="md"
        />
      )}
    </div>
  );

  return (
    <div className="min-h-screen bg-surface-base p-8">
      <div className="max-w-3xl mx-auto space-y-6">
        {header}

        {status.isLoading && !status.data && <LoadingState lines={6} />}

        {!status.isLoading && status.error && (
          <ErrorState message="Failed to load activation status" onRetry={status.refetch} />
        )}

        {status.data && (
          <>
            <IntentPickerSection
              loading={picker.isLoading}
              error={picker.error ? String(picker.error) : null}
              refetch={picker.refetch}
              options={picker.data?.intents ?? []}
              selected={toggles}
              onToggle={toggleToken}
              onSave={tokens => saveIntents.mutate(tokens)}
              saving={saveIntents.isLoading}
              saveError={saveIntents.error ? String(saveIntents.error) : null}
            />

            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">
                Recommended connect plan
              </h2>

              {plan.isLoading && !plan.data && <LoadingState lines={4} />}
              {plan.error && (
                <ErrorState message="Could not load your connect plan" onRetry={plan.refetch} />
              )}

              {plan.data && plan.data.needs_selection && (
                <EmptyState
                  title="Save your goals to see a plan"
                  description="Pick at least one goal above — the recommended integrations are derived from your choices."
                />
              )}

              {plan.data && !plan.data.needs_selection && (
                <div className="space-y-4">
                  {plan.data.categories.length === 0 ? (
                    <EmptyState
                      title="No recommended integrations"
                      description="Your goals don't map to connectable integrations yet — nothing is recommended rather than faking a step."
                    />
                  ) : (
                    plan.data.categories.map(category => (
                      <PlanCategoryBlock
                        key={category.experience_category}
                        category={category}
                      />
                    ))
                  )}
                </div>
              )}
            </section>

            <div className="border-t border-border-default pt-6 space-y-2">
              <h2 className="text-sm font-semibold text-text-primary uppercase tracking-wide">
                Finish activation — prove first value
              </h2>
              <p className="text-xs text-text-secondary">
                Once your integrations are connected, send a first event through
                the SDK to prove Aether works end-to-end.
              </p>
              <PlanStep status={status.data} />
              <SdkStep status={status.data} />
              <KeysStep status={status.data} />
              <TestEventStep status={status.data} />
              <FirstValueStep status={status.data} />
              <CompleteStep status={status.data} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
