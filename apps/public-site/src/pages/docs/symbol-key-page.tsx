/**
 * Built from design/designs/Symbol Key.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './symbol-key-page.css';

const m = (g: string, k: string, v: string, c?: string) => ({ g, k, v, style: 'font-family: var(--font-mono); font-size: 22px; color: ' + (c || '#e8e6e1') + ';' });
const GROUPS = [
  { title: 'Things', rows: [m('●', 'Person', 'A human.', '#9fbad6'), m('⬡', 'Agent', 'Software acting for someone.', '#dcb683'), m('◈', 'Company', 'An organization.', '#c9b088'), m('○', 'System', 'An app, tool, or service.', '#8fb0cc'), m('□', 'Device', 'A phone, browser, or machine.', '#a09f99'), m('↑', 'Value', 'Money or worth.', '#9cc4a9')] },
  { title: 'Connections', rows: [m('→', 'Movement', 'Something happened, or was handed on.'), m('↔', 'Relationship', 'Two things are linked.'), m('— solid', 'Seen', 'Aether saw this happen.'), m('- - dashed', 'Worked out', 'Aether inferred this from evidence.'), m('thick / faint', 'Strength', 'Strong evidence is thick. Weak is faint.')] },
  { title: 'States', rows: [m('●', 'Observed', 'Something directly occurred.', '#9fbad6'), m('↔', 'Resolved', 'Records were matched as one.', '#9fbad6'), m('✓', 'Verified', 'The expected effect was seen.', '#9cc4a9'), m('▲', 'Risk', 'Worth a closer look.', '#e09a8f'), m('■', 'Problem', 'Something is wrong or stopped.', '#e09a8f')] },
];

export function SymbolKeyPage() {
  const link = useLink();
  usePageMeta('symbol-key');
  const groups = GROUPS;
  return (
    <div className="dc pg-symbol-key">
    <div data-page="symbol-key" data-theme="dark" style={css("min-height: 100vh; background: #111114; color: #e8e6e1; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Developers" />
      <main style={css("max-width: 760px; margin: 0 auto; padding: clamp(80px, 12vw, 152px) 24px clamp(72px, 10vw, 128px); display: flex; flex-direction: column; gap: 56px;")}>
        <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px;")}>
          <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
            <a href={link("Docs.dc.html")} style={css("color: #a09f99; text-decoration: none;")}>
              {"Docs"}
            </a>
            <span>
              {"/"}
            </span>
            <span style={css("color: #e8e6e1;")}>
              {"Symbol key"}
            </span>
          </span>
          <h1 style={css("font-size: clamp(40px, 6vw, 72px); font-weight: 500; line-height: 0.98; letter-spacing: -0.045em; margin: 0; color: #e8e6e1;")}>
            {"One small alphabet."}
          </h1>
          <p style={css("font-size: 16px; line-height: 1.6; color: #a09f99; margin: 0; max-width: 480px;")}>
            {"The same symbols mean the same thing everywhere in Aether."}
          </p>
        </div>
        {(groups).map((g: any, gIndex: number) => (
          <Fragment key={gIndex}>
            <section style={css("display: flex; flex-direction: column;")}>
              <h2 style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99; margin: 0 0 12px;")}>
                {g.title}
              </h2>
              <div style={css("border-top: 1px solid #2a2a2f;")}>
                {(g.rows).map((r: any, rIndex: number) => (
                  <Fragment key={rIndex}>
                    <div style={css("display: grid; grid-template-columns: 72px 140px minmax(0, 1fr); gap: 16px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid #2a2a2f;")}>
                      <span style={css(r.style)}>
                        {r.g}
                      </span>
                      <span style={css("font-size: 16px; font-weight: 500;")}>
                        {r.k}
                      </span>
                      <span style={css("font-size: 14px; line-height: 1.5; color: #a09f99;")}>
                        {r.v}
                      </span>
                    </div>
                  </Fragment>
                ))}
              </div>
            </section>
          </Fragment>
        ))}
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
