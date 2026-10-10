import { useEffect, useRef } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { AetherMark, OlympusAttribution } from '@aether-marketing/components/brand-byline';

/**
 * AuthLayout — the threshold between the public Aether product and the
 * tenant application. Intentionally the quietest surface in the system:
 * no decorative or ambient motion, minimal chrome, focused on the single
 * task of getting the right user to the right environment.
 *
 * Phase 4 migrates real sign-in forms into this shell. Until then these
 * routes are honest threshold pages that hand off to the Aether application.
 */
export function AuthLayout() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement | null>(null);
  const isFirstRender = useRef(true);

  // After the initial load, route changes between the threshold pages move
  // focus to the main landmark so keyboard and assistive-tech users land on
  // the new form instead of being left on the (now unmounted) link.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col bg-surface-sunken">
      <a
        href="#auth-main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-text-inverse"
      >
        Skip to content
      </a>
      <header className="border-b border-border-default bg-surface-base">
        <div className="mkt-container flex h-16 items-center justify-between">
          <span className="flex shrink-0 items-center gap-2.5">
            <Link to="/" aria-label="Aether — back to home">
              <AetherMark size={22} />
            </Link>
            <OlympusAttribution />
          </span>
          <nav aria-label="Utility">
            <Link
              to="/"
              className="rounded px-2 py-1 text-sm font-medium text-text-secondary underline underline-offset-2 mkt-motion-color hover:text-text-primary"
            >
              Back to the Aether home page
            </Link>
          </nav>
        </div>
      </header>

      <main
        id="auth-main"
        ref={mainRef}
        tabIndex={-1}
        className="flex flex-1 items-center justify-center px-4 py-12 focus:outline-none md:py-16"
      >
        <Outlet />
      </main>

      <footer className="border-t border-border-default bg-surface-base">
        <div className="mkt-container flex flex-col items-center justify-between gap-3 py-6 text-xs text-text-muted md:flex-row">
          <p className="font-mono">Aether by Olympus Labs</p>
          <nav aria-label="Auth footer" className="flex items-center gap-4">
            <Link to="/" className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
              Home
            </Link>
            <Link to="/security" className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
              Security
            </Link>
            <Link to="/company" className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
              Company
            </Link>
            <Link to="/pricing" className="underline underline-offset-2 mkt-motion-color hover:text-text-primary">
              Pricing
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
