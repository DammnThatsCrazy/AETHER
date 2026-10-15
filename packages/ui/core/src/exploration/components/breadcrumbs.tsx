import type { Crumb } from '../chrome-model';

export interface ExplorationBreadcrumbsProps {
  readonly crumbs: readonly Crumb[];
  readonly onNavigate?: ((index: number, crumb: Crumb) => void) | undefined;
}

/** Context-preserving breadcrumb trail (surface → anchors → focus). */
export function ExplorationBreadcrumbs({ crumbs, onNavigate }: ExplorationBreadcrumbsProps) {
  if (crumbs.length === 0) return null;
  return (
    <nav
      className="flex flex-wrap items-center gap-1 text-xs"
      aria-label="Exploration breadcrumbs"
      data-testid="breadcrumbs"
    >
      {crumbs.map((crumb, index) => {
        const isLast = index === crumbs.length - 1;
        return (
          <span key={`${crumb.label}-${index}`} className="flex items-center gap-1">
            {index > 0 && <span className="text-text-muted">/</span>}
            {onNavigate && !isLast ? (
              <button
                type="button"
                onClick={() => onNavigate(index, crumb)}
                className="text-accent hover:underline"
              >
                {crumb.label}
              </button>
            ) : (
              <span className={isLast ? 'text-text-primary' : 'text-text-secondary'}>{crumb.label}</span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
