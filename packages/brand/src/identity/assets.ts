import type { BrandAssetReference } from './types';

/**
 * This package owns the approved Olympus and Aether SVG sources. Vite apps
 * expose this one directory as their `publicDir`, so the same geometry is
 * served by Aether and Kyber without app-local copies.
 */
export const olympusAssets = {
  arch: {
    id: 'olympus-arch',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/logo-olympus-arch.svg',
    publicPath: '/logo-olympus-arch.svg',
    viewBox: '0 0 240 248',
    label: 'Olympus Labs arch',
  },
  horizontal: {
    id: 'olympus-horizontal-lockup',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/lockup-olympus-horizontal.svg',
    publicPath: '/lockup-olympus-horizontal.svg',
    viewBox: '0 0 320 72',
    label: 'Olympus Labs',
  },
} as const satisfies Record<string, BrandAssetReference>;

export const aetherAssets = {
  layers: {
    id: 'aether-layers',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/logo-aether-layers.svg',
    publicPath: '/logo-aether-layers.svg',
    viewBox: '0 0 200 232',
    label: 'Aether layers',
  },
  layersMono: {
    id: 'aether-layers-mono',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/logo-aether-layers-mono.svg',
    publicPath: '/logo-aether-layers-mono.svg',
    viewBox: '0 0 200 232',
    label: 'Aether layers, monochrome',
  },
  horizontal: {
    id: 'aether-horizontal-lockup',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/lockup-aether-horizontal.svg',
    publicPath: '/lockup-aether-horizontal.svg',
    viewBox: '0 0 240 72',
    label: 'Aether',
  },
  combinedDark: {
    id: 'olympus-aether-combined-dark',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/lockup-combined-dark.svg',
    publicPath: '/lockup-combined-dark.svg',
    viewBox: '0 0 540 88',
    label: 'Olympus Labs and Aether',
  },
  favicon: {
    id: 'aether-favicon',
    kind: 'svg',
    sourcePath: 'packages/brand/src/identity/marks/favicon-aether.svg',
    publicPath: '/favicon-aether.svg',
    viewBox: '0 0 200 232',
    label: 'Aether app icon',
  },
} as const satisfies Record<string, BrandAssetReference>;

/**
 * Kept only for migration compatibility. Kyber's approved product lockup is a
 * composition based on the Aether mark, defined in `kyber/manifest.ts`.
 */
export const kyberLegacyAssets = {
  icon: {
    id: 'kyber-legacy-icon',
    kind: 'svg',
    sourcePath: 'frontend/kyber/public/kyber.svg',
    publicPath: '/kyber.svg',
    viewBox: '0 0 32 32',
    label: 'Kyber legacy app icon',
  },
} as const satisfies Record<string, BrandAssetReference>;
