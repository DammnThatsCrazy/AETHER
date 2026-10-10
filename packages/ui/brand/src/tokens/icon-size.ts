export type IconSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl';

/** SVG visual size. Interactive controls require the separate hit-target rules. */
export const ICON_SIZE: Readonly<Record<IconSize, number>> = {
  xs: 12,
  sm: 16,
  md: 20,
  lg: 24,
  xl: 32,
};

export const iconSizeGuidance = {
  metadata: { size: 'xs', description: 'Inline metadata and micro indicators.' },
  denseTable: { size: 'sm', description: 'Dense tables, compact badges, and small controls.' },
  navigation: { size: 'md', description: 'Primary navigation destinations.' },
  provider: { size: 'lg', description: 'Provider rows and connector cards.' },
  entity: { size: 'lg', description: 'Entity lists and standard identity rows.' },
  modalIdentity: { size: 'xl', description: 'Provider or entity identity in a modal.' },
  shellBrand: { size: 'xl', description: 'Collapsed shell brand mark.' },
} as const;

export function iconSizePx(size: IconSize): number {
  return ICON_SIZE[size];
}
