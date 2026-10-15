import { olympusAssets } from '../assets';
import type { BrandManifest } from '../types';

export const olympusManifest = {
  id: 'olympus',
  label: 'Olympus Labs',
  relationship: 'Corporate identity. Olympus Labs endorses products without competing with their product-level identity.',
  mark: olympusAssets.arch,
  lockups: [
    {
      id: 'olympus-horizontal',
      layout: 'horizontal',
      variant: 'full',
      context: 'light',
      asset: olympusAssets.horizontal,
      minimumWidth: 144,
      minimumClearSpace: 8,
      monochrome: false,
      usage: ['Corporate marketing', 'Documentation mastheads', 'Partner attribution'],
    },
    {
      id: 'olympus-mark',
      layout: 'mark',
      variant: 'mark',
      context: 'light',
      asset: olympusAssets.arch,
      minimumWidth: 20,
      minimumClearSpace: 4,
      monochrome: true,
      usage: ['Compact corporate attribution', 'App icon composition'],
    },
  ],
  rules: [
    'Use Olympus standalone on corporate surfaces; do not prepend it to normal product navigation.',
    'Do not redraw the arch or recreate the wordmark as a product logo.',
    'Use clear space equal to at least the lockup minimumClearSpace value.',
  ],
} as const satisfies BrandManifest;
