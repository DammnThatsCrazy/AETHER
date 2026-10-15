import type { Elevation } from './elevation';

/** Keep most surfaces border-led; reserve substantial shadow for floating layers. */
export const SHADOW = {
  none: 'none',
  raised: '0 1px 2px rgb(0 0 0 / 0.18)',
  floating: '0 8px 24px rgb(0 0 0 / 0.22)',
  modal: '0 16px 48px rgb(0 0 0 / 0.30)',
  tooltip: '0 4px 12px rgb(0 0 0 / 0.28)',
} as const;

export type Shadow = keyof typeof SHADOW;

export const shadowByElevation: Readonly<Record<Elevation, Shadow>> = {
  base: 'none',
  raised: 'raised',
  floating: 'floating',
  modal: 'modal',
  tooltip: 'tooltip',
};
