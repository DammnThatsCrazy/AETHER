import { resolveProvider, type ProviderId, type ProviderVisualIdentity } from '@olympus/brand';
import type { CSSProperties, HTMLAttributes, ReactNode } from 'react';

import { cn } from '../utils/cn';

export interface ProviderMarkProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  readonly provider: ProviderId | null | undefined;
  /** A provider mark next to the visible label is redundant. */
  readonly decorative?: boolean;
  readonly label?: string;
  readonly size?: number;
}

function providerMarkStyle(size: number, opticalScale: number): CSSProperties {
  return { width: size, height: size, transform: `scale(${opticalScale})` };
}

function ProviderFallback({ identity, size }: { readonly identity: ProviderVisualIdentity; readonly size: number }) {
  return (
    <span
      className="aether-provider-mark__fallback inline-flex shrink-0 items-center justify-center rounded-md border border-border-subtle bg-surface-sunken font-mono text-[0.55em] font-semibold leading-none text-text-secondary"
      style={{ width: size, height: size }}
    >
      {identity.fallbackInitials}
    </span>
  );
}

/**
 * Safe provider identity renderer. It only renders a third-party image when
 * the registry supplies an approved *local* asset; every current registry
 * entry intentionally uses neutral initials until a review adds one.
 */
export function ProviderMark({ provider, decorative = false, label, size = 24, className, ...props }: ProviderMarkProps) {
  const { identity } = resolveProvider(provider);
  const accessibleLabel = label ?? identity.label;
  const mark = identity.mark;
  const localAsset = mark.kind === 'reviewed-local' && mark.publicPath;

  return (
    <span
      {...props}
      className={cn('aether-provider-mark inline-flex shrink-0', className)}
      {...(decorative ? { 'aria-hidden': true } : { role: 'img', 'aria-label': accessibleLabel })}
      data-provider={identity.id}
      data-provider-mark={localAsset ? 'reviewed-local' : 'fallback'}
    >
      {localAsset ? (
        <img
          src={mark.publicPath}
          alt=""
          aria-hidden="true"
          className="aether-provider-mark__asset block object-contain"
          style={providerMarkStyle(size, mark.opticalScale)}
        />
      ) : <ProviderFallback identity={identity} size={size} />}
    </span>
  );
}

export interface ProviderCardProps extends Omit<HTMLAttributes<HTMLElement>, 'children'> {
  readonly provider: ProviderId | null | undefined;
  readonly detail?: string;
  readonly action?: ReactNode;
  readonly markSize?: number;
}

/** A compact, label-first provider surface suitable for connector lists. */
export function ProviderCard({ provider, detail, action, markSize = 28, className, ...props }: ProviderCardProps) {
  const { identity } = resolveProvider(provider);
  return (
    <article
      {...props}
      className={cn('aether-provider-card flex min-w-0 items-center gap-3 rounded-md border border-border-subtle bg-surface-raised px-3 py-2', className)}
      aria-label={`Provider: ${identity.label}`}
    >
      <ProviderMark provider={provider} decorative size={markSize} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-medium text-text-primary">{identity.label}</span>
        {detail && <span className="block truncate text-xs text-text-secondary">{detail}</span>}
      </span>
      {action && <span className="shrink-0">{action}</span>}
    </article>
  );
}

export interface ProviderSourceChipProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  readonly provider: ProviderId | null | undefined;
  readonly markSize?: number;
}

/** Inline source attribution that never replaces the provider's text label with a logo. */
export function ProviderSourceChip({ provider, markSize = 16, className, ...props }: ProviderSourceChipProps) {
  const { identity } = resolveProvider(provider);
  return (
    <span
      {...props}
      className={cn('aether-provider-source-chip inline-flex min-w-0 items-center gap-1.5 rounded-full border border-border-subtle bg-surface-sunken px-2 py-1 text-xs text-text-secondary', className)}
      aria-label={`Source: ${identity.label}`}
    >
      <ProviderMark provider={provider} decorative size={markSize} />
      <span className="truncate">{identity.label}</span>
    </span>
  );
}
