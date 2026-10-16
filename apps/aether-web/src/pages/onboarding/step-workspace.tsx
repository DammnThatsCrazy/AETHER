import { ChoiceChip, Eyebrow, InlineNotice, LinkButton } from '@aether-app/components/ae-ui';
import type { ActivationIntentOption } from '@aether-app/features/activation/use-activation-intents';
import { goalStyle, TIMEZONE_CHOICES, workspaceSlug } from './onboarding-model';
import { StepHeading } from './step-heading';

export interface WorkspaceStepProps {
  readonly name: string;
  readonly onName: (value: string) => void;
  readonly goals: readonly string[];
  readonly onToggleGoal: (token: string) => void;
  readonly intents: readonly ActivationIntentOption[];
  readonly intentsLoading: boolean;
  readonly intentsError: string | null;
  readonly onRetryIntents: () => void;
  readonly timezone: string | null;
  readonly onTimezone: (tz: string) => void;
  /** False when the tenant temporal-defaults feature is off for this deployment. */
  readonly timezoneAvailable: boolean;
  readonly browserTz: string | null;
}

export function WorkspaceStep(props: WorkspaceStepProps) {
  const zones = props.browserTz && !(TIMEZONE_CHOICES as readonly string[]).includes(props.browserTz)
    ? [props.browserTz, ...TIMEZONE_CHOICES]
    : [...TIMEZONE_CHOICES];

  return (
    <div className="ae-rise flex flex-col items-center gap-7" data-testid="onboarding-step-workspace">
      <StepHeading
        step={1}
        kicker="workspace"
        title="Name your workspace"
        description="Your goals decide which sources Aether suggests first. Change any of this later in Settings."
      />

      <div className="flex w-full max-w-[420px] flex-col items-center gap-1.5">
        <label htmlFor="workspace-name" className="sr-only">Workspace name</label>
        <input
          id="workspace-name"
          value={props.name}
          maxLength={160}
          onChange={e => props.onName(e.target.value)}
          placeholder="Your workspace"
          className="w-full border-0 border-b bg-transparent px-3 py-2.5 text-center text-[24px] font-medium tracking-[-0.33px] outline-none focus:border-[var(--ae-blue)]"
          style={{ borderColor: 'var(--ae-line)', color: 'var(--ae-ink)' }}
        />
        <span className="ae-mono text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          workspace:{workspaceSlug(props.name)}
        </span>
      </div>

      <div className="flex w-full flex-col items-center gap-2.5">
        <Eyebrow>What should Aether answer first</Eyebrow>
        {props.intentsError ? (
          <InlineNotice tone="ember">
            Could not load goals. <LinkButton onClick={props.onRetryIntents}>Try again</LinkButton>
          </InlineNotice>
        ) : props.intentsLoading && props.intents.length === 0 ? (
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>Loading goals…</span>
        ) : (
          <div className="flex max-w-[640px] flex-wrap justify-center gap-2" role="group" aria-label="Goals">
            {props.intents.map(intent => {
              const on = props.goals.includes(intent.token);
              const style = goalStyle(intent.token);
              return (
                <button
                  key={intent.token}
                  type="button"
                  aria-pressed={on}
                  title={intent.description}
                  data-activation-intent={intent.token}
                  onClick={() => props.onToggleGoal(intent.token)}
                  className="ae-focus inline-flex items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] transition-colors"
                  style={{
                    background: on ? 'var(--ae-blue-tint)' : 'var(--ae-raised)',
                    borderColor: on ? 'var(--ae-blue)' : 'var(--ae-edge-soft)',
                    color: 'var(--ae-ink)',
                  }}
                >
                  <span aria-hidden="true" style={{ color: style.color }}>{style.glyph}</span>
                  {intent.label}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div
        className="flex w-full max-w-[640px] flex-wrap items-center justify-center gap-x-7 gap-y-2.5 border-t pt-[18px]"
        style={{ borderColor: 'var(--ae-edge)' }}
      >
        <div className="flex flex-wrap items-center justify-center gap-1.5" role="group" aria-label="Timezone">
          <span className="mr-0.5 text-[12px]" style={{ color: 'var(--ae-mute)' }}>Timezone</span>
          {zones.map(tz => (
            <ChoiceChip
              key={tz}
              size="sm"
              selected={props.timezone === tz}
              disabled={!props.timezoneAvailable}
              onClick={() => props.onTimezone(tz)}
            >
              {tz}
            </ChoiceChip>
          ))}
        </div>
        {!props.timezoneAvailable && (
          <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>
            Workspace time settings are not enabled on this deployment yet.
          </span>
        )}
      </div>
    </div>
  );
}
