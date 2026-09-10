import { Badge } from '@aether/ui';

/**
 * A small, reusable availability marker for capability, integration, and
 * pricing listings across the Aether marketing site. Three honest states only
 * — the same three-way vocabulary the rest of the site already uses in prose
 * ("not yet generally available", "planned", "credential required"): a
 * capability is either live today, open to a limited private preview, or not
 * yet open at all. Nothing here invents a fourth, rosier state.
 */
export type AvailabilityStatus = 'available' | 'preview' | 'coming-soon';

const LABELS: Readonly<Record<AvailabilityStatus, string>> = {
  available: 'Available now',
  preview: 'Private preview',
  'coming-soon': 'Coming soon',
};

const VARIANTS: Readonly<Record<AvailabilityStatus, 'success' | 'accent' | 'default'>> = {
  available: 'success',
  preview: 'accent',
  'coming-soon': 'default',
};

export function AvailabilityBadge({
  status,
  label,
  className,
}: {
  readonly status: AvailabilityStatus;
  /** Override the default label text; the color still reflects `status`. */
  readonly label?: string;
  readonly className?: string;
}) {
  return (
    <Badge variant={VARIANTS[status]} className={className}>
      {label ?? LABELS[status]}
    </Badge>
  );
}
