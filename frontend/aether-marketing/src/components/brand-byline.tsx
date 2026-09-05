import { AetherLockup } from '@aether/ui';
import { OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';

/**
 * Aether identity with its Olympus Labs attribution, always in the correct
 * hierarchy: Aether is the product, Olympus Labs is the owner.
 *
 * The header composes these as siblings — a home link carrying the Aether
 * lockup, followed by a separate quiet Olympus Labs attribution link — so no
 * anchor is ever nested inside another anchor.
 */

/** The Aether product mark; pair with an accessible label when used as a link. */
export function AetherMark({ size = 26 }: { readonly size?: number }) {
  return <AetherLockup variant="compact" label="Aether" size={size} />;
}

/** Small "by Olympus Labs" attribution line, linked to the corporate site. */
export function OlympusAttribution({ className }: { readonly className?: string }) {
  return (
    <span className={`text-xs text-text-secondary ${className ?? ''}`}>
      by{' '}
      <a href={OLYMPUS_SITE_URL} className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
        Olympus Labs
      </a>
    </span>
  );
}
