/**
 * Olympus and Aether marks. The geometry is owned by @olympus/brand and served
 * from its marks directory (the Vite publicDir); pages never name the files.
 */
import { aetherAssets, olympusAssets } from '@olympus/brand';

const MARKS = {
  olympus: olympusAssets.arch.publicPath,
  aether: aetherAssets.layers.publicPath,
} as const;

export type BrandMarkId = keyof typeof MARKS;

/** Tab icon per site. */
export const BRAND_FAVICONS = {
  olympus: olympusAssets.arch.publicPath,
  aether: aetherAssets.favicon.publicPath,
} as const;

/** Served URL of a brand mark, for design markup that sizes its own <img>. */
export function markSrc(brand: BrandMarkId): string {
  return MARKS[brand];
}

export function BrandMark({ brand, className }: { brand: BrandMarkId; className?: string }) {
  return <img src={MARKS[brand]} alt="" className={className} />;
}
