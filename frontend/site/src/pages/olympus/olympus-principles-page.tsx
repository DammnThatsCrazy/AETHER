/**
 * Built from design/designs/Olympus Principles.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-principles-page.css';

const RULES = [['I', 'Help people decide. Don’t decide for them.', 'Technology should make human judgment better informed, not take its place.'], ['II', 'Be able to explain everything.', 'Every answer should come with the reasons behind it, and be open to review.'], ['III', 'People stay in charge of AI.', 'However capable an agent is, a person can always see what it did and stop it.'], ['IV', 'Stay within the law and within consent.', 'If someone hasn’t agreed, their data isn’t used.'], ['V', 'Trust comes first.', 'Without it, nothing else here matters.']].map(([n, t, b]) => ({ n, t, b }));
const MAY = ['Recommend', 'Spot patterns', 'Predict', 'Explain'];
const MAY_NOT = ['Take big, irreversible actions without a person', 'Work outside agreed rules', 'Take people out of important decisions'];

export function OlympusPrinciplesPage() {
  const link = useLink();
  usePageMeta('olympus-principles');
  const rules = RULES;
  const may = MAY;
  const mayNot = MAY_NOT;
  return (
    <div className="dc pg-olympus-principles">
    <div data-page="olympus-principles" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Company" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Principles"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.6vw, 104px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 900px; text-wrap: balance;")}>
              {"Five rules."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 540px;")}>
              {"They decide what Olympus builds, how it treats data, and where people stay in charge. When two conflict, the earlier one wins."}
            </p>
          </div>
        </section>
        <section style={css("border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1000px; margin: 0 auto; padding: 0 24px clamp(80px, 11vw, 144px);")}>
            <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column;")}>
              {(rules).map((r: any, rIndex: number) => (
                <Fragment key={rIndex}>
                  <li style={css("display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 24px; align-items: baseline; padding: clamp(28px, 4vw, 44px) 0; border-bottom: 1px solid #d8d6d0;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 13px; color: #9c9b95;")}>
                      {r.n}
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 10px;")}>
                      <span style={css("font-size: clamp(24px, 3vw, 36px); font-weight: 500; letter-spacing: -0.025em; line-height: 1.15;")}>
                        {r.t}
                      </span>
                      <span style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; max-width: 600px;")}>
                        {r.b}
                      </span>
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: clamp(32px, 5vw, 72px);")}>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #9cc4a9;")}>
                {"Aether may"}
              </span>
              {(may).map((m: any, mIndex: number) => (
                <Fragment key={mIndex}>
                  <span style={css("font-size: clamp(20px, 2.2vw, 26px); font-weight: 500; letter-spacing: -0.02em; color: #e8e6e1;")}>
                    {m}
                  </span>
                </Fragment>
              ))}
            </div>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #e09a8f;")}>
                {"Aether may not"}
              </span>
              {(mayNot).map((m: any, mIndex: number) => (
                <Fragment key={mIndex}>
                  <span style={css("font-size: clamp(20px, 2.2vw, 26px); font-weight: 500; letter-spacing: -0.02em; color: #8a8984; line-height: 1.3;")}>
                    {m}
                  </span>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 720px; text-wrap: balance;")}>
              {"Ask how any of these is enforced."}
            </h2>
            <a href={link("Contact.dc.html?brand=olympus&type=security")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
              {"Request a review"}
              <span style={css("font-family: var(--font-mono);")}>
                {"→"}
              </span>
            </a>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
