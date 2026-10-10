/**
 * Built from design/designs/Olympus Stories.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-stories-page.css';

const FIVE = [['The question', 'What the team wanted to understand, and where they started.'], ['The data', 'Which tools were connected, and how ready they were.'], ['The answer', 'What Aether showed — including what it wasn’t sure about.'], ['The decision', 'Who decided what, and when.'], ['The result', 'What changed, and how it was measured.']].map(([t, b], i) => ({ t, b, n: '0' + (i + 1) }));

export function OlympusStoriesPage() {
  const link = useLink();
  usePageMeta('olympus-stories');
  const five = FIVE;
  return (
    <div className="dc pg-olympus-stories">
    <div data-page="olympus-stories" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="Company" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Proof"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.6vw, 104px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 900px; text-wrap: balance;")}>
              {"Has this actually worked?"}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 560px;")}>
              {"No customer stories are published yet. They appear here only once a partner approves them — and each one has to show the same five things."}
            </p>
          </div>
        </section>
        <section style={css("border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px clamp(80px, 11vw, 144px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(40px, 6vw, 96px); align-items: start;")}>
            <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
              {"Every story shows"}
            </h2>
            <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(five).map((x: any, xIndex: number) => (
                <Fragment key={xIndex}>
                  <li style={css("display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 16px; align-items: baseline; padding: 20px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                      {x.n}
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                      <span style={css("font-size: 19px; font-weight: 500;")}>
                        {x.t}
                      </span>
                      <span style={css("font-size: 14px; color: #6b6a65;")}>
                        {x.b}
                      </span>
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 720px; color: #e8e6e1; text-wrap: balance;")}>
              {"Be the first proof partner."}
            </h2>
            <p style={css("font-size: 16px; line-height: 1.6; color: #a09f99; margin: 0; max-width: 480px;")}>
              {"Bring your own data and a result you want to measure. You get a named contact and a written plan."}
            </p>
            <a href={link("Contact.dc.html?brand=olympus&type=proof")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #e8e6e1; color: #111114;")} className="hv-a07ac886">
              {"Become a proof partner"}
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
