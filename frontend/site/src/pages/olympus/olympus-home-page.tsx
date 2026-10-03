/**
 * Built from design/designs/Olympus Home.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './olympus-home-page.css';

const SEES = ['contacts', 'clicks', 'payments', 'tasks'];
const BUILDS = ['who someone is', 'what they did', 'who they’re connected to', 'what changed over time', 'who was in charge', 'what it was worth'];
const LAYERS = [['Olympus Labs', 'The company.'], ['Aether', 'The product it builds.'], ['Uses', 'The problems Aether helps solve.'], ['Under the hood', 'The engineering that makes it work.']].map(([t, b]) => ({ t, b }));
const BELIEFS = [['I', 'Connections matter more than records.', 'How a customer, an AI agent, and a system relate tells you more than any single record can.'], ['II', 'People stay in charge.', 'Technology should help people make decisions, not make them on their own.'], ['III', 'Trust is built in.', 'Clear, explainable, and respectful of privacy from the start — not added later.']].map(([n, t, b]) => ({ n, t, b }));
const APPS = [['Customers and sales', 'who they are · how they buy'], ['People working with AI agents', 'who asked · what the agent did'], ['Automated systems', 'what’s running · what changed'], ['Trust and privacy', 'consent · proof'], ['Day-to-day operations', 'what’s happening now'], ['Revenue and payments', 'where the money came from']].map(([t, b]) => ({ t, b }));

export function OlympusHomePage() {
  const link = useLink();
  usePageMeta('olympus-home');
  const sees = SEES;
  const builds = BUILDS;
  const layers = LAYERS;
  const beliefs = BELIEFS;
  const apps = APPS;
  return (
    <div className="dc pg-olympus-home">
    <div data-page="olympus-home" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="olympus" active="" />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 16vw, 200px) 24px clamp(80px, 12vw, 160px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 28px;")}>
            <span style={css("display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              <img src={markSrc('olympus')} alt="" style={css("width: 16px; height: 16px;")} />
              {"Olympus Labs"}
            </span>
            <h1 style={css("font-size: clamp(52px, 8.6vw, 120px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 1000px; text-wrap: balance;")}>
              {"Help your systems understand each other."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 20px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 600px; text-wrap: pretty;")}>
              {"Olympus Labs builds technology that shows how the people, tools, and AI agents in a business connect — and what that means for the work."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 8px;")}>
              <a href={link("Aether Home.dc.html")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 46px; padding: 0 22px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-7e3a2e7d">
                {"Explore Aether"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Olympus Technology.dc.html")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 46px; padding: 0 22px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: transparent; color: #1a1a1e; border: 1px solid #d8d6d0; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-67a914b1">
                {"The technology"}
              </a>
            </div>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
              {"The problem"}
            </span>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; color: #e8e6e1; max-width: 820px; text-wrap: balance;")}>
              {"Your tools keep records. They miss the relationships."}
            </h2>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 0; margin-top: 40px; text-align: left; border-top: 1px solid #2a2a2f;")}>
              <div style={css("display: flex; flex-direction: column; padding: 28px 32px 0 0;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65; padding-bottom: 12px;")}>
                  {"What most tools see"}
                </span>
                {(sees).map((s: any, sIndex: number) => (
                  <Fragment key={sIndex}>
                    <span style={css("font-size: clamp(22px, 2.4vw, 30px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.5; color: #8a8984;")}>
                      {s}
                    </span>
                  </Fragment>
                ))}
              </div>
              <div style={css("display: flex; flex-direction: column; padding: 28px 0 0 32px; border-left: 1px solid #2a2a2f;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #dcb683; padding-bottom: 12px;")}>
                  {"What actually matters"}
                </span>
                {(builds).map((s: any, sIndex: number) => (
                  <Fragment key={sIndex}>
                    <span style={css("font-size: clamp(22px, 2.4vw, 30px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.5; color: #e8e6e1;")}>
                      {s}
                    </span>
                  </Fragment>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(40px, 6vw, 96px); align-items: center;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                <img src={markSrc('aether')} alt="" style={css("width: 16px; height: 16px;")} />
                {"The product"}
              </span>
              <h2 style={css("font-size: clamp(32px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Meet Aether."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.65; color: #4a4945; margin: 0; max-width: 480px;")}>
                {"Aether pulls activity from the tools you already use and joins it into one clear picture: what happened, who was involved, how it all connects, and what to do next."}
              </p>
              <a href={link("Aether Home.dc.html")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; margin-top: 4px;")} className="hv-cc8e330e">
                {"Meet Aether"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
            <dl style={css("margin: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(layers).map((l: any, lIndex: number) => (
                <Fragment key={lIndex}>
                  <div style={css("display: grid; grid-template-columns: 140px minmax(0, 1fr); gap: 20px; align-items: baseline; padding: 22px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <dt style={css("font-size: 17px; font-weight: 500; letter-spacing: -0.2px;")}>
                      {l.t}
                    </dt>
                    <dd style={css("margin: 0; font-size: 15px; line-height: 1.55; color: #4a4945;")}>
                      {l.b}
                    </dd>
                  </div>
                </Fragment>
              ))}
            </dl>
          </div>
        </section>
        <section id="applications" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(40px, 6vw, 96px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                {"Where it applies"}
              </span>
              <h2 style={css("font-size: clamp(32px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Built for teams where people and AI work side by side."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.65; color: #4a4945; margin: 0; max-width: 440px;")}>
                {"A few of the places this technology helps."}
              </p>
            </div>
            <ul style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(apps).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <li style={css("display: flex; justify-content: space-between; align-items: baseline; gap: 16px; padding: 18px 0; border-bottom: 1px solid #d8d6d0;")}>
                    <span style={css("font-size: 18px; font-weight: 500; letter-spacing: -0.2px;")}>
                      {a.t}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65; text-align: right;")}>
                      {a.b}
                    </span>
                  </li>
                </Fragment>
              ))}
            </ul>
          </div>
        </section>
        <section style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; gap: 40px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Why the approach is different"}
            </span>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: clamp(32px, 4vw, 56px);")}>
              {(beliefs).map((b: any, bIndex: number) => (
                <Fragment key={bIndex}>
                  <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                      {b.n}
                    </span>
                    <span style={css("font-size: clamp(20px, 2vw, 24px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.3;")}>
                      {b.t}
                    </span>
                    <span style={css("font-size: 14px; line-height: 1.6; color: #6b6a65;")}>
                      {b.b}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 168px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"Start with a question you can’t answer today."}
            </h2>
            <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 520px;")}>
              {"Tell us what you want to understand, where the data lives, and what a good result would look like."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=olympus&type=pilot")} style={css("display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; min-height: 46px; padding: 0 22px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Start a conversation"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Olympus Company.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; min-height: 46px; padding: 0 22px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: transparent; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"About Olympus Labs"}
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
