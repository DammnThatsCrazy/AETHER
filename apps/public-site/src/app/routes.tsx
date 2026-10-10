import { Navigate, type RouteObject } from 'react-router-dom';
import type { SiteId } from '@site/site/site';
import { AetherHomePage } from '@site/pages/aether/aether-home-page';
import { AetherConnectPage } from '@site/pages/aether/aether-connect';
import { AetherPlatformPage } from '@site/pages/aether/aether-platform-page';
import { AetherFeaturePage } from '@site/pages/aether/aether-feature-page';
import { AetherLensesPage } from '@site/pages/aether/aether-lenses-page';
import { AetherAgentsPage } from '@site/pages/aether/aether-agents-page';
import { AetherApplicationsPage } from '@site/pages/aether/aether-applications-page';
import { AetherCustomerIntelligencePage } from '@site/pages/aether/aether-customer-intelligence-page';
import { AetherDetailPage } from '@site/pages/aether/aether-detail-page';
import { AetherTrustPage } from '@site/pages/aether/aether-trust-page';
import { AetherProcurementPage } from '@site/pages/aether/aether-procurement-page';
import { AetherSecurityPage } from '@site/pages/aether/aether-security-page';
import { AetherPricingPage } from '@site/pages/aether/aether-pricing-page';
import { AetherHowItWorksPage } from '@site/pages/aether/aether-how-it-works-page';
import { ContactPage } from '@site/pages/contact-page';
import { DocsPage } from '@site/pages/docs/docs-page';
import { GlossaryPage } from '@site/pages/docs/glossary-page';
import { SymbolKeyPage } from '@site/pages/docs/symbol-key-page';
import { StatusPage } from '@site/pages/status-page';
import { LegalPage } from '@site/pages/legal-page';
import { NotFoundPage } from '@site/pages/not-found-page';
import { OlympusCompanyPage } from '@site/pages/olympus/olympus-company-page';
import { OlympusHomePage } from '@site/pages/olympus/olympus-home-page';
import { OlympusPrinciplesPage } from '@site/pages/olympus/olympus-principles-page';
import { OlympusResearchPage } from '@site/pages/olympus/olympus-research-page';
import { OlympusStoriesPage } from '@site/pages/olympus/olympus-stories-page';
import { OlympusTechnologyPage } from '@site/pages/olympus/olympus-technology-page';
import { OlympusApplicationsPage } from '@site/pages/olympus/olympus-applications-page';
import { LEGACY_AETHER_ROUTES } from './legacy-routes';

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
    { path: '/technology', element: <OlympusTechnologyPage /> },
    { path: '/applications', element: <OlympusApplicationsPage /> },
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
    { path: '/platform', element: <AetherPlatformPage /> },
    { path: '/platform/lenses', element: <AetherLensesPage /> },
    { path: '/platform/agents', element: <AetherAgentsPage /> },
    { path: '/platform/:feature', element: <AetherFeaturePage /> },
    { path: '/applications', element: <AetherApplicationsPage /> },
    { path: '/applications/customer-intelligence', element: <AetherCustomerIntelligencePage /> },
    { path: '/connect', element: <AetherConnectPage /> },
    { path: '/connect/:topic', element: <AetherDetailPage /> },
    { path: '/trust', element: <AetherTrustPage /> },
    { path: '/trust/:topic', element: <AetherDetailPage /> },
    { path: '/pricing', element: <AetherPricingPage /> },
    { path: '/security', element: <AetherSecurityPage /> },
    { path: '/procurement', element: <AetherProcurementPage /> },
    { path: '/docs', element: <DocsPage /> },
    { path: '/docs/glossary', element: <GlossaryPage /> },
    { path: '/docs/symbol-key', element: <SymbolKeyPage /> },
    { path: '/docs/section/:section', element: <DocsPage /> },
    { path: '/docs/:page', element: <DocsPage /> },
    { path: '/status', element: <StatusPage /> },
    ...SHARED,
    ...LEGACY_AETHER_ROUTES,
    { path: '*', element: <NotFoundPage /> },
  ],
};
