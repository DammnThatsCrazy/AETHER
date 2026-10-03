/**
 * Built from design/designs/Site Header.dc.html (copy, layout and styles
 * verbatim). The design switches layouts on window width; here both render and
 * a 1080px media query picks one, so prerendered pages are right on phones.
 * Pilot-only builds (production before its backend) drop "Sign in" and make
 * "Request a pilot" the primary action.
 */
import { Fragment, useEffect } from 'react';
import { asset, css, useDesignState, useLink } from '@site/design/runtime';
import { pilotOnly } from '@site/site/access';
import { SkipLink } from '@site/components/skip-link';
import { useSite } from '@site/site/site-context';
import './site-header.css';

interface MenuItem {
  g: string;
  label: string;
  href: string;
  q: string;
  c: string;
}

type NavEntry = [label: string, href: string, children: MenuItem[] | null];

const C = (g: string, label: string, href: string, q: string, c: string): MenuItem => ({ g, label, href, q, c });

const AETHER_NAV: NavEntry[] = [
  ['Platform', 'Aether Platform.dc.html', [
    C('◈', 'Overview', 'Aether Platform.dc.html', 'What can Aether do?', '#3a6896'),
    C('→', 'How it works', 'Aether How It Works.dc.html', 'How does Aether produce understanding?', '#4f8466'),
    C('↔', 'Graph', 'Aether Feature Page.dc.html?f=graph', 'What is related?', '#3a6896'),
    C('⬡', 'Profiles', 'Aether Feature Page.dc.html?f=profiles', 'Who is this?', '#5a85a8'),
    C('◉', 'Journeys', 'Aether Feature Page.dc.html?f=journeys', 'How did they get here?', '#4f8466'),
    C('◈', 'Lenses', 'Aether Lenses.dc.html', 'What does this look like from another perspective?', '#8a6433'),
    C('⬡', 'Agents', 'Aether Agents.dc.html', 'What did the agent do?', '#a8783e'),
    C('↑', 'Value and risk', 'Aether Feature Page.dc.html?f=value', 'What influenced this outcome?', '#a3473c'),
  ]],
  ['Applications', 'Aether Applications.dc.html', [
    C('●', 'Customer intelligence', 'Aether Customer Intelligence.dc.html', 'One explainable history per customer', '#3a6896'),
    C('↑', 'Revenue intelligence', 'Aether Applications.dc.html#revenue', 'From first signal to revenue', '#4f8466'),
    C('⬡', 'Agent intelligence', 'Aether Agents.dc.html', 'Lineage, authority, and outcomes', '#a8783e'),
    C('✉', 'Communications', 'Aether Applications.dc.html#communications', 'Messages as relationship history', '#5a85a8'),
    C('▲', 'Risk and trust', 'Aether Applications.dc.html#risk', 'How risk emerges from relationships', '#a3473c'),
    C('◉', 'Operations', 'Aether Applications.dc.html#operations', 'What is happening now', '#7d6538'),
  ]],
  ['Connect', 'Aether Connect.dc.html', [
    C('⚙', 'Connectors', 'Aether Detail Page.dc.html?p=connectors', 'Existing SaaS platforms', '#5a85a8'),
    C('⌘', 'SDKs', 'Aether Detail Page.dc.html?p=sdks', 'Web, iOS, Android, React Native', '#3a6896'),
    C('→', 'APIs and webhooks', 'Aether Detail Page.dc.html?p=apis', 'Backends and live services', '#4f8466'),
    C('⇪', 'Imports', 'Aether Detail Page.dc.html?p=imports', 'Historical files', '#8a6433'),
  ]],
  ['Developers', 'Docs.dc.html', [
    C('⌘', 'Documentation', 'Docs.dc.html', 'Understand, use, connect, build', '#3a6896'),
    C('◉', 'Quickstarts', 'Docs.dc.html?page=start-here', 'Send your first signal', '#4f8466'),
    C('≡', 'API reference', 'Docs.dc.html?page=ingestion-api', 'Exact contracts', '#5a85a8'),
    C('◈', 'Glossary', 'Glossary.dc.html', 'Plain, product, and technical meanings', '#8a6433'),
    C('●', 'Status', 'Status.dc.html', 'Service health', '#4f8466'),
  ]],
  ['Pricing', 'Aether Pricing.dc.html', null],
];

const OLYMPUS_NAV: NavEntry[] = [
  ['Technology', 'Olympus Technology.dc.html', [
    C('◈', 'Overview', 'Olympus Technology.dc.html', 'What kind of technology is this?', '#3a6896'),
    C('↔', 'Records and relationships', 'Olympus Technology.dc.html#views', 'What software sees, and what Olympus sees', '#4f8466'),
  ]],
  ['Applications', 'Olympus Applications.dc.html', null],
  ['Aether', 'Aether Home.dc.html', null],
  ['Research', 'Olympus Research.dc.html', null],
  ['Company', 'Olympus Company.dc.html', [
    C('◈', 'About', 'Olympus Company.dc.html', 'Who is behind this?', '#3a6896'),
    C('✓', 'Principles', 'Olympus Principles.dc.html', 'How the work is governed', '#4f8466'),
    C('◉', 'Proof', 'Olympus Stories.dc.html', 'Has this actually worked?', '#7d6538'),
    C('✉', 'Contact', 'Contact.dc.html?brand=olympus', 'Reach the team', '#8a6433'),
  ]],
];

/** The header navigation for a site, with pilot-only builds dropping the status link. */
export function headerNav(brand: 'aether' | 'olympus', pilot = pilotOnly()): NavEntry[] {
  const raw = brand === 'olympus' ? OLYMPUS_NAV : AETHER_NAV;
  if (!pilot) return raw;
  return raw.map(([label, href, children]) => [label, href, children && children.filter((c) => c.href !== 'Status.dc.html')]);
}

const NAV_BASE =
  'font-family: inherit; display: inline-flex; align-items: center; gap: 4px; background: transparent; border: 0; cursor: pointer; font-size: 13px; font-weight: 500; text-decoration: none; padding: 8px 10px; border-radius: 4px; transition: color 120ms cubic-bezier(0.22,1,0.36,1);';

export function SiteHeader({ brand, active = '' }: { brand?: 'aether' | 'olympus'; active?: string }) {
  const link = useLink();
  const { site } = useSite();
  const isAether = (brand ?? site) !== 'olympus';
  const pilot = pilotOnly();
  const [state, setState] = useDesignState<{ open: boolean; menu: string | null; viaHover: boolean }>({ open: false, menu: null, viaHover: false });

  useEffect(() => {
    const onK = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setState({ menu: null, open: false });
    };
    const onDoc = (e: MouseEvent) => {
      const target = e.target as Element | null;
      if (!target?.closest?.('nav[aria-label="Primary"]')) setState({ menu: null });
    };
    window.addEventListener('keydown', onK);
    document.addEventListener('click', onDoc);
    return () => {
      window.removeEventListener('keydown', onK);
      document.removeEventListener('click', onDoc);
    };
  }, [setState]);

  const nav = headerNav(isAether ? 'aether' : 'olympus', pilot).map(([label, href, children]) => {
    const open = state.menu === label;
    return {
      label,
      href,
      hasMenu: !!children,
      open: !!children && open,
      expanded: open,
      children: (children ?? []).map((c) => ({
        ...c,
        gStyle: 'font-family: var(--font-mono); font-size: 13px; color: ' + c.c + '; line-height: 18px;',
      })),
      style: NAV_BASE + (label === active || open ? 'color: #1a1a1e;' : 'color: #6b6a65;'),
      caret:
        'font-family: var(--font-mono); font-size: 10px; opacity: 0.6; transition: transform 120ms cubic-bezier(0.22,1,0.36,1); transform: rotate(' +
        (open ? '180deg' : '0') +
        ');',
      panel:
        'width: ' +
        ((children ?? []).length > 5 ? 360 : 300) +
        'px; box-sizing: border-box; padding: 6px; background: #fbfaf8; border: 1px solid #d8d6d0; border-radius: 8px; box-shadow: 0 12px 32px rgba(26,26,30,0.10), 0 2px 6px rgba(26,26,30,0.05); display: flex; flex-direction: column; animation: hdrIn 200ms cubic-bezier(0.22,1,0.36,1) both;',
      enter: () => {
        if (children) setState((s) => (s.menu === label ? {} : { menu: label, viaHover: true }));
      },
      leave: () => setState((s) => (s.menu === label ? { menu: null } : {})),
      // A click on a menu the pointer just opened keeps it open; a second click closes it.
      toggle: () => setState((s) => (s.menu === label && !s.viaHover ? { menu: null } : { menu: label, viaHover: false })),
    };
  });

  // Pilot-only builds have no product to sign in to: one action, a pilot request.
  const showSignIn = isAether && !pilot;
  const secondary = isAether
    ? pilot
      ? null
      : { label: 'Request a pilot', href: 'Contact.dc.html?brand=aether&type=pilot' }
    : { label: 'Contact', href: 'Contact.dc.html?brand=olympus' };
  const primary = isAether
    ? pilot
      ? { label: 'Request a pilot', href: 'Contact.dc.html?brand=aether&type=pilot' }
      : { label: 'Get started', href: 'Aether Portal.dc.html?mode=signup' }
    : { label: 'Explore Aether', href: 'Aether Home.dc.html' };
  const open = state.open;

  return (
    <header style={css('position: sticky; top: 0; z-index: 40; background: #f5f4f1; border-bottom: 1px solid #d8d6d0; font-family: var(--font-sans);')}>
      <SkipLink />
      <div style={css('max-width: 1200px; margin: 0 auto; padding: 0 24px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 24px;')}>
        <div style={css('display: flex; align-items: center; gap: 10px; flex-shrink: 0;')}>
          {isAether ? (
            <>
              <a href={link('Aether Home.dc.html')} aria-label="Aether home" style={css('display: flex; align-items: center; gap: 8px; text-decoration: none; color: #1a1a1e;')}>
                <img src={asset('../assets/logo-aether-layers.svg')} alt="" style={css('width: 22px; height: 22px; display: block;')} />
                <span style={css('font-size: 17px; font-weight: 500; letter-spacing: -0.4px;')}>Aether</span>
              </a>
              <span style={css('font-size: 12px; color: #6b6a65;')}>
                {'by '}
                <a href={link('Olympus Home.dc.html')} style={css('color: #6b6a65; text-decoration: underline; text-underline-offset: 2px;')}>
                  Olympus Labs
                </a>
              </span>
            </>
          ) : (
            <a href={link('Olympus Home.dc.html')} aria-label="Olympus Labs home" style={css('display: flex; align-items: center; gap: 9px; text-decoration: none; color: #1a1a1e;')}>
              <img src={asset('../assets/logo-olympus-arch.svg')} alt="" style={css('width: 18px; height: 18px; display: block;')} />
              <span style={css('font-size: 16px; font-weight: 500; letter-spacing: -0.3px;')}>Olympus Labs</span>
            </a>
          )}
        </div>
        <nav aria-label="Primary" className="hdr-wide" style={css('align-items: center; gap: 2px;')}>
          {nav.map((item) => (
            <div key={item.label} style={css('position: relative;')} onMouseEnter={item.enter} onMouseLeave={item.leave}>
              {item.hasMenu ? (
                <button type="button" onClick={item.toggle} aria-expanded={item.expanded} aria-haspopup="true" style={css(item.style)} className="hv-75877933">
                  {item.label}
                  <span style={css(item.caret)}>↓</span>
                </button>
              ) : (
                <a href={link(item.href)} aria-current={item.label === active ? 'page' : undefined} style={css(item.style)} className="hv-75877933">
                  {item.label}
                </a>
              )}
              {item.open ? (
                <div style={css('position: absolute; top: 100%; left: -8px; padding-top: 10px; z-index: 50;')}>
                  <div role="menu" style={css(item.panel)}>
                    {item.children.map((c) => (
                      <a
                        key={c.label + c.href}
                        href={link(c.href)}
                        role="menuitem"
                        style={css('display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 2px 8px; padding: 9px 10px; border-radius: 6px; text-decoration: none; color: #1a1a1e; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);')}
                        className="hv-67a914b1"
                      >
                        <span aria-hidden="true" style={css(c.gStyle)}>
                          {c.g}
                        </span>
                        <span style={css('font-size: 13px; font-weight: 500;')}>{c.label}</span>
                        <span />
                        <span style={css('font-size: 12px; color: #6b6a65; line-height: 1.4;')}>{c.q}</span>
                      </a>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </nav>
        <div className="hdr-wide" style={css('align-items: center; gap: 8px;')}>
          {showSignIn ? (
            <a href={link('Aether Portal.dc.html?mode=signin')} style={css('font-size: 13px; font-weight: 500; color: #6b6a65; text-decoration: none; padding: 0 8px;')} className="hv-75877933">
              Sign in
            </a>
          ) : null}
          {secondary ? (
            <a
              href={link(secondary.href)}
              style={css('display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; flex-shrink: 0; box-sizing: border-box; font-size: 13px; font-weight: 500; color: #1a1a1e; text-decoration: none; padding: 0 14px; min-height: 36px; border: 1px solid #d8d6d0; background: #eceae5; border-radius: 6px; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);')}
              className="hv-dafa5f55"
            >
              {secondary.label}
            </a>
          ) : null}
          <a
            href={link(primary.href)}
            style={css('display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; flex-shrink: 0; box-sizing: border-box; font-size: 13px; font-weight: 500; color: #f5f4f1; text-decoration: none; padding: 0 14px; min-height: 36px; border-radius: 6px; background: #2563eb; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);')}
            className="hv-7e3a2e7d"
          >
            {primary.label}
          </a>
        </div>
        <button
          type="button"
          className="hdr-narrow"
          onClick={() => setState((s) => ({ open: !s.open }))}
          aria-expanded={open}
          aria-controls="site-mobile-nav"
          aria-label={open ? 'Close menu' : 'Open menu'}
          style={css('width: 44px; height: 44px; align-items: center; justify-content: center; background: transparent; border: 0; border-radius: 4px; color: #1a1a1e; cursor: pointer; font-family: var(--font-mono); font-size: 18px;')}
        >
          {open ? '✕' : '≡'}
        </button>
      </div>
      {open ? (
        <nav
          id="site-mobile-nav"
          aria-label="Mobile"
          className="hdr-narrow-block"
          onClick={(e) => {
            if ((e.target as HTMLElement).closest('a')) setState({ open: false });
          }}
          style={css('border-top: 1px solid #d8d6d0; background: #f5f4f1; padding: 8px 24px 20px; max-height: calc(100vh - 57px); overflow-y: auto; box-sizing: border-box;')}
        >
          <div style={css('display: flex; flex-direction: column;')}>
            {nav.map((item) => (
              <div key={item.label} style={css('display: flex; flex-direction: column; border-bottom: 1px solid #e8e6e1; padding: 10px 0;')}>
                <a href={link(item.href)} style={css('font-size: 15px; font-weight: 500; color: #1a1a1e; text-decoration: none; padding: 4px 0; display: flex; justify-content: space-between;')}>
                  <span>{item.label}</span>
                  <span aria-hidden="true" style={css('font-family: var(--font-mono); color: #6b6a65;')}>
                    →
                  </span>
                </a>
                {item.hasMenu ? (
                  <div style={css('display: flex; flex-wrap: wrap; gap: 4px 14px; padding: 4px 0 2px;')}>
                    {item.children.map((c) => (
                      <Fragment key={c.label + c.href}>
                        <a href={link(c.href)} style={css('font-size: 13px; color: #6b6a65; text-decoration: none; padding: 4px 0;')}>
                          {c.label}
                        </a>
                      </Fragment>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          <div style={css('display: flex; flex-direction: column; gap: 8px; margin-top: 16px;')}>
            {secondary ? (
              <a
                href={link(secondary.href)}
                style={css('display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; padding: 0 18px; min-height: 44px; border: 1px solid #d8d6d0; background: #eceae5; border-radius: 6px;')}
              >
                {secondary.label}
              </a>
            ) : null}
            <a
              href={link(primary.href)}
              style={css('display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; font-size: 14px; font-weight: 500; color: #f5f4f1; text-decoration: none; padding: 0 18px; min-height: 44px; border-radius: 6px; background: #2563eb;')}
            >
              {primary.label}
            </a>
            {showSignIn ? (
              <a href={link('Aether Portal.dc.html?mode=signin')} style={css('font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; text-align: center; padding: 10px 0;')}>
                Sign in
              </a>
            ) : null}
          </div>
        </nav>
      ) : null}
    </header>
  );
}
