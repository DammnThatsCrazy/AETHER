import { ProviderMark } from './provider-mark';

export type SocialProvider = 'google' | 'apple' | 'slack' | 'microsoft';

interface SocialProviderIconProps {
  provider: SocialProvider;
  className?: string;
}

export function SocialProviderIcon({ provider, className }: SocialProviderIconProps) {
  // Compatibility adapter: the provider registry presently has no reviewed
  // local logos for these IDs, so ProviderMark intentionally renders initials.
  return <ProviderMark provider={provider} decorative size={16} className={className} />;
}
