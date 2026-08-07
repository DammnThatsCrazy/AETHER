/**
 * Aether mobile design tokens — typed dark theme.
 *
 * Values mirror the app-shell aesthetic (the aether-mobile and kyber-mobile
 * `App.tsx` shells: `#0b0d12` background, `#f5f7fa` text, `#8b93a7` muted) and the
 * desktop brand accent (`frontend/shared/src/styles/tokens.css` `--color-accent:
 * #3a6896`).
 *
 * Pure TypeScript with no react-native import, so the tokens are unit-testable in
 * plain Node and importable from non-UI logic.
 */

export const theme = {
  colors: {
    /** App shell background. */
    background: '#0b0d12',
    /** Elevated card surface. */
    surface: '#161a23',
    /** Hairline separators and card borders. */
    border: '#232836',
    /** Primary text. */
    text: '#f5f7fa',
    /** Secondary / muted text. */
    muted: '#8b93a7',
    /** Brand accent (desktop `--color-accent`). */
    accent: '#3a6896',
    /** Accent on hover / active states (light-on-dark variant). */
    accentHover: '#5a85a8',
    /** Text/icon rendered on top of the accent fill. */
    onAccent: '#ffffff',
    success: '#4d9f6c',
    warning: '#d29922',
    danger: '#e5484d',
  },
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    lg: 16,
    xl: 24,
    xxl: 32,
  },
  radii: {
    sm: 6,
    md: 10,
    lg: 14,
    pill: 999,
  },
  type: {
    display: { fontSize: 32, fontWeight: '700', lineHeight: 38, color: '#f5f7fa' },
    title: { fontSize: 28, fontWeight: '700', lineHeight: 34, color: '#f5f7fa' },
    subtitle: { fontSize: 15, fontWeight: '400', lineHeight: 21, color: '#8b93a7' },
    body: { fontSize: 15, fontWeight: '400', lineHeight: 21, color: '#f5f7fa' },
    label: { fontSize: 13, fontWeight: '600', lineHeight: 18, color: '#8b93a7' },
    caption: { fontSize: 12, fontWeight: '400', lineHeight: 16, color: '#8b93a7' },
  },
} as const;

/** The static design-token shape (deep-readonly literals). */
export type Theme = typeof theme;

/**
 * Returns the current theme. The kit ships a single static token set; apps that need
 * runtime theming (brand variants) can wrap this in a Context in M3/M4 without
 * changing the typed shape.
 */
export function useTheme(): Theme {
  return theme;
}
