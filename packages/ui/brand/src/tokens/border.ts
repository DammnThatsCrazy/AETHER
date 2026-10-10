export const BORDER_WIDTH = {
  none: 0,
  hairline: 1,
  emphasis: 2,
} as const;

export type BorderWidth = keyof typeof BORDER_WIDTH;

export const borderTokens = {
  subtle: { width: 'hairline', color: 'var(--color-border-subtle)' },
  default: { width: 'hairline', color: 'var(--color-border-default)' },
  focus: { width: 'emphasis', color: 'var(--color-border-focus)' },
} as const satisfies Readonly<Record<string, { readonly width: BorderWidth; readonly color: string }>>;
