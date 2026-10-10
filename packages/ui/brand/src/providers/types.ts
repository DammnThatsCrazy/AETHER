import type { ProviderCategory } from './categories';

/**
 * `ProviderId` deliberately permits a server-delivered identifier that has not
 * been registered yet. Use `resolveProvider` to turn it into a safe fallback
 * presentation rather than treating an unknown provider as a known brand.
 */
export type ProviderId = string & {};

export interface ProviderAsset {
  readonly kind: 'reviewed-local' | 'fallback';
  readonly sourcePath?: string;
  readonly publicPath?: string;
  readonly opticalScale: number;
  readonly fallbackInitials: string;
  /** Why a fallback is used. It is safe to expose in internal diagnostics. */
  readonly reason?: string;
}

export interface ProviderVisualIdentity {
  readonly id: ProviderId;
  readonly label: string;
  readonly category: ProviderCategory;
  /** Never a remote URL. A missing approved mark is represented as a fallback. */
  readonly mark: ProviderAsset;
  readonly monochromeMark?: ProviderAsset;
  readonly preferredBackground: 'light' | 'dark' | 'either';
  readonly brandColor?: string;
  readonly fallbackInitials: string;
  readonly attributionRequired: boolean;
  readonly trademarkGuidance: string;
  readonly aliases: readonly string[];
}

export interface ResolvedProviderIdentity {
  readonly identity: ProviderVisualIdentity;
  readonly known: boolean;
  readonly requestedId: string | null;
}
