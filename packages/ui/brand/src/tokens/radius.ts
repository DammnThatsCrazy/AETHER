export const RADIUS = {
  none: 0,
  xs: 2,
  sm: 4,
  md: 6,
  lg: 8,
  xl: 12,
  pill: 9999,
} as const;

export type Radius = keyof typeof RADIUS;

export const radiusUsage = {
  indicator: 'pill',
  control: 'sm',
  card: 'md',
  modal: 'lg',
  heroSurface: 'xl',
} as const satisfies Readonly<Record<string, Radius>>;
