import { Link, Route, Routes } from 'react-router-dom';
import { OlympusShell } from '@olympus-marketing/components/olympus-shell';
import { HomePage } from '@olympus-marketing/pages/home-page';
import { SectionPage } from '@olympus-marketing/pages/section-page';
import { usePageMeta } from '@olympus-marketing/lib/meta';

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

/**
 * Olympus Labs marketing routes. The shell stays mounted across every route;
 * only the workspace below it changes. Public site — no authenticated surface.
 */
export function AppRouter() {
  return (
    <Routes>
      <Route element={<OlympusShell />}>
        <Route index element={<HomePage />} />
        <Route path="company" element={<SectionPage />} />
        <Route path="principles" element={<SectionPage />} />
        <Route path="products" element={<SectionPage />} />
        <Route path="products/aether" element={<SectionPage />} />
        <Route path="research" element={<SectionPage />} />
        <Route path="security" element={<SectionPage />} />
        <Route path="careers" element={<SectionPage />} />
        <Route path="contact" element={<SectionPage />} />
        <Route path="legal" element={<SectionPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
