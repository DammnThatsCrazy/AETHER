import { Link, Route, Routes, useLocation } from 'react-router-dom';
import type { ReactNode } from 'react';
import { OlympusShell } from '@olympus-marketing/components/olympus-shell';
import { HomePage } from '@olympus-marketing/pages/home-page';
import { SectionPage } from '@olympus-marketing/pages/section-page';
import { usePageMeta } from '@olympus-marketing/lib/meta';
import { LaunchPackPage } from '../../../marketing/src/LaunchPackPage';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';

export function NotFoundPage() {
  usePageMeta({ title: 'Page not found — Olympus Labs' });
  return (
    <section className="mkt-container py-24">
      <h1 className="mkt-display">Page not found.</h1>
      <p className="mkt-lead mt-4">
        The page you are looking for does not exist on the Olympus Labs site. Return to the{' '}
        <Link className="text-accent underline" to="/">
          Olympus Labs home page
        </Link>
        .
      </p>
    </section>
  );
}

function LaunchPackRoute({ fallback }: { readonly fallback: ReactNode }) {
  const location = useLocation();
  const packRoute = location.pathname === '/products/aether' ? '/aether' : location.pathname;
  const page = getLaunchPackPage('Olympus Labs', packRoute);
  usePageMeta({
    title: page?.seoTitle || 'Olympus Labs',
    description: page?.seoDescription || 'Olympus Labs relationship infrastructure.',
  });
  return page ? <LaunchPackPage page={page} /> : <>{fallback}</>;
}

/**
 * Olympus Labs marketing routes. The shell stays mounted across every route;
 * only the workspace below it changes. Public site — no authenticated surface.
 */
export function AppRouter() {
  return (
    <Routes>
      <Route element={<OlympusShell />}>
        <Route index element={<LaunchPackRoute fallback={<HomePage />} />} />
        <Route path="company" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="principles" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="manifesto" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="aether" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="products" element={<SectionPage />} />
        <Route path="products/aether" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="research" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="resources" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="stories" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="why-olympus" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="security" element={<SectionPage />} />
        <Route path="careers" element={<SectionPage />} />
        <Route path="contact" element={<LaunchPackRoute fallback={<SectionPage />} />} />
        <Route path="legal" element={<SectionPage />} />
        <Route path="*" element={<LaunchPackRoute fallback={<NotFoundPage />} />} />
      </Route>
    </Routes>
  );
}
