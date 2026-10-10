/**
 * Shared chrome for the Kyber security console.
 *
 * Every page under `/security/*` renders four states honestly:
 * loading, empty, error and forbidden. "Forbidden" is a first-class state —
 * a 403 from the backend is the authoritative answer and is shown as such,
 * never swallowed into a blank table.
 */

import type { ReactNode } from 'react';
import { Card, CardContent, EmptyState, ErrorState, LoadingState, Badge } from '@aether/ui';
import { KyberSessionBanners } from '@kyber/features/auth';

interface SecurityPageShellProps {
  readonly title: string;
  readonly description: string;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
}

export function SecurityPageShell({
  title,
  description,
  actions,
  children,
}: SecurityPageShellProps) {
  return (
    <div className="flex flex-col">
      <KyberSessionBanners />
      <div className="p-6 max-w-6xl space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-bold font-mono text-text-primary">{title}</h1>
            <p className="text-xs text-text-muted mt-0.5 max-w-2xl">{description}</p>
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
        {children}
      </div>
    </div>
  );
}

interface AsyncSectionProps {
  readonly isLoading: boolean;
  readonly error: string | null;
  readonly isForbidden?: boolean | undefined;
  readonly isEmpty: boolean;
  readonly emptyTitle: string;
  readonly emptyDescription?: string | undefined;
  readonly onRetry?: (() => void) | undefined;
  readonly children: ReactNode;
}

export function AsyncSection({
  isLoading,
  error,
  isForbidden,
  isEmpty,
  emptyTitle,
  emptyDescription,
  onRetry,
  children,
}: AsyncSectionProps) {
  if (isForbidden === true) {
    return (
      <div data-testid="section-forbidden">
        <EmptyState
          icon="⛔"
          title="Not permitted"
          description="The backend refused this read for your current session. Ask an operator with the right role template, or raise your session authority."
        />
      </div>
    );
  }
  if (error !== null) {
    return (
      <div data-testid="section-error">
        <ErrorState message={error} {...(onRetry ? { onRetry } : {})} />
      </div>
    );
  }
  if (isLoading) {
    return (
      <div data-testid="section-loading">
        <LoadingState lines={4} />
      </div>
    );
  }
  if (isEmpty) {
    return (
      <div data-testid="section-empty">
        <EmptyState title={emptyTitle} {...(emptyDescription ? { description: emptyDescription } : {})} />
      </div>
    );
  }
  return <>{children}</>;
}

export function SecurityCard({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <Card>
      <CardContent className="space-y-3 pt-4">
        <div className="text-xs font-mono uppercase tracking-wide text-text-secondary">{title}</div>
        {children}
      </CardContent>
    </Card>
  );
}

/** Advisory reminder rendered on every mutation-bearing security page. */
export function AdvisoryNote() {
  return (
    <p className="text-[11px] text-text-muted">
      <Badge variant="default" size="sm">advisory</Badge>{' '}
      Controls hidden here are a convenience only — the Kyber backend re-checks
      every capability, action class and disclosure level on its own.
    </p>
  );
}

export function fieldOrDash(value: string | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : value;
}
