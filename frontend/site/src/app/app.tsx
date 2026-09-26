import { useEffect } from 'react';
import { useRoutes } from 'react-router-dom';
import { SiteProvider, useSite } from '@site/site/site-context';
import type { SiteId } from '@site/site/site';
import { ROUTES } from './routes';
import { BRAND_FAVICONS } from '@site/components/brand-mark';

/** Tab icon per site; index.html ships the Aether one. */
export const FAVICONS: Record<SiteId, string> = BRAND_FAVICONS;

function SiteRoutes() {
  const { site } = useSite();
  useEffect(() => {
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (icon) icon.href = FAVICONS[site];
  }, [site]);
  return useRoutes(ROUTES[site]);
}

/** Router-agnostic root: callers supply the router (browser or memory). */
export function App({ site }: { site?: SiteId }) {
  return (
    <SiteProvider site={site}>
      <SiteRoutes />
    </SiteProvider>
  );
}
