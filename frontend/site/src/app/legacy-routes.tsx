import { useEffect } from 'react';
import { Navigate, type RouteObject } from 'react-router-dom';
import { siteHref } from '@site/site/site';
import { leaveFor } from './leave';

/**
 * URLs the previous Aether marketing app (frontend/aether-marketing) served,
 * mapped to where their content lives on the unified site. Bookmarks and
 * indexed links keep working after the Aether host switches apps. A path
 * with `olympus: true` moved to the Olympus Labs site.
 */
export const LEGACY_AETHER_REDIRECTS: ReadonlyArray<{ from: string; to: string; olympus?: boolean }> = [
  { from: '/platform/*', to: '/how-it-works' },
  { from: '/platform', to: '/how-it-works' },
  { from: '/product', to: '/how-it-works' },
  { from: '/architecture', to: '/how-it-works' },
  { from: '/profile-360', to: '/how-it-works' },
  { from: '/identity-resolution', to: '/how-it-works' },
  { from: '/intelligence-graph', to: '/how-it-works' },
  { from: '/campaign-attribution', to: '/how-it-works' },
  { from: '/solutions/*', to: '/' },
  { from: '/solutions', to: '/' },
  { from: '/integrations', to: '/connections' },
  { from: '/governance', to: '/security' },
  { from: '/start-pilot', to: '/contact?type=pilot' },
  { from: '/proof-partner', to: '/contact?type=proof' },
  { from: '/proof/*', to: '/contact?type=proof' },
  { from: '/faq', to: '/docs/faq' },
  { from: '/resources', to: '/docs' },
  { from: '/developers', to: '/docs/start-here' },
  { from: '/developers/*', to: '/docs' },
  { from: '/developers/start-here', to: '/docs/start-here' },
  { from: '/developers/api-reference', to: '/docs/api-conventions' },
  { from: '/developers/changelog', to: '/docs/changelog' },
  { from: '/developers/events', to: '/docs/events' },
  { from: '/developers/integrations', to: '/docs/connector-catalog' },
  { from: '/developers/troubleshooting', to: '/docs/troubleshooting' },
  { from: '/developers/quickstart/web', to: '/docs/quickstart-web' },
  { from: '/developers/quickstart/electron', to: '/docs/quickstart-web' },
  { from: '/developers/quickstart/ios', to: '/docs/quickstart-ios' },
  { from: '/developers/quickstart/android', to: '/docs/quickstart-android' },
  { from: '/developers/quickstart/react-native', to: '/docs/quickstart-react-native' },
  { from: '/developers/quickstart/backend', to: '/docs/quickstart-backend' },
  { from: '/developers/quickstart/rest', to: '/docs/ingestion-api' },
  { from: '/developers/sdk/web', to: '/docs/sdk-web' },
  { from: '/developers/sdk/ios', to: '/docs/sdk-ios' },
  { from: '/developers/sdk/android', to: '/docs/sdk-android' },
  { from: '/developers/sdk/react-native', to: '/docs/sdk-react-native' },
  { from: '/company', to: '/company', olympus: true },
  { from: '/stories', to: '/stories', olympus: true },
  { from: '/perspectives', to: '/research', olympus: true },
];

function OlympusRedirect({ path }: { path: string }) {
  const href = siteHref('aether', 'olympus', path);
  useEffect(() => leaveFor(href), [href]);
  return (
    <p className="p-6">
      This page moved to <a href={href}>Olympus Labs</a>.
    </p>
  );
}

export const LEGACY_AETHER_ROUTES: RouteObject[] = LEGACY_AETHER_REDIRECTS.map(({ from, to, olympus }) => ({
  path: from,
  element: olympus ? <OlympusRedirect path={to} /> : <Navigate to={to} replace />,
}));
