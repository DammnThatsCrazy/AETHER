/**
 * Provider identity for the public site. Marks come from the canonical
 * registry (@olympus/brand), which shows neutral initials until a third-party
 * logo passes legal review (docs/brand-system/providers.md). Always keep the
 * provider's name visible next to the mark.
 */
import { resolveProvider } from '@olympus/brand';
import type { CSSProperties } from 'react';

export function ProviderMark({
  provider,
  size = 16,
  className = '',
  style,
}: {
  provider: string;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const { identity } = resolveProvider(provider);
  return (
    <span
      aria-hidden="true"
      data-provider={identity.id}
      className={`inline-flex shrink-0 items-center justify-center font-mono font-semibold leading-none ${className}`}
      style={{ width: size, height: size, fontSize: Math.max(8, Math.round(size * 0.5)), ...style }}
    >
      {identity.fallbackInitials}
    </span>
  );
}
