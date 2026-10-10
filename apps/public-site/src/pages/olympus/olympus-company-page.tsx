/**
 * Built from design/designs/Olympus Company.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-company-page.css';

const FACTS = [['What we make', 'Aether — one product, used across many kinds of business.'], ['Where we started', 'Online retail: lots of activity, scattered customer data, and results that are quick to measure.'], ['How we work', 'Careful, honest, and unflashy. Claims only what it can show.'], ['What we won’t do', 'Secret monitoring of people, political targeting, or sharing one customer’s data with another.']].map(([k, v]) => ({ k, v }));

export function OlympusCompanyPage() {
  const link = useLink();
  usePageMeta('olympus-company');
  const facts = FACTS;
  return (
    <div className="dc pg-olympus-company">
    <div data-page="olympus-company" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Company" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(72px, 10vw, 128px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h1 style={css("font-size: clamp(48px, 7.6vw, 104px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 960px; text-wrap: balance;")}>
              {"Building for a world where people and AI work together."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 580px;")}>
              {"Olympus Labs is a research and engineering company. We build technology that helps organizations see how their people, tools, and AI agents connect — and keep people in charge of what happens next."}
            </p>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 900px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; gap: 28px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
              {"Why Olympus exists"}
            </span>
            <p style={css("font-size: clamp(26px, 3.2vw, 40px); font-weight: 500; letter-spacing: -0.025em; line-height: 1.22; margin: 0; color: #e8e6e1; text-wrap: pretty;")}>
              {"More and more work happens between people and AI agents. "}
              <span style={css("color: #8a8984;")}>
                {"Most tools only see their own piece of it. The organizations that see the whole picture — and stay in control of it — will do best."}
              </span>
            </p>
          </div>
        </section>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(40px, 6vw, 96px); align-items: start;")}>
            <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
              {"How Olympus works"}
            </h2>
            <dl style={css("margin: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(facts).map((x: any, xIndex: number) => (
                <Fragment key={xIndex}>
                  <div style={css("display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 20px; align-items: baseline; padding: 22px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <dt style={css("font-size: 17px; font-weight: 500;")}>
                      {x.k}
                    </dt>
                    <dd style={css("margin: 0; font-size: 15px; line-height: 1.6; color: #4a4945;")}>
                      {x.v}
                    </dd>
                  </div>
                </Fragment>
              ))}
            </dl>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 720px; text-wrap: balance;")}>
              {"Talk to the team."}
            </h2>
            <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 480px;")}>
              {"Partnerships, research, security reviews, or a question you want answered."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=olympus")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Get in touch"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("mailto:team@olympuslabsml.com")} style={css("display: inline-flex; align-items: center; min-height: 46px; padding: 0 22px; border-radius: 6px; font-family: var(--font-mono); font-size: 13px; text-decoration: none; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"team@olympuslabsml.com"}
              </a>
            </div>
            <nav aria-label="More" style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 24px; margin-top: 24px; font-size: 13px;")}>
              <a href={link("Olympus Principles.dc.html")} style={css("color: #6b6a65; text-decoration: none;")} className="hv-75877933">
                {"Principles"}
              </a>
              <a href={link("Olympus Research.dc.html")} style={css("color: #6b6a65; text-decoration: none;")} className="hv-75877933">
                {"Research"}
              </a>
              <a href={link("Olympus Stories.dc.html")} style={css("color: #6b6a65; text-decoration: none;")} className="hv-75877933">
                {"Proof"}
              </a>
            </nav>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
