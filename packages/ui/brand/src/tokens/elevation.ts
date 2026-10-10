/** Elevation names describe layer intent; shadows are defined separately. */
export const ELEVATION = {
  base: 0,
  raised: 1,
  floating: 2,
  modal: 3,
  tooltip: 4,
} as const;

export type Elevation = keyof typeof ELEVATION;
