/**
 * Plain SVG/CSS charts for the Value page. Each one is fed real rows by the
 * caller and renders nothing it was not given; colours come from the glass
 * tokens so light and dark both work.
 */
import { useState, type ReactNode } from 'react';
import { cn } from '@aether/ui';
import { Eyebrow, Spinner } from '@aether-app/components/ae-ui';
import { HOUR_BANDS, WEEKDAYS, type HeatCell } from './value-model';

export const SERIES_COLORS = [
  'var(--ae-blue)',
  'var(--ae-sage)',
  'var(--ae-violet)',
  'var(--ae-solar)',
  'var(--ae-teal)',
  'var(--ae-amber)',
  'var(--ae-mute)',
] as const;

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length]!;
}

/** A page card in the glass system with an eyebrow title and optional right slot. */
export function ValueCard({
  title,
  aside,
  children,
  className,
  testId,
}: {
  readonly title: ReactNode;
  readonly aside?: ReactNode;
  readonly children: ReactNode;
  readonly className?: string;
  readonly testId?: string;
}) {
  return (
    <section className={cn('ae-card flex min-w-0 flex-col gap-3 rounded-[20px] px-5 py-[18px]', className)} data-testid={testId}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Eyebrow>{title}</Eyebrow>
        {aside}
      </div>
      {children}
    </section>
  );
}

/** Distinct loading / unavailable / empty states for a section read. */
export function SectionLoading({ label }: { readonly label: string }) {
  return (
    <div className="flex items-center gap-2.5 py-4 text-[13px]" style={{ color: 'var(--ae-mute)' }} role="status">
      <Spinner size={16} />
      {label}
    </div>
  );
}

export function SectionUnavailable({ what, detail }: { readonly what: string; readonly detail?: string | null }) {
  return (
    <div className="rounded-xl px-3.5 py-2.5 text-[12px] leading-relaxed" style={{ color: 'var(--ae-amber)', background: 'var(--ae-amber-tint)' }} role="status" data-state="unavailable">
      {what} unavailable right now.{detail ? ` ${detail}` : ''}
    </div>
  );
}

export function SectionEmpty({ children }: { readonly children: ReactNode }) {
  return (
    <p className="py-2 text-[13px] leading-relaxed" style={{ color: 'var(--ae-mute)' }} data-state="empty">
      {children}
    </p>
  );
}

/** Line + area chart over evenly spaced points, with a hover readout. */
export function AreaChart({
  values,
  labels,
  format,
  color = 'var(--ae-blue)',
  height = 180,
  ariaLabel,
}: {
  readonly values: readonly number[];
  readonly labels: readonly string[];
  readonly format: (value: number, index: number) => string;
  readonly color?: string;
  readonly height?: number;
  readonly ariaLabel: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...values, 0);
  const n = values.length;
  const x = (i: number) => (n <= 1 ? 50 : (i / (n - 1)) * 100);
  const y = (v: number) => (max <= 0 ? 92 : 92 - (v / max) * 82);
  const line = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)} ${y(v).toFixed(2)}`).join(' ');
  const area = `${line} L${x(n - 1).toFixed(2)} 100 L${x(0).toFixed(2)} 100 Z`;
  const tickEvery = Math.max(1, Math.ceil(n / 5));

  return (
    <div className="flex flex-col gap-1.5">
      <div
        className="relative"
        style={{ height }}
        onMouseMove={event => {
          const rect = event.currentTarget.getBoundingClientRect();
          if (rect.width <= 0 || n === 0) return;
          setHover(Math.max(0, Math.min(n - 1, Math.round(((event.clientX - rect.left) / rect.width) * (n - 1)))));
        }}
        onMouseLeave={() => setHover(null)}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" role="img" aria-label={ariaLabel}>
          {[25, 50, 75].map(g => (
            <line key={g} x1="0" x2="100" y1={g} y2={g} style={{ stroke: 'var(--ae-edge-soft)' }} strokeWidth="1" vectorEffect="non-scaling-stroke" />
          ))}
          {n > 1 && <path d={area} style={{ fill: color, opacity: 0.1 }} />}
          {n > 1 && <path d={line} fill="none" style={{ stroke: color }} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
          {n === 1 && <circle cx="50" cy={y(values[0]!)} r="1.6" style={{ fill: color }} />}
          {hover !== null && (
            <line x1={x(hover)} x2={x(hover)} y1="0" y2="100" style={{ stroke: 'var(--ae-line)' }} strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {hover !== null && values[hover] !== undefined && (
          <span
            className="ae-mono pointer-events-none absolute top-0 whitespace-nowrap rounded-lg px-2 py-1 text-[11px]"
            style={{
              left: `${Math.min(80, Math.max(0, x(hover) - 10))}%`,
              background: 'var(--ae-raised)',
              border: '1px solid var(--ae-edge)',
            }}
          >
            {labels[hover]} · {format(values[hover]!, hover)}
          </span>
        )}
      </div>
      <div className="ae-mono flex justify-between text-[10px]" style={{ color: 'var(--ae-faint)' }}>
        {labels.map((label, i) => (i % tickEvery === 0 || i === n - 1 ? <span key={`${label}-${i}`}>{label}</span> : null))}
      </div>
    </div>
  );
}

/** Weekday × time-of-day heatmap; clicking a cell selects it. */
export function Heatmap({
  cells,
  selected,
  onSelect,
  metric,
}: {
  readonly cells: readonly HeatCell[];
  readonly selected: { day: number; band: number } | null;
  readonly onSelect: (cell: { day: number; band: number } | null) => void;
  readonly metric: 'total' | 'events';
}) {
  const max = Math.max(...cells.map(c => c[metric]), 0);
  return (
    <div className="grid gap-[3px] text-[10px]" style={{ gridTemplateColumns: '30px repeat(8, minmax(0, 1fr))' }} role="grid" aria-label="Value by weekday and time of day">
      <span />
      {HOUR_BANDS.map(h => (
        <span key={h} className="ae-mono text-center" style={{ color: 'var(--ae-faint)' }}>{h}</span>
      ))}
      {WEEKDAYS.map((label, day) => (
        <div key={label} className="contents" role="row">
          <span className="self-center" style={{ color: 'var(--ae-mute)' }}>{label}</span>
          {cells
            .filter(c => c.day === day)
            .map(cell => {
              const strength = max > 0 ? cell[metric] / max : 0;
              const isSelected = selected?.day === cell.day && selected.band === cell.band;
              return (
                <button
                  key={`${cell.day}-${cell.band}`}
                  type="button"
                  role="gridcell"
                  aria-label={`${label} ${HOUR_BANDS[cell.band]}:00, ${cell.events} value event${cell.events === 1 ? '' : 's'}`}
                  aria-pressed={isSelected}
                  onClick={() => onSelect(isSelected ? null : { day: cell.day, band: cell.band })}
                  className="ae-focus relative h-6 rounded-[5px]"
                  style={{
                    background: 'var(--ae-edge-soft)',
                    outline: isSelected ? '2px solid var(--ae-ink)' : undefined,
                    outlineOffset: isSelected ? 1 : undefined,
                  }}
                >
                  {cell.events > 0 && (
                    <span className="absolute inset-0 rounded-[5px]" style={{ background: 'var(--ae-blue)', opacity: 0.18 + strength * 0.82 }} />
                  )}
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}

/** One horizontal stacked bar with legend rows below. */
export function StackBar({
  segments,
  format,
}: {
  readonly segments: ReadonlyArray<{ key: string; label: string; value: number; detail?: string }>;
  readonly format: (value: number) => string;
}) {
  const total = segments.reduce((a, s) => a + Math.max(0, s.value), 0);
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex h-2.5 gap-0.5 overflow-hidden rounded-[5px]" aria-hidden="true">
        {segments.map((s, i) => (s.value > 0 ? <div key={s.key} style={{ flex: s.value, background: seriesColor(i) }} /> : null))}
      </div>
      <div className="flex flex-col gap-1">
        {segments.map((s, i) => (
          <div key={s.key} className="flex items-baseline justify-between gap-3 text-[13px]">
            <span className="flex min-w-0 items-center gap-2">
              <span className="h-2 w-2 flex-none rounded-full" style={{ background: seriesColor(i) }} />
              <span className="truncate">{s.label}</span>
            </span>
            <span className="ae-mono whitespace-nowrap text-[12px]">
              {format(s.value)}
              <span style={{ color: 'var(--ae-mute)' }}>
                {total > 0 ? ` · ${Math.round((Math.max(0, s.value) / total) * 100)}%` : ''}
                {s.detail ? ` · ${s.detail}` : ''}
              </span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
