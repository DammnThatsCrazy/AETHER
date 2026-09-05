import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Button, OlympusLockup } from '@aether/ui';
import { cn } from '@aether/ui';
import { AETHER_MARKETING_URL } from '@olympus-marketing/lib/env';
import { PRIMARY_NAV } from '@olympus-marketing/content/sections';

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
        <li className="mt-2 flex flex-col gap-2 border-t border-border-default pt-4">
          <Button asChild variant="secondary" size="md">
            <Link to="/contact" onClick={onNavigate}>
              Contact
            </Link>
          </Button>
          <Button asChild variant="primary" size="md">
            <a href={AETHER_MARKETING_URL}>Explore Aether</a>
          </Button>
        </li>
      </ul>
    </nav>
  );
}

/**
 * Olympus Labs Marketing Shell — the most spacious shell in the family.
 * Persistent header/nav/footer remain mounted; only the workspace route below
 * changes. Marketing never links into Kyber; KYBER_URL stays out of public UI.
 */
export function OlympusShell() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const mainRef = useRef<HTMLElement | null>(null);
  const isFirstRender = useRef(true);

  // Close the disclosure menu and reset scroll on route change while the shell
  // itself stays mounted (no full-page resets, no white flash). After the
  // initial load, route changes also move focus to the main landmark so
  // keyboard and assistive-tech users land on the new page's content.
  useEffect(() => {
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
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
          <Link to="/" aria-label="Olympus Labs — home" className="shrink-0">
            <OlympusLockup variant="full" label="Olympus Labs" size={22} />
          </Link>

          <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
            {PRIMARY_NAV.map((item) => (
              <NavLink key={item.to} to={item.to} className={navClass}>
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="hidden items-center gap-3 lg:flex">
            <Button asChild variant="secondary" size="md">
              <Link to="/contact">Contact</Link>
            </Button>
            <Button asChild variant="primary" size="md">
              <a href={AETHER_MARKETING_URL}>Explore Aether</a>
            </Button>
          </div>

          <button
            type="button"
            className="inline-flex h-10 w-10 items-center justify-center rounded-md text-text-secondary hover:bg-surface-raised hover:text-text-primary lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="olympus-mobile-nav"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span className="sr-only">{menuOpen ? 'Close menu' : 'Open menu'}</span>
            <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75">
              {menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        {menuOpen && (
          <div id="olympus-mobile-nav">
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
              <OlympusLockup variant="full" label="Olympus Labs" size={20} />
              <p className="mt-4 max-w-xs text-sm leading-relaxed text-text-secondary">
                Olympus Labs builds Aether, the relationship intelligence platform. Aether is the product.
                Olympus Labs is the company.
              </p>
            </div>
            <FooterColumn title="Company">
              <FooterLink to="/company" label="Company" />
              <FooterLink to="/principles" label="Principles" />
              <FooterLink to="/research" label="Research" />
              <FooterLink to="/careers" label="Careers" />
              <FooterLink to="/contact" label="Contact" />
            </FooterColumn>
            <FooterColumn title="Products">
              <FooterLink to="/products" label="Products" />
              <FooterLink to="/products/aether" label="Aether" />
              <FooterLink to="/security" label="Security" />
            </FooterColumn>
            <FooterColumn title="Legal">
              <FooterLink to="/legal" label="Legal notices" />
            </FooterColumn>
          </div>
          <div className="mt-10 flex flex-col gap-2 border-t border-border-default pt-6 text-xs text-text-muted md:flex-row md:items-center md:justify-between">
            <p>© {new Date().getFullYear()} Olympus Labs. All rights reserved.</p>
            <p className="font-mono">
              Aether by Olympus Labs · <span className="text-text-muted">Kyber is internal</span>
            </p>
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
