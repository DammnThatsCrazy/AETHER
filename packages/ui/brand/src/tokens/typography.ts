export type TypographyRole = 'eyebrow' | 'caption' | 'body' | 'bodyStrong' | 'label' | 'headingSm' | 'headingMd' | 'headingLg' | 'display' | 'data';

export interface TypographyToken {
  readonly family: 'sans' | 'mono';
  readonly fontSize: number;
  readonly lineHeight: number;
  readonly fontWeight: 400 | 500 | 600 | 700;
  readonly letterSpacing?: string;
}

/** Geist is the product sans; Geist Mono is reserved for data, IDs, and code. */
export const FONT_FAMILY = {
  sans: 'var(--font-family-sans)',
  mono: 'var(--font-family-mono)',
} as const;

export const TYPOGRAPHY: Readonly<Record<TypographyRole, TypographyToken>> = {
  eyebrow: { family: 'mono', fontSize: 11, lineHeight: 16, fontWeight: 500, letterSpacing: '0.08em' },
  caption: { family: 'sans', fontSize: 12, lineHeight: 16, fontWeight: 400 },
  body: { family: 'sans', fontSize: 14, lineHeight: 20, fontWeight: 400 },
  bodyStrong: { family: 'sans', fontSize: 14, lineHeight: 20, fontWeight: 600 },
  label: { family: 'sans', fontSize: 14, lineHeight: 20, fontWeight: 500 },
  headingSm: { family: 'sans', fontSize: 16, lineHeight: 24, fontWeight: 600, letterSpacing: '-0.01em' },
  headingMd: { family: 'sans', fontSize: 20, lineHeight: 28, fontWeight: 600, letterSpacing: '-0.02em' },
  headingLg: { family: 'sans', fontSize: 24, lineHeight: 32, fontWeight: 600, letterSpacing: '-0.025em' },
  display: { family: 'sans', fontSize: 32, lineHeight: 40, fontWeight: 600, letterSpacing: '-0.03em' },
  data: { family: 'mono', fontSize: 12, lineHeight: 16, fontWeight: 500 },
};
