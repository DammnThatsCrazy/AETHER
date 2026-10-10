import type { IconDescriptor } from './types';

export type Confidence = 'verified' | 'high' | 'medium' | 'low' | 'unknown';

/** Confidence is evidence certainty, never the health or urgency of an entity. */
export const confidenceIcons = {
  verified: { icon: 'badge-check', label: 'Verified confidence', decorativeByDefault: true, description: 'Verified by a durable source or policy.' },
  high: { icon: 'signal-high', label: 'High confidence', decorativeByDefault: true, description: 'High confidence in the assessment.' },
  medium: { icon: 'signal-medium', label: 'Medium confidence', decorativeByDefault: true, description: 'Moderate confidence in the assessment.' },
  low: { icon: 'signal-low', label: 'Low confidence', decorativeByDefault: true, description: 'Low confidence; confirm before acting.' },
  unknown: { icon: 'circle-help', label: 'Confidence unknown', decorativeByDefault: true, description: 'No confidence signal is available.' },
} as const satisfies Readonly<Record<Confidence, IconDescriptor>>;
