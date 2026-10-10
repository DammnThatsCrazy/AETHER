/**
 * Accent colors for components whose accent is chosen at runtime (tabs,
 * relationship types, research cards). Values are the handoff token table;
 * design files that hard-code a nearby hex map to these (handoff README,
 * "Fidelity"). Static styling stays in Tailwind classes.
 */
export type Accent = 'cobalt' | 'sage' | 'ochre' | 'ember' | 'steel' | 'solar';

export interface AccentColors {
  /** Border, glyph and fill color. */
  base: string;
  /** Text on light surfaces and selected (filled) controls. */
  ink: string;
  /** base as "r, g, b" for tints at any opacity. */
  rgb: string;
  /** Opacity of the accent's soft fill (chips, tinted cards, icon tiles). */
  soft: number;
}

export const ACCENTS: Record<Accent, AccentColors> = {
  cobalt: { base: '#3a6896', ink: '#2d5373', rgb: '58, 104, 150', soft: 0.12 },
  sage: { base: '#6b9a7c', ink: '#4f8466', rgb: '107, 154, 124', soft: 0.15 },
  ochre: { base: '#c9975a', ink: '#8a6433', rgb: '201, 151, 90', soft: 0.16 },
  ember: { base: '#b5564a', ink: '#9c4439', rgb: '181, 86, 74', soft: 0.12 },
  steel: { base: '#5a85a8', ink: '#3f6a8c', rgb: '90, 133, 168', soft: 0.14 },
  // Not in the token table; used by the designs for economic/value accents.
  solar: { base: '#a88a5a', ink: '#7d6538', rgb: '168, 138, 90', soft: 0.16 },
};

/** The accent's base color at `alpha` opacity (tints, soft borders). */
export function tint(accent: Accent, alpha: number): string {
  return `rgba(${ACCENTS[accent].rgb}, ${alpha})`;
}

/** The accent's soft fill at the opacity the designs use for it. */
export function soft(accent: Accent): string {
  return tint(accent, ACCENTS[accent].soft);
}
