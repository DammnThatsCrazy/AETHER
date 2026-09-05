import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Button } from '@aether/ui';
import { cn } from '@aether/ui';
import { AetherMark, OlympusAttribution } from '@aether-marketing/components/brand-byline';
import { PRIMARY_NAV } from '@aether-marketing/content/sections';
import { AETHER_DOCS_URL, OLYMPUS_SITE_URL } from '@aether-marketing/lib/env';

function navClass({ isActive }: { readonly isActive: boolean }): string {
  return cn(
    'rounded px-3 py-2 text-sm font-medium mkt-motion-color',
    isActive ? 'text-text-primary' : 'text-text-secondary hover:text-text-primary',
  );
}

function MobileNav({ onNavigate }: { readonly onNavigate: () => void }) {
  return (
    <nav aria-label="Mobile" className="border-t border-border-default bg-surface-base lg:hidden">
      <ul className="mkt-container flex flex-col py-4">
        {PRIMARY_NAV.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} onClick={onNavigate} className={navClass}>
              {item.label}
            </NavLink>
          </li>
        ))}
        <li className="mt-3 flex flex-col gap-2 border-t border-border-default pt-4">
          <Button asChild variant="secondary" size="md">
            <a href={AETHER_DOCS_URL}>Documentation</a>
          </Button>
          <Button asChild variant="primary" size="md">
            <Link to="/login">Sign in</Link>
          </Button>
        </li>
      </ul>
    </nav>
  );
}

/**
 * Aether Marketing Shell — behaves like a read-only intelligence application.
 * Persistent header/nav/footer stay mounted; the relationship-graph visual
 * substrate (Phase 3) will shift focus per route rather than restarting.
 */
export function AetherShell() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const isFirstRender = useRef(true);

  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
    // Move focus to the main landmark on route change (but not on the initial
    // page load, which should start at the top of the document). This keeps
    // keyboard and assistive-tech users on the new page's content after a
    // router navigation instead of leaving focus on the (now unmounted) link.
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  return (
    <div className="flex min-h-screen flex-col bg-surface-base">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-accent focus:px-3 focus:py-2 focus:text-text-inverse"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b border-border-default bg-surface-base/95 backdrop-blur supports-[backdrop-filter]:bg-surface-base/80">
        <div className="mkt-container flex h-16 items-center justify-between gap-6">
          <span className="flex shrink-0 items-center gap-2.5">
            <Link to="/" aria-label="Aether — home">
              <AetherMark size={24} />
            </Link>
            <OlympusAttribution />
          </span>

          <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
            {PRIMARY_NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClass}>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-3 lg:flex">
            <a
              href={AETHER_DOCS_URL}
              className="rounded px-3 py-2 text-sm font-medium text-text-secondary mkt-motion-color hover:text-text-primary"
            >
              Docs
            </a>
            <Button asChild variant="secondary" size="md">
              <Link to="/login">Sign in</Link>
            </Button>
            <Button asChild variant="primary" size="md">
              <Link to="/signup">Start building</Link>
            </Button>
          </div>

          <button
            type="button"
            className="inline-flex h-10 w-10 items-center justify-center rounded-md text-text-secondary hover:bg-surface-raised hover:text-text-primary lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="aether-marketing-mobile-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="sr-only">{menuOpen ? 'Close menu' : 'Open menu'}</span>
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75">
              {menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        {menuOpen && (
          <div id="aether-marketing-mobile-nav">
            <MobileNav onNavigate={() => setMenuOpen(false)} />
          </div>
        )}
      </header>

      <main id="main" ref={mainRef} tabIndex={-1} className="flex-1 focus:outline-none">
        <Outlet />
      </main>

      <footer className="border-t border-border-default bg-surface-sunken">
        <div className="mkt-container py-12">
          <div className="grid gap-10 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
            <div>
              <AetherMark size={22} />
              <p className="mt-4 max-w-xs text-sm leading-relaxed text-text-secondary">
                Aether is the relationship intelligence platform that connects fragmented activity into a
                governed graph. Aether, by Olympus Labs.
              </p>
            </div>
            <FooterColumn title="Platform">
              <FooterLink to="/platform" label="Platform overview" />
              <FooterLink to="/developers" label="Developers" />
              <FooterLink to="/integrations" label="Integrations" />
            </FooterColumn>
            <FooterColumn title="Company">
              <FooterLink to="/company" label="About Olympus Labs" />
              <FooterLink to="/security" label="Security" />
              <FooterLink to="/pricing" label="Pricing" />
              <FooterLink to="/resources" label="Resources" />
            </FooterColumn>
            <FooterColumn title="Sign in">
              <FooterLink to="/login" label="Aether sign in" />
              <FooterLink to="/signup" label="Start building" />
              <FooterExternal to={AETHER_DOCS_URL} label="Documentation" />
              <FooterExternal to={OLYMPUS_SITE_URL} label="Olympus Labs" />
            </FooterColumn>
          </div>
          <div className="mt-10 flex flex-col gap-2 border-t border-border-default pt-6 text-xs text-text-muted md:flex-row md:items-center md:justify-between">
            <p>© {new Date().getFullYear()} Olympus Labs. All rights reserved.</p>
            <p className="font-mono">Aether by Olympus Labs</p>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FooterColumn({ title, children }: { readonly title: string; readonly children: ReactNode }) {
  return (
    <nav aria-label={title}>
      <h2 className="mkt-eyebrow">{title}</h2>
      <ul className="mt-4 space-y-2">{children}</ul>
    </nav>
  );
}

function FooterLink({ to, label }: { readonly to: string; readonly label: string }) {
  return (
    <li>
      <NavLink
        to={to}
        className="text-sm text-text-secondary underline underline-offset-2 mkt-motion-color hover:text-text-primary"
      >
        {label}
      </NavLink>
    </li>
  );
}

function FooterExternal({ to, label }: { readonly to: string; readonly label: string }) {
  return (
    <li>
      <a
        href={to}
        className="text-sm text-text-secondary underline underline-offset-2 mkt-motion-color hover:text-text-primary"
      >
        {label}
      </a>
    </li>
  );
}
