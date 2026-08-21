import type { IconDescriptor } from './types';

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export interface SeverityDescriptor extends IconDescriptor {
  readonly priority: 'P0' | 'P1' | 'P2' | 'P3' | 'info';
}

/** Severity answers urgency only. Pair it with a separate status, domain, and provider where applicable. */
export const severityIcons = {
  critical: { icon: 'octagon-alert', label: 'Critical', decorativeByDefault: true, description: 'Immediate action is required.', priority: 'P0' },
  high: { icon: 'triangle-alert', label: 'High', decorativeByDefault: true, description: 'Urgent attention is required.', priority: 'P1' },
  medium: { icon: 'circle-alert', label: 'Medium', decorativeByDefault: true, description: 'Attention is needed soon.', priority: 'P2' },
  low: { icon: 'info', label: 'Low', decorativeByDefault: true, description: 'Informational attention is useful.', priority: 'P3' },
  info: { icon: 'message-circle-more', label: 'Information', decorativeByDefault: true, description: 'Informational only.', priority: 'info' },
} as const satisfies Readonly<Record<Severity, SeverityDescriptor>>;

export function severityFromPriority(priority: string | null | undefined): Severity {
  switch (priority?.trim().toUpperCase()) {
    case 'P0': return 'critical';
    case 'P1': return 'high';
    case 'P2': return 'medium';
    case 'P3': return 'low';
    default: return 'info';
  }
}
