/**
 * Built from design/designs/Not Found.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './not-found-page.css';

import { useLocation } from 'react-router-dom';
import { useSite } from '@site/site/site-context';
import { pilotOnly } from '@site/site/access';

const LINKS: Record<'aether' | 'olympus', [g: string, title: string, body: string, href: string][]> = {
  olympus: [['◈', 'Olympus Labs home', 'The company and what it believes', 'Olympus Home.dc.html'], ['⬡', 'Aether', 'The product', 'Aether Home.dc.html'], ['⚗', 'Research', 'Hard questions we work on', 'Olympus Research.dc.html'], ['✉', 'Contact', 'Reach the team', 'Contact.dc.html?brand=olympus']],
  aether: [['⬡', 'Aether home', 'What Aether does', 'Aether Home.dc.html'], ['⌘', 'Documentation', 'Guides, SDKs, and integrations', 'Docs.dc.html'], ['◉', 'Status', 'Is everything working?', 'Status.dc.html'], ['✉', 'Contact', 'Ask an engineer', 'Contact.dc.html?brand=aether&type=developer']],
};

export function NotFoundPage() {
  const link = useLink();
  usePageMeta('not-found');
  const { site } = useSite();
  const { pathname } = useLocation();
  const brand = site;
  const path = pathname;
  // Pilot-only builds have no public status page.
  const links = LINKS[brand].filter((l) => !(pilotOnly() && l[3] === 'Status.dc.html')).map(([g, title, body, href]) => ({ g, title, body, href }));
  return (
    <div className="dc pg-not-found">
    <div data-page="not-found" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans); display: flex; flex-direction: column;")}>
      <SiteHeader brand={brand} active="" />
      <main style={css("flex: 1; max-width: 1200px; width: 100%; box-sizing: border-box; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 40px;")}>
        <div style={css("display: flex; flex-direction: column; align-items: center; gap: 18px; max-width: 640px;")}>
          <span style={css("display: inline-flex; align-items: center; gap: 10px;")}>
            <span style={css("font-family: var(--font-mono); font-size: 13px; color: #6b6a65;")}>
              {"404"}
            </span>
            <code style={css("font-size: 12px; color: #6b6a65; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 360px;")}>
              {path}
            </code>
          </span>
          <h1 style={css("font-size: clamp(44px, 7vw, 88px); font-weight: 500; letter-spacing: -0.045em; line-height: 0.98; margin: 0;")}>
            {"This page doesn’t exist."}
          </h1>
          <p style={css("font-size: 16px; line-height: 1.6; color: #4a4945; margin: 0;")}>
            {"The link may be old, or the page may have moved."}
          </p>
        </div>
        <nav aria-label="Go somewhere else" style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px 28px;")}>
          {(links).map((l: any, lIndex: number) => (
            <Fragment key={lIndex}>
              <a href={link(l.href)} style={css("display: inline-flex; gap: 6px; font-size: 15px; font-weight: 500; color: #1a1a1e; text-decoration: none;")} className="hv-cc8e330e">
                {l.title}
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"→"}
                </span>
              </a>
            </Fragment>
          ))}
        </nav>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
