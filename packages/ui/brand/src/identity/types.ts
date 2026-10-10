/**
 * Asset metadata only. Rendering packages resolve `publicPath` for the app that
 * owns the public directory; this package never copies or redraws a brand mark.
 */
export interface BrandAssetReference {
  readonly id: string;
  readonly kind: 'svg';
  readonly sourcePath: string;
  readonly publicPath: string;
  readonly viewBox: string;
  readonly label: string;
}

export type BrandId = 'olympus' | 'aether' | 'kyber';
export type BrandContext = 'light' | 'dark' | 'either';
export type LockupLayout = 'mark' | 'horizontal' | 'stacked' | 'composed';
export type LockupVariant = 'full' | 'compact' | 'mark';

export interface BrandComposition {
  readonly mark: BrandAssetReference;
  readonly wordmark: string;
  readonly descriptor?: string;
  readonly parent?: 'olympus' | 'aether';
}

export interface BrandLockup {
  readonly id: string;
  readonly layout: LockupLayout;
  readonly variant: LockupVariant;
  readonly context: BrandContext;
  readonly asset?: BrandAssetReference;
  readonly composition?: BrandComposition;
  readonly minimumWidth: number;
  readonly minimumClearSpace: number;
  readonly monochrome: boolean;
  readonly usage: readonly string[];
}

export interface BrandManifest {
  readonly id: BrandId;
  readonly label: string;
  readonly relationship: string;
  readonly mark: BrandAssetReference;
  readonly favicon?: BrandAssetReference;
  readonly lockups: readonly BrandLockup[];
  readonly rules: readonly string[];
}
