import type { CSSProperties, ReactNode } from 'react';
import { cn } from '@aether/ui';

/** Selectable pill (role, timezone, filters). Selected = inverted ink chip. */
export function ChoiceChip({
  selected,
  onClick,
  children,
  size = 'md',
  disabled,
  ...rest
}: {
  readonly selected: boolean;
  readonly onClick: () => void;
  readonly children: ReactNode;
  readonly size?: 'sm' | 'md';
  readonly disabled?: boolean;
  readonly 'data-testid'?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      data-testid={rest['data-testid']}
      className={cn('ae-focus rounded-full border transition-colors disabled:opacity-50', size === 'sm' ? 'px-2.5 py-1 text-[12px]' : 'px-3.5 py-1.5 text-[13px]')}
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

/** Small status pill: tone drives both tint and ink. */
export type Tone = 'blue' | 'sage' | 'amber' | 'ember' | 'mute' | 'solar';

const TONES: Record<Tone, { readonly fg: string; readonly bg: string }> = {
  blue: { fg: 'var(--ae-blue-ink)', bg: 'var(--ae-blue-tint)' },
  sage: { fg: 'var(--ae-sage)', bg: 'var(--ae-sage-tint)' },
  amber: { fg: 'var(--ae-amber)', bg: 'var(--ae-amber-tint)' },
  ember: { fg: 'var(--ae-ember)', bg: 'var(--ae-ember-tint)' },
  solar: { fg: 'var(--ae-solar-ink)', bg: 'var(--ae-solar-wash)' },
  mute: { fg: 'var(--ae-mute)', bg: 'rgba(127,127,127,.1)' },
};

export function toneColor(tone: Tone): string {
  return TONES[tone].fg;
}

export function TonePill({ tone, children, className }: { readonly tone: Tone; readonly children: ReactNode; readonly className?: string }) {
  return (
    <span
      className={cn('inline-flex items-center whitespace-nowrap rounded-full px-2 py-px text-[10px]', className)}
      style={{ color: TONES[tone].fg, background: TONES[tone].bg }}
    >
      {children}
    </span>
  );
}

export function Eyebrow({ children, className, style }: { readonly children: ReactNode; readonly className?: string; readonly style?: CSSProperties }) {
  return (
    <span className={cn('ae-eyebrow', className)} style={style}>
      {children}
    </span>
  );
}

/** Thin progress bar. `value` null renders an indeterminate pulse. */
export function Bar({ value, color = 'var(--ae-blue)', height = 4 }: { readonly value: number | null; readonly color?: string; readonly height?: number }) {
  return (
    <span
      className="block overflow-hidden"
      style={{ height, borderRadius: height / 2, background: 'var(--ae-edge-soft)' }}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
    >
      <span
        className={cn('block h-full', value === null && 'ae-pulse')}
        style={{
          width: `${value === null ? 100 : Math.max(0, Math.min(100, value))}%`,
          background: value === null ? 'var(--ae-blue-tint)' : color,
          transition: 'width .4s cubic-bezier(.22,1,.36,1)',
        }}
      />
    </span>
  );
}

export function Spinner({ size = 28 }: { readonly size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="ae-spin inline-block rounded-full"
      style={{ width: size, height: size, border: '2px solid var(--ae-edge)', borderTopColor: 'var(--ae-blue)' }}
    />
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  className,
  type = 'button',
  ...rest
}: {
  readonly children: ReactNode;
  readonly onClick?: () => void;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly type?: 'button' | 'submit';
  readonly 'data-testid'?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      data-testid={rest['data-testid']}
      className={cn('ae-btn-primary ae-focus px-5 py-[9px]', className)}
    >
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  disabled,
  className,
  ...rest
}: {
  readonly children: ReactNode;
  readonly onClick?: () => void;
  readonly disabled?: boolean;
  readonly className?: string;
  readonly 'data-testid'?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={rest['data-testid']}
      className={cn('ae-btn-secondary ae-focus px-5 py-[9px]', className)}
    >
      {children}
    </button>
  );
}

export function LinkButton({ children, onClick, className, tone = 'blue' }: { readonly children: ReactNode; readonly onClick: () => void; readonly className?: string; readonly tone?: Tone }) {
  return (
    <button type="button" onClick={onClick} className={cn('ae-focus text-[12px] hover:underline', className)} style={{ color: toneColor(tone) }}>
      {children}
    </button>
  );
}

/** Honest inline notice for an unavailable read or a failed write. */
export function InlineNotice({ tone = 'amber', children }: { readonly tone?: Tone; readonly children: ReactNode }) {
  return (
    <div
      className="rounded-xl px-3.5 py-2.5 text-[12px] leading-relaxed"
      style={{ color: TONES[tone].fg, background: TONES[tone].bg }}
      role={tone === 'ember' ? 'alert' : 'status'}
    >
      {children}
    </div>
  );
}

/** Glass panel card used inside a page (lighter than the page frame). */
export function Panel({ children, className, style, accent }: { readonly children: ReactNode; readonly className?: string; readonly style?: CSSProperties; readonly accent?: string }) {
  return (
    <div
      className={cn('ae-glass-card rounded-[22px]', className)}
      style={{
        ...(accent ? { boxShadow: `inset 0 2px 0 ${accent}, inset 0 3px 0 rgba(255,255,255,.7), 0 10px 30px rgba(26,26,30,.06)` } : {}),
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Large metric tile (value + label), mono numerals. */
export function MetricTile({ value, label, sub, tone }: { readonly value: ReactNode; readonly label: string; readonly sub?: ReactNode; readonly tone?: Tone }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-[14px] px-3.5 py-3" style={{ background: 'var(--ae-glass-card)', border: '1px solid var(--ae-edge-soft)' }}>
      <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>{label}</span>
      <span className="ae-mono text-[22px] font-medium tracking-[-0.33px]" style={tone ? { color: toneColor(tone) } : undefined}>{value}</span>
      {sub !== undefined && <span className="text-[11px]" style={{ color: 'var(--ae-mute)' }}>{sub}</span>}
    </div>
  );
}
