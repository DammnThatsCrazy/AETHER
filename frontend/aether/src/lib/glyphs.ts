/** ASCII glyph constants for GlyphIcon usage throughout the app. */
export const GLYPHS = {
  // Navigation
  me:        '[~]',
  settings:  '[:]',
  billing:   '[$]',
  users:     '[u]',
  graph:     '[g]',
  campaigns: '[c]',
  // Actions
  back:    '<',
  copy:    '[cp]',
  key:     '[k]',
  warning: '[!]',
  check:   '[✓]',
  close:   '[x]',
  add:     '[+]',
  minus:   '[-]',
  arrow:   '[>]',
  signout: '[<-]',
  // Status
  dot:     '[·]',
  sun:     '[sun]',
  moon:    '[moon]',
  // SSO provider fallback aria labels (visual is SocialProviderIcon SVG)
  google:    '[G]',
  apple:     '[A]',
  slack:     '[S]',
  microsoft: '[M]',
} as const;

export type GlyphKey = keyof typeof GLYPHS;
