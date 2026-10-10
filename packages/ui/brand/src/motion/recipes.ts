import { MOTION_DURATION, type MotionDuration } from './duration';
import { MOTION_EASING, type MotionEasing } from './easing';

export interface MotionRecipe {
  readonly duration: MotionDuration;
  readonly easing: MotionEasing;
  readonly properties: readonly string[];
  readonly transform: boolean;
}

/** Purposeful interaction recipes. Renderers apply reduced-motion policy separately. */
export const motionRecipes = {
  hover: { duration: 'micro', easing: 'standard', properties: ['background-color', 'border-color', 'color'], transform: false },
  press: { duration: 'micro', easing: 'standard', properties: ['background-color', 'transform'], transform: true },
  focus: { duration: 'micro', easing: 'standard', properties: ['outline-color', 'box-shadow'], transform: false },
  tooltip: { duration: 'micro', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  menu: { duration: 'standard', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  dropdown: { duration: 'standard', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  modal: { duration: 'panel', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  sheet: { duration: 'panel', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  disclosure: { duration: 'standard', easing: 'standard', properties: ['height', 'opacity'], transform: false },
  tab: { duration: 'standard', easing: 'standard', properties: ['opacity', 'color', 'border-color'], transform: false },
  loading: { duration: 'complex', easing: 'linear', properties: ['stroke-dashoffset'], transform: false },
  progress: { duration: 'standard', easing: 'standard', properties: ['width'], transform: false },
  providerConnection: { duration: 'standard', easing: 'standard', properties: ['opacity', 'border-color', 'background-color'], transform: false },
  stateTransition: { duration: 'standard', easing: 'standard', properties: ['opacity', 'color', 'background-color'], transform: false },
  graphSelection: { duration: 'micro', easing: 'standard', properties: ['opacity', 'stroke-width'], transform: false },
  graphExpansion: { duration: 'panel', easing: 'standard', properties: ['opacity', 'transform'], transform: true },
  graphLayout: { duration: 'complex', easing: 'standard', properties: ['transform'], transform: true },
  notification: { duration: 'panel', easing: 'enter', properties: ['opacity', 'transform'], transform: true },
  success: { duration: 'standard', easing: 'standard', properties: ['opacity', 'color'], transform: false },
  remediation: { duration: 'standard', easing: 'standard', properties: ['opacity', 'border-color'], transform: false },
} as const satisfies Readonly<Record<string, MotionRecipe>>;

export function transitionFor(recipe: MotionRecipe): string {
  return recipe.properties
    .map(property => `${property} ${MOTION_DURATION[recipe.duration]}ms ${MOTION_EASING[recipe.easing]}`)
    .join(', ');
}
