import type { Elevation, Radius, Shadow } from '../tokens';

export interface SurfaceRecipe {
  readonly background: string;
  readonly border: string;
  readonly radius: Radius;
  readonly elevation: Elevation;
  readonly shadow: Shadow;
  readonly purpose: string;
}

/**
 * Surfaces formalize the existing warm/stone theme. A shadow is an exception
 * for spatial separation, not the default treatment for every card.
 */
export const surfaceRecipes = {
  base: {
    background: 'var(--color-surface-base)', border: 'none', radius: 'none', elevation: 'base', shadow: 'none',
    purpose: 'Application canvas.',
  },
  raised: {
    background: 'var(--color-surface-raised)', border: '1px solid var(--color-border-subtle)', radius: 'md', elevation: 'raised', shadow: 'raised',
    purpose: 'Grouped content that needs a small separation from the canvas.',
  },
  floating: {
    background: 'var(--color-surface-overlay)', border: '1px solid var(--color-border-default)', radius: 'md', elevation: 'floating', shadow: 'floating',
    purpose: 'Menus and floating contextual controls.',
  },
  modal: {
    background: 'var(--color-surface-raised)', border: '1px solid var(--color-border-default)', radius: 'lg', elevation: 'modal', shadow: 'modal',
    purpose: 'Dialog and sheet content.',
  },
  popover: {
    background: 'var(--color-surface-overlay)', border: '1px solid var(--color-border-default)', radius: 'md', elevation: 'floating', shadow: 'floating',
    purpose: 'Popover content.',
  },
  tooltip: {
    background: 'var(--color-surface-overlay)', border: '1px solid var(--color-border-default)', radius: 'sm', elevation: 'tooltip', shadow: 'tooltip',
    purpose: 'Concise contextual help.',
  },
  interactive: {
    background: 'var(--color-surface-raised)', border: '1px solid var(--color-border-subtle)', radius: 'sm', elevation: 'base', shadow: 'none',
    purpose: 'Interactive rows and controls before hover or selection.',
  },
  selected: {
    background: 'color-mix(in srgb, var(--color-accent) 10%, var(--color-surface-raised))', border: '1px solid var(--color-accent)', radius: 'sm', elevation: 'base', shadow: 'none',
    purpose: 'A selected item; retain a text or ARIA selected state in addition to color.',
  },
  premium: {
    background: 'var(--color-surface-raised)', border: '1px solid var(--color-border-default)', radius: 'lg', elevation: 'raised', shadow: 'raised',
    purpose: 'A deliberate featured composition, not a glow or separate theme.',
  },
  warning: {
    background: 'color-mix(in srgb, var(--color-warning) 10%, var(--color-surface-raised))', border: '1px solid color-mix(in srgb, var(--color-warning) 45%, var(--color-border-default))', radius: 'md', elevation: 'base', shadow: 'none',
    purpose: 'Caution context; pair with an explicit severity/status label.',
  },
  critical: {
    background: 'color-mix(in srgb, var(--color-danger) 10%, var(--color-surface-raised))', border: '1px solid color-mix(in srgb, var(--color-danger) 45%, var(--color-border-default))', radius: 'md', elevation: 'base', shadow: 'none',
    purpose: 'Critical context; pair with an explicit severity/status label and remediation.',
  },
  provider: {
    background: 'var(--color-surface-raised)', border: '1px solid var(--color-border-subtle)', radius: 'md', elevation: 'base', shadow: 'none',
    purpose: 'External provider identity within Aether; provider brand never dominates the surface.',
  },
} as const satisfies Readonly<Record<string, SurfaceRecipe>>;

export type Surface = keyof typeof surfaceRecipes;
