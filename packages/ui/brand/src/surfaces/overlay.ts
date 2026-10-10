export const overlayRecipes = {
  scrim: {
    background: 'rgb(13 13 16 / 0.72)',
    backdropFilter: 'blur(2px)',
    purpose: 'Modal and drawer isolation only.',
  },
  quiet: {
    background: 'color-mix(in srgb, var(--color-surface-sunken) 60%, transparent)',
    backdropFilter: 'none',
    purpose: 'Non-blocking contextual overlay.',
  },
  tooltip: {
    background: 'var(--color-surface-overlay)',
    backdropFilter: 'none',
    purpose: 'Short contextual hint.',
  },
} as const;

export type Overlay = keyof typeof overlayRecipes;
