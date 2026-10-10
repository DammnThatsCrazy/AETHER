import { navigationDestinations, type NavigationDestination } from '@olympus/brand';
import type { ComponentProps } from 'react';

import { Icon } from './icon';

export interface NavigationIconProps extends Omit<ComponentProps<typeof Icon>, 'decorative' | 'label' | 'name'> {
  readonly destination: NavigationDestination;
  /** Set only when an adjacent navigation label is always visible. */
  readonly decorative?: boolean;
  /** Override the canonical destination label for an otherwise unnamed icon control. */
  readonly label?: string;
}

/**
 * Renderer for the Aether and Kyber navigation taxonomy. Collapsed navigation
 * remains named by default, so an icon-only navigation control has an
 * accessible destination name.
 */
export function NavigationIcon({ destination, decorative = false, label, ...props }: NavigationIconProps) {
  const descriptor = navigationDestinations[destination];
  return (
    <Icon
      {...props}
      name={descriptor.icon}
      decorative={decorative}
      label={label ?? descriptor.label}
    />
  );
}
