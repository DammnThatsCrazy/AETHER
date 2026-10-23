import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '@aether/ui';
import type { JourneyStep } from '@aether-app/features/journey';
import { BrandMark } from '@aether-app/components/brand-mark';
import {
  densityLabel, formatWhen, laneMeta, stepLabel, stepLane, stepTime, visibleLanes, type Density,
} from '@aether-app/features/journeys/journey-model';

/**
 * Primitives shared by the Journeys and Episodes pages (Claude Design:
 * Aether Journeys, Aether Episodes). They only arrange steps the caller read
 * from the compiled journey; none of them invent data.
 */

export type ReplaySpeed = 1 | 4 | 16;
export const REPLAY_SPEEDS: readonly ReplaySpeed[] = [1, 4, 16];

/**
 * Replay position over step order. At 1x the playhead advances one step per
 * second; 4x and 16x scale that. Position is fractional so the playhead glides.
 */
export function useReplay(count: number) {
  const last = Math.max(0, count - 1);
  const [pos, setPos] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<ReplaySpeed>(1);

  useEffect(() => {
    setPos(p => Math.min(p, last));
  }, [last]);

  useEffect(() => {
    if (!playing) return undefined;
    const id = setInterval(() => setPos(p => Math.min(last, p + 0.05 * speed)), 50);
    return () => clearInterval(id);
  }, [playing, speed, last]);

  useEffect(() => {
    if (playing && pos >= last) setPlaying(false);
  }, [playing, pos, last]);

  const toggle = useCallback(() => {
    if (count < 2) return;
    setPlaying(p => {
      if (!p && pos >= last) setPos(0);
      return !p;
    });
  }, [count, pos, last]);

  const seek = useCallback((i: number) => {
    setPos(Math.max(0, Math.min(last, i)));
  }, [last]);

  return { pos, index: Math.min(last, Math.floor(pos + 1e-6)), playing, speed, setSpeed, toggle, seek };
}

export type Replay = ReturnType<typeof useReplay>;

/** Width (px) reserved on the left of the swimlane for lane labels. */
export const SWIMLANE_LABEL_GUTTER = 92;

function xPct(i: number, count: number): number {
  return count > 1 ? 4 + (i / (count - 1)) * 92 : 50;
}

/**
 * "Who acted · replay": one lane per actor class, dots in step order, the
 * path through them, and a playhead driven by `replay`. Clicking a dot seeks.
 */
export function SwimlaneReplay({
  steps,
  replay,
  spawns = [],
  footer,
}: {
  readonly steps: readonly JourneyStep[];
  readonly replay: Replay;
  /** Step indexes to mark as spawn points (an agent's first step). */
  readonly spawns?: readonly number[];
  readonly footer?: ReactNode;
}) {
  const lanes = visibleLanes(steps);
  const laneH = 46;
  const height = lanes.length * laneH;
  const yPct = (i: number) => {
    const li = lanes.findIndex(l => l.key === stepLane(steps[i]!));
    return ((li + 0.5) / lanes.length) * 100;
  };
  const pts = steps.map((_, i) => `${xPct(i, steps.length)},${yPct(i)}`);
  const head = xPct(replay.pos, steps.length);
  const current = steps[replay.index];
  const t0 = steps.length ? stepTime(steps[0]!) : null;
  const t1 = steps.length ? stepTime(steps[steps.length - 1]!) : null;

  return (
    <div className="flex flex-col gap-2.5" data-testid="swimlane-replay">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="ae-eyebrow">Who acted · replay</span>
        <span className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={replay.toggle}
            disabled={steps.length < 2}
            className="ae-btn-primary ae-focus min-w-[64px] px-3.5 py-1 text-[12px] font-medium"
            data-testid="replay-toggle"
          >
            {replay.playing ? 'Pause' : 'Play'}
          </button>
          {REPLAY_SPEEDS.map(s => (
            <button
              key={s}
              type="button"
              aria-pressed={replay.speed === s}
              onClick={() => replay.setSpeed(s)}
              className="ae-focus ae-mono rounded-full border px-2.5 py-0.5 text-[11px]"
              style={{
                background: replay.speed === s ? 'var(--ae-chip-on)' : 'transparent',
                color: replay.speed === s ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
                borderColor: replay.speed === s ? 'var(--ae-chip-on)' : 'var(--ae-edge)',
              }}
            >
              {s}x
            </button>
          ))}
        </span>
      </div>

      <div className="relative w-full overflow-hidden rounded-[14px]" style={{ height, background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
        {lanes.map((l, li) => (
          <div
            key={l.key}
            className="absolute inset-x-0 flex items-center px-3"
            style={{ top: li * laneH, height: laneH, borderTop: li ? '1px dashed var(--ae-edge-soft)' : undefined }}
          >
            <span className="truncate text-[11px]" style={{ color: 'var(--ae-mute)', maxWidth: SWIMLANE_LABEL_GUTTER - 16 }} data-lane-label={l.key}>{l.label}</span>
          </div>
        ))}
        {/* Plot area starts after the lane-label gutter so labels never sit under the first node. */}
        <div className="absolute inset-y-0 right-3" style={{ left: SWIMLANE_LABEL_GUTTER }} data-testid="swimlane-plot">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
            <polyline points={pts.join(' ')} fill="none" stroke="var(--ae-edge)" strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
            <polyline points={pts.slice(0, replay.index + 1).join(' ')} fill="none" stroke="var(--ae-blue)" strokeWidth={2.2} vectorEffect="non-scaling-stroke" />
          </svg>
          <span className="pointer-events-none absolute inset-y-0 w-px" style={{ left: `${head}%`, background: 'var(--ae-blue)', opacity: 0.5, transition: replay.playing ? 'left .05s linear' : 'left .3s cubic-bezier(.22,1,.36,1)' }} />
          {steps.map((s, i) => {
            const color = laneMeta(stepLane(s)).color;
            const done = i <= replay.index;
            return (
              <button
                key={s.step_id}
                type="button"
                title={stepLabel(s)}
                aria-label={`Step ${i + 1}: ${stepLabel(s)}`}
                onClick={() => replay.seek(i)}
                className="ae-focus absolute -translate-x-1/2 -translate-y-1/2 rounded-full"
                style={{
                  left: `${xPct(i, steps.length)}%`,
                  top: `${yPct(i)}%`,
                  width: i === replay.index ? 14 : 10,
                  height: i === replay.index ? 14 : 10,
                  background: done ? color : 'var(--ae-card)',
                  border: `2px solid ${color}`,
                  transition: 'width .2s, height .2s, background .2s',
                }}
              />
            );
          })}
          {spawns.map(i => (
            <span
              key={`spawn-${i}`}
              className="pointer-events-none absolute h-2 w-2 -translate-x-1/2 rotate-45"
              style={{ left: `${xPct(i, steps.length)}%`, top: `calc(${yPct(i)}% - 16px)`, background: 'var(--ae-violet)' }}
              title="Agent spawn point"
              data-testid="spawn-point"
            />
          ))}
        </div>
      </div>

      {footer}

      <input
        type="range"
        min={0}
        max={Math.max(0, steps.length - 1)}
        step={0.01}
        value={replay.pos}
        onChange={e => replay.seek(Number(e.target.value))}
        aria-label="Replay position"
        className="w-full"
        style={{ accentColor: 'var(--ae-blue)' }}
        disabled={steps.length < 2}
      />
      <span className="flex justify-between gap-2 text-[11px]" style={{ color: 'var(--ae-mute)' }}>
        <span className="ae-mono">{formatWhen(t0)}</span>
        <span className="truncate text-center" style={{ color: 'var(--ae-ink)' }} data-testid="replay-current">{current ? stepLabel(current) : ''}</span>
        <span className="ae-mono">{formatWhen(t1)}</span>
      </span>
    </div>
  );
}

/** Bar strip of events per time bin; bins at or before `cursor` are lit. */
export function DensityStrip({ density, cursor }: { readonly density: Density; readonly cursor: number | null }) {
  const max = Math.max(1, ...density.bins);
  const litUntil = cursor !== null && density.start !== null && density.binMs > 0
    ? Math.floor((cursor - density.start) / density.binMs)
    : -1;
  if (density.bins.length === 0) {
    return <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No timestamps reported, so density cannot be drawn.</span>;
  }
  return (
    <div className="flex flex-col gap-1" data-testid="density-strip">
      <span className="ae-eyebrow">{densityLabel(density)}</span>
      <div className="flex h-10 items-end gap-[2px]" role="img" aria-label={`${densityLabel(density)}, peak ${max}`}>
        {density.bins.map((n, i) => (
          <span
            key={i}
            className="flex-1 rounded-[2px]"
            style={{
              height: n ? `${Math.max(10, (n / max) * 100)}%` : 2,
              background: i <= litUntil ? 'var(--ae-blue)' : 'var(--ae-edge)',
              transition: 'background .2s',
            }}
            title={`${n} event${n === 1 ? '' : 's'}`}
          />
        ))}
      </div>
    </div>
  );
}

/** Mini density strip for list cards (no labels). */
export function MiniDensity({ bins }: { readonly bins: readonly number[] }) {
  const max = Math.max(1, ...bins);
  return (
    <span className="flex h-6 w-[96px] flex-none items-end gap-px" aria-hidden="true">
      {bins.map((n, i) => (
        <span key={i} className="flex-1 rounded-[1px]" style={{ height: n ? `${Math.max(14, (n / max) * 100)}%` : 2, background: n ? 'var(--ae-blue)' : 'var(--ae-edge)' }} />
      ))}
    </span>
  );
}

export type EvidenceMode = 'plain' | 'raw';

export function EvidenceModeToggle({ mode, onChange, label = 'Show' }: { readonly mode: EvidenceMode; readonly onChange: (m: EvidenceMode) => void; readonly label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5" role="group" aria-label="Evidence detail">
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
      {(['plain', 'raw'] as const).map(m => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          onClick={() => onChange(m)}
          className="ae-focus rounded-full border px-2.5 py-0.5 text-[12px]"
          style={{
            background: mode === m ? 'var(--ae-chip-on)' : 'transparent',
            color: mode === m ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
            borderColor: mode === m ? 'var(--ae-chip-on)' : 'var(--ae-edge)',
          }}
        >
          {m === 'plain' ? 'Plain' : 'Raw'}
        </button>
      ))}
    </span>
  );
}

export function RawFields({ rows }: { readonly rows: ReadonlyArray<readonly [string, string]> }) {
  return (
    <dl className="ae-mono grid gap-x-3 gap-y-0.5 rounded-[10px] px-3 py-2 text-[11px]" style={{ gridTemplateColumns: 'minmax(110px, max-content) 1fr', background: 'var(--ae-code)', color: 'var(--ae-code-ink)' }}>
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt style={{ opacity: 0.65 }}>{k}</dt>
          <dd className="min-w-0 break-all">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SystemsTouched({ systems }: { readonly systems: readonly string[] }) {
  if (systems.length === 0) {
    return <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>No source, provider or domain is reported on these steps.</span>;
  }
  return (
    <span className="flex flex-wrap gap-1.5" data-testid="systems-touched">
      {systems.map(s => (
        <span key={s} className="inline-flex items-center gap-1.5 rounded-full py-0.5 pl-0.5 pr-2.5 text-[12px]" style={{ background: 'var(--ae-edge-soft)' }}>
          <BrandMark token={s} size={20} shape="round" />
          {s}
        </span>
      ))}
    </span>
  );
}

/** "← Section / Name" breadcrumb used by the open journey and open episode. */
export function Crumb({ to, section, name }: { readonly to: string; readonly section: string; readonly name: string }) {
  return (
    <span className="flex min-w-0 items-center gap-1 text-[13px]" style={{ color: 'var(--ae-mute)' }}>
      <Link to={to} className="ae-focus hover:underline">← {section}</Link>
      <span>/</span>
      <span className="truncate" style={{ color: 'var(--ae-ink)' }}>{name}</span>
    </span>
  );
}

/** Pill tab row (Overview, Timeline, …), addressable as a tablist. */
export function PageTabs<T extends string>({
  tabs, value, onChange, label,
}: {
  readonly tabs: ReadonlyArray<readonly [T, string]>;
  readonly value: T;
  readonly onChange: (t: T) => void;
  readonly label: string;
}) {
  return (
    <div className="ae-scroll-none flex gap-1 overflow-x-auto border-b" style={{ borderColor: 'var(--ae-edge)' }} role="tablist" aria-label={label}>
      {tabs.map(([t, l]) => (
        <button
          key={t}
          type="button"
          role="tab"
          aria-selected={value === t}
          onClick={() => onChange(t)}
          className={cn('ae-focus -mb-px whitespace-nowrap border-b-2 px-3.5 py-2 text-[13px] transition-colors')}
          style={{ borderColor: value === t ? 'var(--ae-blue)' : 'transparent', color: value === t ? 'var(--ae-ink)' : 'var(--ae-mute)' }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

/** Lane-coloured dot for list rows. */
export function LaneDot({ step, size = 8 }: { readonly step: JourneyStep; readonly size?: number }) {
  return <span className="flex-none rounded-full" style={{ width: size, height: size, background: laneMeta(stepLane(step)).color }} aria-hidden="true" />;
}
