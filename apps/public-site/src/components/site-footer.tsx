/**
 * Built from design/designs/Site Footer.dc.html (copy, layout and styles
 * verbatim). Pilot-only builds leave out the product and status links.
 */
import { asset, css, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { pilotOnly } from '@site/site/access';
import './site-footer.css';

interface FooterLink {
  label: string;
  href: string;
}

const L = (label: string, href: string): FooterLink => ({ label, href });

const COLUMNS: { title: string; links: FooterLink[] }[] = [
  {
    title: 'Aether',
    links: [
      L('Overview', 'Aether Home.dc.html'),
      L('Platform', 'Aether Platform.dc.html'),
      L('How it works', 'Aether How It Works.dc.html'),
      L('Applications', 'Aether Applications.dc.html'),
      L('Connect', 'Aether Connect.dc.html'),
      L('Pricing', 'Aether Pricing.dc.html'),
    ],
  },
  {
    title: 'Olympus Labs',
    links: [
      L('Technology', 'Olympus Technology.dc.html'),
      L('Applications', 'Olympus Applications.dc.html'),
      L('Research', 'Olympus Research.dc.html'),
      L('Proof', 'Olympus Stories.dc.html'),
      L('Company', 'Olympus Company.dc.html'),
      L('Contact', 'Contact.dc.html?brand=olympus'),
    ],
  },
  {
    title: 'Trust',
    links: [
      L('Trust overview', 'Aether Trust.dc.html'),
      L('Security', 'Aether Security.dc.html'),
      L('Procurement', 'Aether Procurement.dc.html'),
      L('Privacy and data use', 'Legal.dc.html?doc=privacy'),
      L('Terms and use', 'Legal.dc.html?doc=terms'),
      L('Status', 'Status.dc.html'),
    ],
  },
  {
    title: 'Resources',
    links: [
      L('Documentation', 'Docs.dc.html'),
      L('Glossary', 'Glossary.dc.html'),
      L('Sign in', 'Aether Portal.dc.html?mode=signin'),
      L('Get started', 'Aether Portal.dc.html?mode=signup'),
      L('Request a pilot', 'Contact.dc.html?brand=aether&type=pilot'),
      L('team@olympuslabsml.com', 'mailto:team@olympuslabsml.com'),
    ],
  },
];

/** Footer columns; pilot-only builds drop sign-in, sign-up and status. */
export function footerColumns(pilot = pilotOnly()): { title: string; links: FooterLink[] }[] {
  if (!pilot) return COLUMNS;
  return COLUMNS.map((col) => ({
    ...col,
    links: col.links.filter((l) => !l.href.startsWith('Aether Portal.dc.html') && l.href !== 'Status.dc.html'),
  }));
}

export function SiteFooter() {
  const link = useLink();
  const pilot = pilotOnly();
  return (
    <footer style={css('background: #eceae5; border-top: 1px solid #d8d6d0; font-family: var(--font-sans);')}>
      <div style={css('max-width: 1200px; margin: 0 auto; padding: 48px 24px 28px;')}>
        <div style={css('display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 32px;')}>
          <div style={css('display: flex; flex-direction: column; gap: 14px; min-width: 200px;')}>
            <div style={css('display: flex; align-items: center; gap: 14px;')}>
              <span style={css('display: flex; align-items: center; gap: 7px;')}>
                <img src={markSrc('olympus')} alt="" style={css('width: 15px; height: 15px;')} />
                <span style={css('font-size: 14px; font-weight: 500; color: #1a1a1e;')}>Olympus Labs</span>
              </span>
              <span aria-hidden="true" style={css('width: 1px; height: 14px; background: #d8d6d0;')} />
              <span style={css('display: flex; align-items: center; gap: 6px;')}>
                <img src={markSrc('aether')} alt="" style={css('width: 17px; height: 17px;')} />
                <span style={css('font-size: 14px; font-weight: 500; color: #1a1a1e;')}>Aether</span>
              </span>
            </div>
            <p style={css('font-size: 13px; line-height: 1.55; color: #6b6a65; max-width: 260px; margin: 0;')}>
              Olympus Labs builds technology that helps systems understand people, agents, relationships, activity, and value. Aether is the
              intelligence technology that creates that shared understanding.
            </p>
          </div>
          {footerColumns(pilot).map((col) => (
            <nav key={col.title} aria-label={col.title} style={css('display: flex; flex-direction: column; gap: 10px;')}>
              <span style={css('font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;')}>{col.title}</span>
              {col.links.map((l) => (
                <a key={l.label} href={link(l.href)} style={css('font-size: 13px; color: #1a1a1e; text-decoration: none;')} className="hv-cc8e330e">
                  {l.label}
                </a>
              ))}
            </nav>
          ))}
        </div>
        <div style={css('margin-top: 40px; padding-top: 20px; border-top: 1px solid #d8d6d0; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; font-size: 12px; color: #6b6a65;')}>
          <span>© 2026 Olympus Labs. All rights reserved.</span>
          <span style={css('display: flex; gap: 16px; font-family: var(--font-mono);')}>
            {pilot ? null : (
              <a href={link('Status.dc.html')} style={css('color: #6b6a65; text-decoration: none;')}>
                status.olympuslabsml.com
              </a>
            )}
            <span style={css('display: inline-flex; align-items: center; gap: 6px;')}>
              <img src={markSrc('aether')} alt="" style={css('width: 14px; height: 14px;')} />
              Aether by
              <img src={markSrc('olympus')} alt="" style={css('width: 13px; height: 13px;')} />
              Olympus Labs
            </span>
          </span>
        </div>
      </div>
    </footer>
  );
}
