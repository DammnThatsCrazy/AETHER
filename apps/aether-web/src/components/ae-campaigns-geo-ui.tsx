import type { ReactNode } from 'react';
import { cn } from '@aether/ui';
import { Bar } from '@aether-app/components/ae-ui';

/**
 * Small primitives shared by the Campaigns and Geography pages (Claude Design
 * handoff: Aether Campaigns, Aether Geography). They only arrange values the
 * caller already read from the backend; none of them invent data.
 */

export interface SegmentOption<T extends string> {
  readonly value: T;
  readonly label: ReactNode;
  /** Optional count badge (e.g. open review items). Hidden when 0/undefined. */
  readonly badge?: number;
  readonly testId?: string;
}

/**
 * Pill segmented control (design: inline-flex pill group on a soft ink tint,
 * selected = inverted chip). Rendered as a tablist so assistive tech and
 * tests can address each option as a tab.
 */
export function SegmentedTabs<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: {
  readonly options: readonly SegmentOption<T>[];
  readonly value: T;
  readonly onChange: (value: T) => void;
  readonly label: string;
  readonly className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      className={cn('ae-scroll-none inline-flex max-w-full gap-0.5 overflow-x-auto rounded-full p-[3px]', className)}
      style={{ background: 'var(--ae-edge-soft)' }}
    >
      {options.map(option => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={selected}
            data-testid={option.testId}
            onClick={() => onChange(option.value)}
            className="ae-focus inline-flex items-center whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px] transition-colors"
            style={{
              background: selected ? 'var(--ae-chip-on)' : 'transparent',
              color: selected ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
            }}
          >
            {option.label}
            {option.badge !== undefined && option.badge > 0 && (
              <span
                className="ae-mono ml-1.5 rounded-full px-1.5 text-[11px] font-medium"
                style={{ background: 'var(--ae-amber)', color: '#fff' }}
              >
                {option.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** Small outline chip used for secondary dimension pickers (design: "Channel / Device / Place"). */
export function OutlineChip({
  selected,
  onClick,
  children,
}: {
  readonly selected: boolean;
  readonly onClick: () => void;
  readonly children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className="ae-focus whitespace-nowrap rounded-full border px-3 py-1 text-[12px] transition-colors"
      style={{
        background: selected ? 'var(--ae-chip-on)' : 'transparent',
        color: selected ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
        borderColor: selected ? 'var(--ae-chip-on)' : 'var(--ae-edge)',
      }}
    >
      {children}
    </button>
  );
}

/** Label · value · share row with a thin bar (design: breakdown rows). */
export function ShareRow({
  label,
  value,
  share,
  color = 'var(--ae-blue)',
  leading,
}: {
  readonly label: ReactNode;
  readonly value: ReactNode;
  /** 0–100, or null when the share is not computable. */
  readonly share: number | null;
  readonly color?: string;
  readonly leading?: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="flex items-center justify-between gap-2 text-[13px]">
        <span className="flex min-w-0 items-center gap-2">
          {leading}
          <span className="truncate">{label}</span>
        </span>
        <span className="ae-mono shrink-0 text-[12px]">
          {value}
          {share !== null && <span style={{ color: 'var(--ae-faint)' }}> · {Math.round(share)}%</span>}
        </span>
      </span>
      <Bar value={share ?? 0} color={color} height={6} />
    </div>
  );
}

/** Glass search field (design: pill input on the page header). */
export function GlassSearch({
  value,
  onChange,
  placeholder,
  label,
}: {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
  readonly label: string;
}) {
  return (
    <input
      type="search"
      value={value}
      aria-label={label}
      placeholder={placeholder}
      onChange={event => onChange(event.target.value)}
      className="ae-focus min-w-0 flex-1 rounded-full border px-4 py-[9px] text-[13px] outline-none sm:min-w-[190px] sm:flex-none"
      style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' }}
    />
  );
}

/** Section card used inside a glass page (design: 22–24px radius glass panel). */
export function GlassSection({
  children,
  className,
  testId,
}: {
  readonly children: ReactNode;
  readonly className?: string;
  readonly testId?: string;
}) {
  return (
    <section
      className={cn('ae-glass-card flex min-w-0 flex-col gap-2.5 rounded-[22px] px-[18px] py-4 sm:px-5', className)}
      data-testid={testId}
    >
      {children}
    </section>
  );
}

/** Dashed empty slot (design: "No campaigns here."). */
export function EmptySlot({ children, testId }: { readonly children: ReactNode; readonly testId?: string }) {
  return (
    <div
      className="rounded-[22px] border border-dashed px-5 py-6 text-center text-[13px] leading-relaxed"
      style={{ borderColor: 'var(--ae-faint)', color: 'var(--ae-mute)' }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

/** Centred spinner row for a loading read. */
export function LoadingRow({ label }: { readonly label: string }) {
  return (
    <div className="flex items-center gap-3 py-4 text-[13px]" style={{ color: 'var(--ae-mute)' }} role="status">
      <span
        aria-hidden="true"
        className="ae-spin inline-block rounded-full"
        style={{ width: 18, height: 18, border: '2px solid var(--ae-edge)', borderTopColor: 'var(--ae-blue)' }}
      />
      {label}
    </div>
  );
}
