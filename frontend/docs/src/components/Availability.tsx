/**
 * Availability badges — small inline markers used inside MDX content to tell
 * readers whether the feature a section describes is live, in preview, or
 * not shipped yet.
 *
 * Usage inside an .mdx file:
 *
 *   import { Available, Preview, ComingSoon } from '../../components/Availability';
 *
 *   ### Heatmaps <Preview />
 *
 * Deliberately styled with inline styles (not Tailwind) to match the rest of
 * this app's components (see DocPage.tsx) — the docs site has no build-time
 * CSS pipeline beyond MDX + plain React.
 */

export type AvailabilityStatus = 'available' | 'preview' | 'coming-soon';

interface AvailabilityProps {
  status: AvailabilityStatus;
  /** Override the default label (e.g. "Beta" instead of "Preview"). */
  label?: string | undefined;
}

const CONFIG: Record<AvailabilityStatus, { label: string; bg: string; fg: string }> = {
  available: { label: 'Available', bg: '#dcfce7', fg: '#15803d' },
  preview: { label: 'Preview', bg: '#fef3c7', fg: '#b45309' },
  'coming-soon': { label: 'Coming Soon', bg: '#f3f4f6', fg: '#6b7280' },
};

export function Availability({ status, label }: AvailabilityProps) {
  const cfg = CONFIG[status];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.3rem',
        fontSize: '0.7rem',
        fontWeight: 600,
        padding: '0.1rem 0.5rem',
        borderRadius: 999,
        background: cfg.bg,
        color: cfg.fg,
        letterSpacing: '0.02em',
        verticalAlign: 'middle',
        marginLeft: '0.5rem',
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: cfg.fg,
          display: 'inline-block',
        }}
      />
      {label ?? cfg.label}
    </span>
  );
}

/** Shorthand: `<Available />` */
export function Available({ label }: { label?: string }) {
  return <Availability status="available" label={label} />;
}

/** Shorthand: `<Preview />` */
export function Preview({ label }: { label?: string }) {
  return <Availability status="preview" label={label} />;
}

/** Shorthand: `<ComingSoon />` */
export function ComingSoon({ label }: { label?: string }) {
  return <Availability status="coming-soon" label={label} />;
}
