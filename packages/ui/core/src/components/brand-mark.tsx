import {
  aetherManifest,
  kyberManifest,
  lockupVariantFor,
  olympusManifest,
  type BrandAssetReference,
  type BrandId,
  type BrandLockup,
  type BrandManifest,
  type LockupVariant,
} from '@olympus/brand';
import type { CSSProperties, HTMLAttributes } from 'react';

import { cn } from '../utils/cn';

const manifests: Readonly<Record<BrandId, BrandManifest>> = {
  olympus: olympusManifest,
  aether: aetherManifest,
  kyber: kyberManifest,
};

export interface BrandMarkProps extends Omit<HTMLAttributes<HTMLImageElement>, 'alt' | 'src'> {
  readonly brand: BrandId;
  /** Marks beside an already-visible brand name should be hidden from assistive technology. */
  readonly decorative?: boolean;
  /** Override the canonical brand label for a meaningful, context-specific image. */
  readonly label?: string;
  readonly size?: number | string;
}

function brandImageStyle(asset: BrandAssetReference, size: number | string | undefined): CSSProperties {
  return {
    display: 'inline-block',
    width: size,
    height: size,
    objectFit: 'contain',
    aspectRatio: asset.viewBox.split(' ').slice(2).join(' / '),
  };
}

/** Renders an approved brand mark from the canonical asset manifest. */
export function BrandMark({ brand, decorative = false, label, size = 24, className, style, ...props }: BrandMarkProps) {
  const manifest = manifests[brand];
  const accessibleLabel = label ?? manifest.mark.label;

  return (
    <img
      {...props}
      src={manifest.mark.publicPath}
      alt={decorative ? '' : accessibleLabel}
      aria-hidden={decorative || undefined}
      className={cn('aether-brand-mark shrink-0 object-contain', className)}
      style={{ ...brandImageStyle(manifest.mark, size), ...style }}
    />
  );
}

export type ProductLockupVariant = LockupVariant | 'responsive';

export interface ProductLockupProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  readonly brand: BrandId;
  /** `responsive` uses container queries; pass `availableWidth` for deterministic non-DOM rendering. */
  readonly variant?: ProductLockupVariant;
  /** Available inline space in pixels. This selects one canonical lockup without a browser measurement. */
  readonly availableWidth?: number;
  /** A label is announced once for composed responsive lockups; the inner artwork is decorative. */
  readonly label?: string;
  readonly size?: number | string;
}

function findLockup(manifest: BrandManifest, variant: LockupVariant): BrandLockup {
  return manifest.lockups.find(lockup => lockup.variant === variant)
    ?? manifest.lockups.find(lockup => lockup.variant === 'full')
    ?? manifest.lockups[0]!;
}

function lockupSize(lockup: BrandLockup, size: number | string | undefined): CSSProperties {
  const minimum = lockup.minimumWidth;
  return {
    minWidth: minimum,
    height: size,
    maxHeight: size,
  };
}

function LockupArtwork({ lockup, size }: { readonly lockup: BrandLockup; readonly size: number | string | undefined }) {
  if (lockup.asset) {
    return (
      <img
        src={lockup.asset.publicPath}
        alt=""
        aria-hidden="true"
        className="aether-product-lockup__asset block max-w-full object-contain object-left"
        style={lockupSize(lockup, size)}
      />
    );
  }

  const composition = lockup.composition;
  if (!composition) return null;
  return (
    <span className="aether-product-lockup__composition inline-flex min-w-0 items-center gap-2" aria-hidden="true">
      <img
        src={composition.mark.publicPath}
        alt=""
        className="aether-product-lockup__composition-mark shrink-0 object-contain"
        style={brandImageStyle(composition.mark, size)}
      />
      <span className="aether-product-lockup__words flex min-w-0 flex-col leading-none">
        <span className="aether-product-lockup__wordmark font-semibold tracking-tight">{composition.wordmark}</span>
        {composition.descriptor && <span className="aether-product-lockup__descriptor mt-1 text-[0.65em] text-text-secondary">{composition.descriptor}</span>}
      </span>
    </span>
  );
}

function StaticProductLockup({
  manifest,
  variant,
  size,
}: {
  readonly manifest: BrandManifest;
  readonly variant: LockupVariant;
  readonly size: number | string | undefined;
}) {
  return <LockupArtwork lockup={findLockup(manifest, variant)} size={size} />;
}

/**
 * Renders the product lockup selected by the canonical responsive policy.
 *
 * The lockup source always remains a manifest asset or a manifest composition;
 * no product wordmark geometry is recreated here.
 */
export function ProductLockup({
  brand,
  variant,
  availableWidth,
  label,
  size = 28,
  className,
  ...props
}: ProductLockupProps) {
  const manifest = manifests[brand];
  const responsive = variant === 'responsive' && availableWidth === undefined;
  const resolvedVariant: LockupVariant = variant === 'responsive'
    ? (availableWidth === undefined ? 'full' : lockupVariantFor(brand, availableWidth))
    : (variant ?? (availableWidth === undefined ? 'full' : lockupVariantFor(brand, availableWidth)));
  const accessibleLabel = label ?? manifest.label;

  return (
    <span
      {...props}
      className={cn('aether-product-lockup inline-flex min-w-0 items-center', responsive && 'aether-product-lockup--responsive', className)}
      role="img"
      aria-label={accessibleLabel}
      data-brand={brand}
      data-variant={responsive ? 'responsive' : resolvedVariant}
    >
      {responsive ? (
        <>
          <span className="aether-product-lockup__full"><StaticProductLockup manifest={manifest} variant="full" size={size} /></span>
          <span className="aether-product-lockup__compact"><StaticProductLockup manifest={manifest} variant="compact" size={size} /></span>
          <span className="aether-product-lockup__mark"><StaticProductLockup manifest={manifest} variant="mark" size={size} /></span>
        </>
      ) : <StaticProductLockup manifest={manifest} variant={resolvedVariant} size={size} />}
    </span>
  );
}

export function OlympusLockup(props: Omit<ProductLockupProps, 'brand'>) {
  return <ProductLockup brand="olympus" {...props} />;
}

export function AetherLockup(props: Omit<ProductLockupProps, 'brand'>) {
  return <ProductLockup brand="aether" {...props} />;
}

export function KyberLockup(props: Omit<ProductLockupProps, 'brand'>) {
  return <ProductLockup brand="kyber" {...props} />;
}
