import { aetherAssets, olympusAssets } from '../assets';
import type { BrandLockup } from '../types';

export const combinedLockups = [
  {
    id: 'olympus-aether-dark',
    layout: 'horizontal',
    variant: 'full',
    context: 'dark',
    asset: aetherAssets.combinedDark,
    minimumWidth: 270,
    minimumClearSpace: 12,
    monochrome: false,
    usage: ['Dark corporate partnership surfaces', 'Product launch material'],
  },
  {
    id: 'olympus-aether-composed',
    layout: 'composed',
    variant: 'full',
    context: 'light',
    composition: {
      mark: olympusAssets.arch,
      wordmark: 'Olympus Labs · Aether',
      parent: 'olympus',
    },
    minimumWidth: 244,
    minimumClearSpace: 12,
    monochrome: false,
    usage: ['Light-context surfaces when the dark combined SVG cannot be used'],
  },
] as const satisfies readonly BrandLockup[];
