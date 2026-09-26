import { Navigate, type RouteObject } from 'react-router-dom';
import type { SiteId } from '@site/site/site';
import { AetherHomePage } from '@site/pages/aether/aether-home-page';
import { AetherConnectionsPage } from '@site/pages/aether/aether-connections-page';
import { AetherProcurementPage } from '@site/pages/aether/aether-procurement-page';
import { AetherSecurityPage } from '@site/pages/aether/aether-security-page';
import { AetherPricingPage } from '@site/pages/aether/aether-pricing-page';
import { AetherHowItWorksPage } from '@site/pages/aether/aether-how-it-works-page';
import { ContactPage } from '@site/pages/contact-page';
import { DocsPage } from '@site/pages/docs/docs-page';
import { StatusPage } from '@site/pages/status-page';
import { LegalPage } from '@site/pages/legal-page';
import { NotFoundPage } from '@site/pages/not-found-page';
import { OlympusCompanyPage } from '@site/pages/olympus/olympus-company-page';
import { OlympusHomePage } from '@site/pages/olympus/olympus-home-page';
import { OlympusPrinciplesPage } from '@site/pages/olympus/olympus-principles-page';
import { OlympusResearchPage } from '@site/pages/olympus/olympus-research-page';
import { OlympusStoriesPage } from '@site/pages/olympus/olympus-stories-page';

/** Pages both sites serve (handoff route map). */
const SHARED: RouteObject[] = [
  { path: '/contact', element: <ContactPage /> },
  { path: '/legal', element: <Navigate to="/legal/privacy" replace /> },
  { path: '/legal/:doc', element: <LegalPage /> },
];

/**
 * Route tables per site (handoff README, "Route map"). Pages are added as each
 * phase lands; until then a route falls through to the 404 page.
 */
export const ROUTES: Record<SiteId, RouteObject[]> = {
  olympus: [
    { path: '/', element: <OlympusHomePage /> },
    { path: '/company', element: <OlympusCompanyPage /> },
    { path: '/principles', element: <OlympusPrinciplesPage /> },
    { path: '/research', element: <OlympusResearchPage /> },
    { path: '/stories', element: <OlympusStoriesPage /> },
    ...SHARED,
    { path: '*', element: <NotFoundPage /> },
  ],
  aether: [
    { path: '/', element: <AetherHomePage /> },
    { path: '/how-it-works', element: <AetherHowItWorksPage /> },
    { path: '/connections', element: <AetherConnectionsPage /> },
    { path: '/pricing', element: <AetherPricingPage /> },
    { path: '/security', element: <AetherSecurityPage /> },
    { path: '/procurement', element: <AetherProcurementPage /> },
    { path: '/docs', element: <DocsPage /> },
    { path: '/docs/:page', element: <DocsPage /> },
    { path: '/status', element: <StatusPage /> },
    ...SHARED,
    { path: '*', element: <NotFoundPage /> },
  ],
};
