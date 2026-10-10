import type { FilterDisposition } from '@aether/shared/exploration-contract';
import { Badge } from '../../components/badge';

type BadgeVariant = 'success' | 'info' | 'warning' | 'danger' | 'default';

interface DispositionStyle {
  variant: BadgeVariant;
  label: string;
}

/**
 * Each disposition is VISUALLY DISTINCT — an honest filter UI never lets an
 * "unsupported" or "suppressed" filter look like it was applied.
 */
const DISPOSITION_STYLES: Record<FilterDisposition, DispositionStyle> = {
  applied: { variant: 'success', label: 'Applied' },
  translated: { variant: 'info', label: 'Translated' },
  unsupported: { variant: 'warning', label: 'Unsupported' },
  suppressed: { variant: 'danger', label: 'Suppressed' },
  not_applicable: { variant: 'default', label: 'N/A' },
};

export function dispositionStyle(disposition: FilterDisposition): DispositionStyle {
  return DISPOSITION_STYLES[disposition];
}

export function FilterDispositionBadge({
  disposition,
  reason,
}: {
  readonly disposition: FilterDisposition;
  readonly reason?: string | null | undefined;
}) {
  const { variant, label } = dispositionStyle(disposition);
  return (
    <span title={reason ?? undefined} data-disposition={disposition}>
      <Badge variant={variant} size="sm" className="uppercase tracking-wide">
        {label}
      </Badge>
    </span>
  );
}
