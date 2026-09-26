import { useRoutes } from 'react-router-dom';
import { SiteProvider, useSite } from '@site/site/site-context';
import type { SiteId } from '@site/site/site';
import { ROUTES } from './routes';

function SiteRoutes() {
  const { site } = useSite();
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
