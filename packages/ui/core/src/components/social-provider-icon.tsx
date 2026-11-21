import { ProviderMark } from './provider-mark';

export type SocialProvider = 'google' | 'apple' | 'slack' | 'microsoft';

interface SocialProviderIconProps {
  provider: SocialProvider;
  className?: string;
}

export function SocialProviderIcon({ provider, className }: SocialProviderIconProps) {
  // Compatibility adapter: the provider registry presently has no reviewed
  // local logos for these IDs, so ProviderMark intentionally renders initials.
  const mark = <ProviderMark provider={provider} decorative size={16} className={className} />;
  // The Apple mark is black; on the dark auth portal it is inverted, as the
  // website portal does.
  return provider === 'apple' ? <span style={{ display: 'inline-flex', filter: 'invert(1)' }}>{mark}</span> : mark;
}
