export const RESPONSIVE_BREAKPOINT = {
  compact: 480,
  tablet: 720,
  desktop: 980,
  wide: 1180,
} as const;

export const logoSizingRules = {
  navigation: { minVisualSize: 20, maxVisualSize: 32, safeArea: 4 },
  auth: { minVisualSize: 40, maxVisualSize: 48, safeArea: 8 },
  marketing: { minVisualSize: 40, maxVisualSize: 72, safeArea: 12 },
  favicon: { minVisualSize: 16, maxVisualSize: 32, safeArea: 2 },
} as const;

export type ResponsiveBreakpoint = keyof typeof RESPONSIVE_BREAKPOINT;
