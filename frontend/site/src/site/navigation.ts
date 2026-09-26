/**
 * Header, footer and 404 link content from the handoff designs
 * (Site Header / Site Footer / Not Found .dc.html). Each link names the site it
 * belongs to; components turn it into a relative or absolute href with
 * useSite().href.
 */
import type { SiteId } from './site';

export interface SiteLink {
  label: string;
  site: SiteId;
  path: string;
}

const link = (label: string, site: SiteId, path: string): SiteLink => ({ label, site, path });

export interface HeaderNav {
  items: SiteLink[];
  secondary: SiteLink;
  primary: SiteLink;
}

export const HEADER_NAV: Record<SiteId, HeaderNav> = {
  aether: {
    items: [
      link('About', 'aether', '/#about'),
      link('How it works', 'aether', '/how-it-works'),
      link('Connections', 'aether', '/connections'),
      link('Pricing', 'aether', '/pricing'),
      link('Developers', 'aether', '/docs'),
      link('Security', 'aether', '/security'),
    ],
    secondary: link('Sign in', 'aether', '/app/signin'),
    primary: link('Request a pilot', 'aether', '/contact?type=pilot'),
  },
  olympus: {
    items: [
      link('Company', 'olympus', '/company'),
      link('Principles', 'olympus', '/principles'),
      link('Research', 'olympus', '/research'),
      link('Stories', 'olympus', '/stories'),
      link('Aether', 'aether', '/'),
      link('Contact', 'olympus', '/#contact'),
    ],
    secondary: link('Contact', 'olympus', '/contact'),
    primary: link('Explore Aether', 'aether', '/'),
  },
};

export interface FooterColumn {
  title: string;
  links: SiteLink[];
}

export const FOOTER_COLUMNS: FooterColumn[] = [
  {
    title: 'Aether',
    links: [
      link('Overview', 'aether', '/'),
      link('How it works', 'aether', '/how-it-works'),
      link('Connections', 'aether', '/connections'),
      link('Pricing', 'aether', '/pricing'),
      link('Request a pilot', 'aether', '/contact?type=pilot'),
    ],
  },
  {
    title: 'Olympus Labs',
    links: [
      link('Company', 'olympus', '/company'),
      link('Principles', 'olympus', '/principles'),
      link('Research', 'olympus', '/research'),
      link('Stories and proof', 'olympus', '/stories'),
      link('Contact', 'olympus', '/contact'),
    ],
  },
  {
    title: 'Trust',
    links: [
      link('Security overview', 'aether', '/security'),
      link('Procurement', 'aether', '/procurement'),
      link('Request a security review', 'aether', '/contact?type=security'),
      link('Privacy and data use', 'aether', '/legal/privacy'),
      link('Terms and use', 'aether', '/legal/terms'),
    ],
  },
  {
    title: 'Resources',
    links: [
      link('Documentation', 'aether', '/docs'),
      link('Status', 'aether', '/status'),
      link('Sign in', 'aether', '/app/signin'),
      link('Create an account', 'aether', '/app/signup'),
      link('contact@olympuslabsml.com', 'aether', 'mailto:contact@olympuslabsml.com'),
    ],
  },
];

export type AccentId = 'cobalt' | 'sage' | 'ochre' | 'steel';

export interface NotFoundLink extends SiteLink {
  glyph: string;
  body: string;
  accent: AccentId;
}

const ACCENT_ORDER: AccentId[] = ['cobalt', 'sage', 'ochre', 'steel'];

function notFoundLinks(rows: Array<[string, string, string, SiteId, string]>): NotFoundLink[] {
  return rows.map(([glyph, label, body, site, path], index) => ({
    glyph,
    label,
    body,
    site,
    path,
    accent: ACCENT_ORDER[index % ACCENT_ORDER.length] as AccentId,
  }));
}

export const NOT_FOUND_LINKS: Record<SiteId, NotFoundLink[]> = {
  olympus: notFoundLinks([
    ['◈', 'Olympus Labs home', 'The company and its principles', 'olympus', '/'],
    ['⬡', 'Aether', 'The flagship product', 'aether', '/'],
    ['⚗', 'Research', 'Open questions', 'olympus', '/research'],
    ['✉', 'Contact', 'Reach the team', 'olympus', '/contact'],
  ]),
  aether: notFoundLinks([
    ['⬡', 'Aether home', 'What Aether is and does', 'aether', '/'],
    ['⌘', 'Documentation', 'Quickstarts, SDKs, connectors', 'aether', '/docs'],
    ['◉', 'Status', 'Service health', 'aether', '/status'],
    ['✉', 'Contact', 'Reach an engineer', 'aether', '/contact?type=developer'],
  ]),
};
