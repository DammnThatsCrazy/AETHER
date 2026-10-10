import { ProviderMark } from '@aether/ui';
import type { FC } from 'react';

/** Notification channels are registry providers, not a feature-local logo pack. */
export type ChannelType = 'slack' | 'discord' | 'telegram' | 'webhook';

interface Props {
  readonly type: ChannelType;
  readonly className?: string;
}

/**
 * Uses a reviewed provider mark when the central registry eventually supplies
 * one. Until then it intentionally renders the neutral initials fallback; no
 * third-party SVG is recreated, recolored, or loaded remotely.
 */
export const ChannelTypeIcon: FC<Props> = ({ type, className = 'w-5 h-5' }) => (
  <ProviderMark provider={type} decorative size={20} className={className} />
);
