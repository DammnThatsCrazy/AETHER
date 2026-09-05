import type { ComponentType } from 'react';
import { Routes, Route } from 'react-router-dom';
import { AetherShell } from '@aether-marketing/components/aether-shell';
import { AuthLayout } from '@aether-marketing/components/auth-layout';
import { SECTIONS } from '@aether-marketing/content/sections';
import { CapabilityPage } from '@aether-marketing/pages/capability-page';
import { DevelopersPage } from '@aether-marketing/pages/developers-page';
import { HomePage } from '@aether-marketing/pages/home-page';
import { IntegrationsPage } from '@aether-marketing/pages/integrations-page';
import { NotFoundPage } from '@aether-marketing/pages/not-found';
import { PlatformPage } from '@aether-marketing/pages/platform-page';
import { SectionPage } from '@aether-marketing/pages/section-page';
import { SolutionPage } from '@aether-marketing/pages/solution-page';
import { SolutionsPage } from '@aether-marketing/pages/solutions-page';
import { ForgotPasswordPage } from '@aether-marketing/pages/auth/forgot-password-page';
import { LoginPage } from '@aether-marketing/pages/auth/login-page';
import { SignupPage } from '@aether-marketing/pages/auth/signup-page';

/**
 * Sections with a dedicated interactive/landing page. Every other top-level
 * section slug falls back to the generic SectionPage.
 */
const DEDICATED_PAGES: Readonly<Record<string, ComponentType>> = {
  '/platform': PlatformPage,
  '/solutions': SolutionsPage,
  '/integrations': IntegrationsPage,
  '/developers': DevelopersPage,
};

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
        <Route index element={<HomePage />} />
        {SECTIONS.map((section) => {
          const Page = DEDICATED_PAGES[section.slug] ?? SectionPage;
          return <Route key={section.slug} path={section.slug} element={<Page />} />;
        })}
        {/* Capability-family and solution deep routes */}
        <Route path="/platform/:capabilitySlug" element={<CapabilityPage />} />
        <Route path="/solutions/:solutionSlug" element={<SolutionPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route element={<AuthLayout />}>
        <Route path="login" element={<LoginPage />} />
        <Route path="signup" element={<SignupPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
      </Route>
    </Routes>
  );
}
