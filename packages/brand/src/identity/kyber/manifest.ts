import { aetherAssets, kyberLegacyAssets } from '../assets';
import type { BrandManifest } from '../types';

export const kyberManifest = {
  id: 'kyber',
  label: 'Kyber',
  relationship: 'Aether operations and control-plane identity; never a separate corporate brand.',
  mark: aetherAssets.layers,
  favicon: kyberLegacyAssets.icon,
  lockups: [
    {
      id: 'kyber-aether-operations',
      layout: 'composed',
      variant: 'full',
      context: 'either',
      composition: {
        mark: aetherAssets.layers,
        wordmark: 'Kyber',
        descriptor: 'Aether Operations',
        parent: 'aether',
      },
      minimumWidth: 132,
      minimumClearSpace: 8,
      monochrome: false,
      usage: ['Kyber shell', 'Operator authentication', 'Operational documentation'],
    },
    {
      id: 'kyber-compact',
      layout: 'composed',
      variant: 'compact',
      context: 'either',
      composition: {
        mark: aetherAssets.layers,
        wordmark: 'Kyber',
        parent: 'aether',
      },
      minimumWidth: 84,
      minimumClearSpace: 6,
      monochrome: false,
      usage: ['Compact operator chrome', 'Tablet navigation'],
    },
    {
      id: 'kyber-mark',
      layout: 'mark',
      variant: 'mark',
      context: 'either',
      asset: aetherAssets.layers,
      minimumWidth: 20,
      minimumClearSpace: 4,
      monochrome: false,
      usage: ['Collapsed navigation and mobile only; pair with an accessible Kyber label.'],
    },
  ],
  rules: [
    'Kyber inherits the Aether mark and visual language; show Kyber as the operational context in text.',
    'The legacy Kyber icon is migration-only and must not be redrawn, recolored, or extended.',
    'Do not use Olympus Labs as the primary label inside dense operator workflows.',
  ],
} as const satisfies BrandManifest;
