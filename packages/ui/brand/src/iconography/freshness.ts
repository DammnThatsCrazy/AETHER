import type { IconDescriptor } from './types';

export type Freshness = 'current' | 'recent' | 'aging' | 'stale' | 'unknown';

export const freshnessIcons = {
  current: { icon: 'clock-check', label: 'Current', decorativeByDefault: true, description: 'Within the current freshness SLA.' },
  recent: { icon: 'clock-4', label: 'Recent', decorativeByDefault: true, description: 'Recent but nearing the freshness threshold.' },
  aging: { icon: 'clock-arrow-up', label: 'Aging', decorativeByDefault: true, description: 'Approaching the freshness SLA.' },
  stale: { icon: 'clock-alert', label: 'Stale', decorativeByDefault: true, description: 'Outside the freshness SLA.' },
  unknown: { icon: 'clock-question-mark', label: 'Freshness unknown', decorativeByDefault: true, description: 'No reliable freshness timestamp is available.' },
} as const satisfies Readonly<Record<Freshness, IconDescriptor>>;
