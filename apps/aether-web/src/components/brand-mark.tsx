import { ProviderMark, cn } from '@aether/ui';

/**
 * SDK platform and design tokens that are not provider families, mapped onto
 * the provider registry IDs that represent them. Anything unmapped is passed
 * through: the registry normalises provider families and display names.
 */
const TOKEN_ALIASES: Readonly<Record<string, string>> = {
  ios: 'apple',
  csv: 'aether',
};

/**
 * A provider or SDK mark on a white chip, rendered through the canonical
 * `ProviderMark` (packages/ui/core): reviewed local marks from the brand
 * registry (packages/ui/brand/src/providers/registry.ts) show the provider's
 * logo; anything without a reviewed mark shows the registry's neutral
 * initials. No third-party artwork is bundled outside that registry.
 */
export function BrandMark({
  token,
  label,
  size = 30,
  markSize,
  shape = 'rounded',
  className,
}: {
  /** Provider family, display name or SDK platform token. */
  readonly token: string;
  /** Accessible label override (the mark is decorative when omitted). */
  readonly label?: string;
  /** Outer chip size in px. */
  readonly size?: number;
  /** Mark size inside the chip in px. */
  readonly markSize?: number;
  readonly shape?: 'round' | 'rounded' | 'square';
  readonly className?: string;
}) {
  const provider = TOKEN_ALIASES[token.trim().toLowerCase()] ?? token;
  const inner = markSize ?? Math.round(size * 0.58);
  const radius = shape === 'round' ? '50%' : shape === 'square' ? 4 : Math.round(size * 0.3);
  return (
    <span
      className={cn('ae-mark-chip', className)}
      style={{ inlineSize: size, blockSize: size, borderRadius: radius }}
      data-brand-token={token}
    >
      <ProviderMark provider={provider} decorative size={inner} {...(label ? { label } : {})} />
    </span>
  );
}
