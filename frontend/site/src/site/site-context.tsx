import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { querySelectedSite, resolveSite, siteHref, siteOrigins, type SiteId, type SiteOrigins } from './site';

interface SiteValue {
  site: SiteId;
  origins: SiteOrigins;
  /** Link to `path` on `target`, relative when it is the current site. */
  href: (target: SiteId, path: string) => string;
}

const SiteContext = createContext<SiteValue | null>(null);

export function SiteProvider({ site, children }: { site?: SiteId; children: ReactNode }) {
  const value = useMemo<SiteValue>(() => {
    const resolved =
      site ??
      (typeof window === 'undefined'
        ? 'aether'
        : resolveSite(window.location.hostname, window.location.search));
    const origins = siteOrigins();
    // Keep `?site=` on same-site links when it chose the site (preview hosts).
    const keepSelector = !site && typeof window !== 'undefined' && querySelectedSite(window.location.search) === resolved;
    return { site: resolved, origins, href: (target, path) => siteHref(resolved, target, path, origins, keepSelector) };
  }, [site]);
  return <SiteContext.Provider value={value}>{children}</SiteContext.Provider>;
}

export function useSite(): SiteValue {
  const value = useContext(SiteContext);
  if (!value) throw new Error('useSite must be used inside <SiteProvider>');
  return value;
}
