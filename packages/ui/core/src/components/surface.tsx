import {
  ELEVATION,
  RADIUS,
  SHADOW,
  surfaceRecipes,
  type Surface as SurfaceName,
} from '@olympus/brand';
import type { CSSProperties, ElementType, HTMLAttributes, ReactNode } from 'react';

import { cn } from '../utils/cn';

export interface SurfaceProps extends HTMLAttributes<HTMLElement> {
  readonly as?: ElementType;
  readonly recipe?: SurfaceName;
  readonly children?: ReactNode;
}

function recipeStyle(recipeName: SurfaceName): CSSProperties {
  const recipe = surfaceRecipes[recipeName];
  return {
    background: recipe.background,
    border: recipe.border,
    borderRadius: RADIUS[recipe.radius],
    boxShadow: SHADOW[recipe.shadow],
    zIndex: ELEVATION[recipe.elevation],
  };
}

/**
 * A token-backed surface. Recipes are data-owned by `@olympus/brand`, while
 * this component is intentionally only their React/CSS adaptation layer.
 */
export function Surface({ as: Component = 'div', recipe = 'base', className, style, children, ...props }: SurfaceProps) {
  return (
    <Component
      {...props}
      className={cn('aether-surface', `aether-surface--${recipe}`, className)}
      style={{ ...recipeStyle(recipe), ...style }}
      data-surface={recipe}
    >
      {children}
    </Component>
  );
}

export function ElevatedSurface({ recipe = 'raised', ...props }: Omit<SurfaceProps, 'recipe'> & { readonly recipe?: Extract<SurfaceName, 'raised' | 'floating' | 'modal' | 'popover' | 'tooltip'> }) {
  return <Surface {...props} recipe={recipe} />;
}

/** Featured content uses the constrained premium recipe, never an ad-hoc glow or competing theme. */
export function PremiumSurface(props: Omit<SurfaceProps, 'recipe'>) {
  return <Surface {...props} recipe="premium" />;
}
