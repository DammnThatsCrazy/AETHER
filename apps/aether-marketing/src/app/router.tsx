import type { ComponentType } from 'react';
import type { ReactNode } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { AetherShell } from '@aether-marketing/components/aether-shell';
import { AuthLayout } from '@aether-marketing/components/auth-layout';
import { SECTIONS } from '@aether-marketing/content/sections';
import { CapabilityPage } from '@aether-marketing/pages/capability-page';
import { DevelopersPage } from '@aether-marketing/pages/developers-page';
import { HomePage } from '@aether-marketing/pages/home-page';
import { IntegrationsPage } from '@aether-marketing/pages/integrations-page';
import { NotFoundPage } from '@aether-marketing/pages/not-found';
import { PlatformPage } from '@aether-marketing/pages/platform-page';
import { PricingPage } from '@aether-marketing/pages/pricing-page';
import { SectionPage } from '@aether-marketing/pages/section-page';
import { SolutionPage } from '@aether-marketing/pages/solution-page';
import { SolutionsPage } from '@aether-marketing/pages/solutions-page';
import { ContactPage } from '@aether-marketing/pages/contact-page';
import { StartPilotPage } from '@aether-marketing/pages/start-pilot-page';
import { ForgotPasswordPage } from '@aether-marketing/pages/auth/forgot-password-page';
import { LoginPage } from '@aether-marketing/pages/auth/login-page';
import { SignupPage } from '@aether-marketing/pages/auth/signup-page';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';

/**
 * Sections with a dedicated interactive/landing page. Every other top-level
 * section slug falls back to the generic SectionPage.
 */
const DEDICATED_PAGES: Readonly<Record<string, ComponentType>> = {
  '/platform': PlatformPage,
  '/solutions': SolutionsPage,
  '/integrations': IntegrationsPage,
  '/developers': DevelopersPage,
  '/pricing': PricingPage,
};

function LaunchPackContent({ page }: { readonly page: NonNullable<ReturnType<typeof getLaunchPackPage>> }) {
  usePageMeta({ title: page.seoTitle, description: page.seoDescription });
  return <LaunchPackPage page={page} />;
}

function LaunchPackRoute({
  fallback,
  preserveInteractive = false,
}: {
  readonly fallback: ReactNode;
  readonly preserveInteractive?: boolean;
}) {
  const location = useLocation();
  // The existing product shell calls the overview /platform; the external
  // launch pack names the same canonical page /product. Keep the public URL
  // stable while making the rendered copy come from the launch-pack source.
  const packRoute = location.pathname === '/platform' ? '/product' : location.pathname;
  const page = getLaunchPackPage('Aether', packRoute);
  if (page !== undefined && !preserveInteractive) return <LaunchPackContent page={page} />;
  return <>{fallback}</>;
}

/**
 * Aether public experience routes.
 *
 * The marketing shell owns every public content route; the AuthLayout is the
 * threshold between the public product and the protected tenant application.
 * AuthLayout routes are deliberately few and quiet.
 */
export function AppRouter() {
  return (
    <Routes>
      <Route element={<AetherShell />}>
        <Route index element={<LaunchPackRoute fallback={<HomePage />} />} />
        {SECTIONS.map((section) => {
          const Page = DEDICATED_PAGES[section.slug] ?? SectionPage;
          return (
            <Route
              key={section.slug}
              path={section.slug}
              element={
                <LaunchPackRoute
                  fallback={<Page />}
                  preserveInteractive={DEDICATED_PAGES[section.slug] !== undefined}
                />
              }
            />
          );
        })}
        {/* Capability-family and solution deep routes */}
        <Route
          path="/platform/:capabilitySlug"
          element={<LaunchPackRoute fallback={<CapabilityPage />} />}
        />
        <Route
          path="/solutions/:solutionSlug"
          element={<LaunchPackRoute fallback={<SolutionPage />} />}
        />
        <Route
          path="/start-pilot"
          element={<LaunchPackRoute fallback={<StartPilotPage />} />}
        />
        <Route
          path="/contact"
          element={<LaunchPackRoute fallback={<ContactPage />} />}
        />
        <Route path="*" element={<LaunchPackRoute fallback={<NotFoundPage />} />} />
      </Route>
      <Route element={<AuthLayout />}>
        <Route path="login" element={<LoginPage />} />
        <Route path="signup" element={<SignupPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
      </Route>
    </Routes>
  );
}
