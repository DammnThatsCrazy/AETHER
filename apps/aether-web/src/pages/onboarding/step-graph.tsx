import type { TenantReadinessResponse } from '@aether-app/lib/api/endpoints';
import { BrandMark } from '@aether-app/components/brand-mark';
import { Bar, Eyebrow, InlineNotice, LinkButton, MetricTile, Panel } from '@aether-app/components/ae-ui';
import type { ActivationStatus } from '@aether-app/features/activation/use-activation';
import type { AnalyticsSummary } from '@aether-app/features/onboarding/use-workspace-setup';
import { GRAPH_STAGES, stageStatuses, type StageStatus } from './onboarding-model';
import { StepHeading } from './step-heading';

const STAGE_TONE: Record<StageStatus, { readonly color: string; readonly label: string }> = {
  passed: { color: 'var(--ae-sage)', label: 'verified' },
  running: { color: 'var(--ae-blue-ink)', label: 'in progress' },
  waiting: { color: 'var(--ae-faint)', label: 'waiting' },
  failed: { color: 'var(--ae-ember)', label: 'needs attention' },
  not_applicable: { color: 'var(--ae-faint)', label: 'not applicable' },
  unknown: { color: 'var(--ae-faint)', label: 'not reported' },
};

function count(value: number | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return '—';
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value);
}

export interface GraphStepProps {
  readonly status: ActivationStatus;
  readonly readiness: TenantReadinessResponse | null;
  readonly readinessError: string | null;
  readonly summary: AnalyticsSummary | null;
  readonly connections: readonly { readonly family: string; readonly display_name: string }[];
  readonly sdkNames: readonly { readonly mark: string; readonly name: string }[];
  readonly keysOnRecord: number;
  readonly built: boolean;
  readonly onSendTestEvent: () => void;
  readonly sendingTestEvent: boolean;
  readonly canSendTestEvent: boolean;
}

export function GraphStep(props: GraphStepProps) {
  const statuses = stageStatuses(props.readiness?.checks);
  const chips = [
    ...props.connections.map(c => ({ token: c.family, label: c.display_name })),
    ...props.sdkNames.map(s => ({ token: s.mark, label: s.name })),
  ];
  const halted = props.status.state === 'blocked' || props.status.state === 'externally_blocked' || props.status.state === 'manual_pending';

  return (
    <div className="ae-rise flex flex-col gap-[22px]" data-testid="onboarding-step-graph">
      <StepHeading
        step={4}
        kicker="graph"
        title={props.built ? 'Your graph is ready' : 'Building your graph'}
        description={
          props.built
            ? 'Events are resolving into profiles and relationships. Home is next.'
            : 'Aether is ingesting history and resolving it into profiles. You can leave this page; progress continues in the background.'
        }
      />

      {halted && props.status.waiting_reason && <InlineNotice tone="amber">{props.status.waiting_reason}</InlineNotice>}

      {props.readinessError && (
        <InlineNotice tone="amber">Graph checks are temporarily unavailable. Activation state below is still current.</InlineNotice>
      )}

      <Panel accent="var(--ae-teal)" className="flex flex-col gap-[18px]" style={{ padding: 'clamp(16px,3vw,24px)' }}>
        {GRAPH_STAGES.map((stage, i) => {
          const status = statuses[i] ?? 'waiting';
          const tone = STAGE_TONE[status];
          return (
            <div key={stage.check} className="flex flex-col gap-2" data-stage={stage.check} data-stage-status={status}>
              <div className="flex items-baseline justify-between gap-2.5">
                <span className="flex items-center gap-2.5">
                  <span className="ae-mono w-4 text-center text-[13px]" style={{ color: tone.color }}>
                    {status === 'passed' ? '✓' : stage.glyph}
                  </span>
                  <span className="flex flex-col leading-snug">
                    <span className="text-[14px] font-medium">{stage.label}</span>
                    <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{stage.description}</span>
                  </span>
                </span>
                <span className="ae-mono whitespace-nowrap text-[12px]" style={{ color: tone.color }}>{tone.label}</span>
              </div>
              <Bar
                value={status === 'passed' || status === 'not_applicable' ? 100 : status === 'running' ? null : 0}
                color={status === 'failed' ? 'var(--ae-ember)' : status === 'not_applicable' ? 'var(--ae-edge)' : 'var(--ae-sage)'}
              />
            </div>
          );
        })}
      </Panel>

      <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
        <MetricTile value={count(props.summary?.total_events)} label="events, last 24h" />
        <MetricTile value={count(props.summary?.unique_users)} label="people seen, last 24h" />
        <MetricTile value={count(props.summary?.total_sessions)} label="sessions, last 24h" />
        <MetricTile value={String(props.keysOnRecord)} label="SDK keys issued" />
      </div>

      {!props.built && props.canSendTestEvent && (
        <div className="flex flex-col items-center gap-1 text-center">
          <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
            No events yet? Prove the pipeline end to end with one test event.
          </span>
          <LinkButton onClick={props.onSendTestEvent}>{props.sendingTestEvent ? 'Sending…' : 'Send a test event'}</LinkButton>
        </div>
      )}

      <div className="flex flex-col items-center gap-2.5">
        <Eyebrow>
          Connected to {chips.length} {chips.length === 1 ? 'connection' : 'connections'}
        </Eyebrow>
        <div className="flex flex-wrap justify-center gap-1.5">
          {chips.length === 0 && (
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              Nothing connected yet. Events sent to the Aether API still build the graph.
            </span>
          )}
          {chips.map(chip => (
            <span
              key={`${chip.token}:${chip.label}`}
              className="inline-flex items-center gap-[7px] rounded-full border py-1 pl-[7px] pr-[11px] text-[12px]"
              style={{ background: 'var(--ae-raised)', borderColor: 'var(--ae-edge-soft)' }}
            >
              <BrandMark token={chip.token} label={chip.label} size={16} markSize={14} shape="round" className="border-0" />
              {chip.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
