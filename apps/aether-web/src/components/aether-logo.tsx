import { AetherLockup } from '@aether/ui';

interface AetherLogoProps {
  /** Size of the logo icon (height in px). Default: 32 */
  size?: number;
  /** Whether to show the "Aether" wordmark next to the icon. Default: true */
  showWordmark?: boolean;
  className?: string;
}

/** Compatibility entry point; canonical assets and lockup behavior live in @aether/ui. */
export function AetherLogo({ size = 32, showWordmark = true, className }: AetherLogoProps) {
  return <AetherLockup variant={showWordmark ? 'compact' : 'mark'} size={size} className={className} />;
}
