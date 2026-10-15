import { ELEVATION, SHADOW, shadowByElevation, type Elevation } from '../tokens';

export interface ElevationRecipe {
  readonly level: Elevation;
  readonly zIndex: number;
  readonly shadow: keyof typeof SHADOW;
}

export const elevationRecipes: Readonly<Record<Elevation, ElevationRecipe>> = {
  base: { level: 'base', zIndex: ELEVATION.base, shadow: shadowByElevation.base },
  raised: { level: 'raised', zIndex: ELEVATION.raised, shadow: shadowByElevation.raised },
  floating: { level: 'floating', zIndex: ELEVATION.floating, shadow: shadowByElevation.floating },
  modal: { level: 'modal', zIndex: ELEVATION.modal, shadow: shadowByElevation.modal },
  tooltip: { level: 'tooltip', zIndex: ELEVATION.tooltip, shadow: shadowByElevation.tooltip },
};
