/** A deliberate spacing rhythm for brand, lockup, and shared-component composition. */
export const BRAND_SPACE = {
  0: 0,
  1: 4,
  2: 8,
  3: 12,
  4: 16,
  5: 20,
  6: 24,
  8: 32,
  10: 40,
  12: 48,
  16: 64,
} as const;

export type BrandSpace = keyof typeof BRAND_SPACE;

export const brandSpacingGuidance = {
  iconLabelGap: BRAND_SPACE[2],
  compactRowGap: BRAND_SPACE[2],
  standardRowGap: BRAND_SPACE[3],
  cardPadding: BRAND_SPACE[4],
  modalPadding: BRAND_SPACE[6],
  lockupClearSpace: BRAND_SPACE[2],
} as const;
