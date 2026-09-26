import type { RouteObject } from 'react-router-dom';
import type { SiteId } from '@site/site/site';
import { NotFoundPage } from '@site/pages/not-found-page';

/**
 * Route tables per site (handoff README, "Route map"). Pages are added as each
 * phase lands; until then a route falls through to the 404 page.
 */
export const ROUTES: Record<SiteId, RouteObject[]> = {
  olympus: [{ path: '*', element: <NotFoundPage /> }],
  aether: [{ path: '*', element: <NotFoundPage /> }],
};
