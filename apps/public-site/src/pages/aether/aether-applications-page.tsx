/**
 * Built from design/designs/Aether Applications.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, portalLabel, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-applications-page.css';

type App = [id: string, g: string, title: string, col: string, headline: string, problem: string, flow: string[], outcome: string, surfaces: string[], href: string, cta: string];
const APPS: App[] = [
  ['customer', '●', 'Customer intelligence', '#3a6896', 'Eight events. One explainable history.', 'Web, CRM, email, Stripe, and support each know a piece of the customer. None know the whole.', ['A person sees an ad', 'Visits anonymously', 'Creates an account', 'Uses the mobile app', 'Speaks with an AI agent', 'Receives an email', 'Buys a product', 'Contacts support'], 'Aether recognizes the relationship between all eight events and provides one explainable history.', ['Profiles', 'Profile 360', 'Journeys', 'Timeline'], 'Aether Customer Intelligence.dc.html', 'Open the customer scenario'],
  ['revenue', '↑', 'Revenue intelligence', '#4f7a5e', 'Where did this value come from?', 'Revenue lands in payments. The campaigns, messages, and journeys that produced it live elsewhere.', ['Campaign', 'Interaction', 'Person', 'Journey', 'Conversion', 'Revenue'], 'Value is traced backward through the relationships that produced it, with credit and uncertainty shown.', ['Value', 'Attribution', 'Value lens', 'Journeys'], 'Aether Lenses.dc.html', 'Apply a value lens'],
  ['agents', '⬡', 'Agent intelligence', '#a8783e', 'Who acted, under whose authority, with what result.', 'Agent runtimes log tasks. Applications log actions. Nothing joins an instruction to its outcome.', ['Human instruction', 'Orchestrator', 'Research, data, and execution agents', 'Application', 'Customer action', 'Outcome'], 'Aether preserves who created whom, who had authority, what tools were used, and what resulted.', ['Agents', 'Agent 360', 'Authority lens', 'Evidence'], 'Aether Agents.dc.html', 'See agent lineage'],
  ['communications', '✉', 'Communications', '#5a85a8', 'Not another inbox.', 'Email, SMS, support, and agent conversations sit in separate tools, detached from the relationships they belong to.', ['Email opened', 'SMS clicked', 'Support replied', 'Agent conversation', 'Placed on the journey timeline'], 'Communications become part of the relationship history — positioned in the journey where they happened.', ['Communications 360', 'Timeline', 'Profiles'], 'Docs.dc.html?page=communications', 'Read about communications'],
  ['risk', '▲', 'Risk and trust', '#a3473c', 'Risk emerges from relationships.', 'Each account looks healthy alone. The pattern only appears across accounts, devices, and payments.', ['Account A', 'Shared device', 'Account B', 'Refund pattern', 'Payment', 'Risk signal with confidence'], 'Observed evidence and inferred risk are kept visually and structurally separate — evidence ≠ inference.', ['Risk', 'Graph', 'Evidence states', 'Risk lens'], 'Docs.dc.html?page=evidence-states', 'How evidence states work'],
  ['operations', '◉', 'Operations', '#7d6538', 'What is happening now — and how it compares to before.', 'Operational activity is spread across systems, agents, and teams with no shared timeline.', ['Activity arrives', 'Entities recognized', 'Compared to history', 'Change surfaced', 'Investigated'], 'One temporal model of activity across people, agents, and systems — so change is visible as it happens.', ['Signals', 'Timeline', 'Temporal lens'], 'Aether Platform.dc.html#explore', 'Explore the timeline'],
];

export function AetherApplicationsPage() {
  const link = useLink();
  usePageMeta('aether-applications');
  const apps = APPS.map(([id, g, title, col, headline, problem, flow, outcome, surfaces, href, cta], i) => ({
    id, g, title, headline, problem, outcome, surfaces, href, cta, n: '0' + (i + 1), jump: '#' + id,
    gStyle: 'font-family: var(--font-mono); color: ' + col + ';',
    kStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + col + ';',
    bg: 'border-bottom: 1px solid #d8d6d0; background: ' + (i % 2 ? '#eceae5' : '#f5f4f1') + ';',
    flow: flow.map((l, j) => {
      const last = j === flow.length - 1;
      return { l, dot: 'width: 7px; height: 7px; margin-left: -4px; border-radius: 999px; flex-shrink: 0; ' + (last ? 'background: ' + col + ';' : 'background: #f5f4f1; border: 1px solid #9c9b95; box-sizing: border-box;'), tStyle: 'font-size: 15px; ' + (last ? 'font-weight: 500; color: #1a1a1e;' : 'color: #4a4945;') };
    }),
  }));
  return (
    <div className="dc pg-aether-applications">
    <div data-page="aether-applications" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Applications" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Applications"}
            </span>
            <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; max-width: 960px; text-wrap: balance;")}>
              {"What can you do with Aether?"}
            </h1>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 620px;")}>
              {"Aether isn’t a different product for every team. It’s one product, used in different situations. Each one starts with scattered data and ends with one clear story."}
            </p>
            <nav aria-label="Applications" style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 6px; margin-top: 8px;")}>
              {(apps).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <a href={link(a.jump)} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 36px; padding: 0 14px; border-radius: 999px; font-size: 13px; font-weight: 500; text-decoration: none; background: #eceae5; border: 1px solid #d8d6d0; color: #1a1a1e;")} className="hv-4d1362f5">
                    <span style={css(a.gStyle)}>
                      {a.g}
                    </span>
                    {a.title}
                  </a>
                </Fragment>
              ))}
            </nav>
          </div>
        </section>
        {(apps).map((a: any, aIndex: number) => (
          <Fragment key={aIndex}>
            <section id={a.id} style={css("border-top: 1px solid #d8d6d0;")}>
              <div style={css("max-width: 1100px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: clamp(32px, 5vw, 80px); align-items: start;")}>
                <div style={css("display: flex; flex-direction: column; gap: 14px;")}>
                  <span style={css(a.kStyle)}>
                    {a.n}{" · "}{a.title}
                  </span>
                  <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0; text-wrap: balance;")}>
                    {a.headline}
                  </h2>
                  <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                    {a.outcome}
                  </p>
                  <a href={link(a.href)} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; margin-top: 4px;")} className="hv-cc8e330e">
                    {a.cta}
                    <span style={css("font-family: var(--font-mono);")}>
                      {"→"}
                    </span>
                  </a>
                </div>
                <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-left: 1px solid #d8d6d0;")}>
                  {(a.flow).map((f: any, fIndex: number) => (
                    <Fragment key={fIndex}>
                      <li style={css("display: flex; align-items: center; gap: 14px; padding: 7px 0;")}>
                        <span style={css(f.dot)} />
                        <span style={css(f.tStyle)}>
                          {f.l}
                        </span>
                      </li>
                    </Fragment>
                  ))}
                </ol>
              </div>
            </section>
          </Fragment>
        ))}
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"Same Aether. Different questions."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Lenses.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"See lenses"}
              </a>
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
