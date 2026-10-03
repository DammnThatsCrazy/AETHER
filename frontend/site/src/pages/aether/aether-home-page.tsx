/**
 * Built from design/designs/Aether Home.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, portalLabel, useDesignState, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { usePageMeta } from '@site/design/page-meta';
import { AetherScene } from '@site/components/aether-scene';
import { IOSDevice } from '@site/components/ios-device';
import { Profile360 } from '@site/components/profile-360';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import { CONNECT_CONNECTORS } from './aether-connect';
import './aether-home-page.css';

import { useEffect } from 'react';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const STEPS: [kicker: string, title: string, body: string, chips: string][] = [
  ['Disconnected activity', 'Your systems know pieces of the story.', 'An ad platform, a website, a mobile app, an email tool, a support agent, a payment processor. Each keeps its own record — and none of them knows the others exist.', 'GA4 · HubSpot · Stripe · App · Agent'],
  ['Aether connects them', 'Aether understands how those pieces belong together.', 'Aether recognizes that seven separate records are really one person. Things it saw directly are solid lines; things it worked out are dashed.', 'one person · seven records'],
  ['Add time', 'Then turns activity into history and journeys.', 'Put in order, those records become a story — from the first ad to the support ticket.', 'timeline · journeys'],
  ['Add intelligence', 'Explore the same reality from any perspective.', 'Same data, different angle. Switch to the value view and the moments that led to the sale stand out.', 'views · value · credit'],
];
const MODEL: [n: string, g: string, title: string, body: string, feats: string[], href: string, c: string, soft: string][] = [
  ['01', '→', 'Connect', 'Bring together activity from the applications, platforms, devices, agents, providers, and systems you already use.', ['Connectors', 'SDKs', 'APIs', 'Events'], 'Aether Connect.dc.html', '#3a6896', 'rgba(58,104,150,0.12)'],
  ['02', '⬡', 'Understand', 'Aether identifies the people, agents, organizations, events, relationships, and value behind that activity.', ['Profiles', 'Identity', 'Relationships', 'Signals'], 'Aether Platform.dc.html#understand', '#4f7a5e', 'rgba(107,154,124,0.16)'],
  ['03', '↔', 'Explore', 'Follow a person, journey, interaction, campaign, agent, relationship, location, or transaction through a connected model instead of searching across separate tools.', ['Graph', 'Journeys', 'Lenses', '360s', 'Timeline'], 'Aether Platform.dc.html#explore', '#8a6433', 'rgba(201,151,90,0.18)'],
  ['04', '✓', 'Act', 'Use that understanding to make decisions, automate actions, investigate changes, personalize experiences, measure outcomes, or give agents reliable context.', ['Recommendations', 'Agents', 'Communications', 'Risk', 'Outcomes'], 'Aether Platform.dc.html#act', '#a3473c', 'rgba(181,86,74,0.12)'],
];
const QUESTIONS: [q: string, a: string, g: string, c: string, href: string][] = [
  ['Who is this?', 'Profiles', '⬡', '#5a85a8', 'Aether Platform.dc.html#understand'],
  ['What happened?', 'Signals', '◉', '#4f7a5e', 'Aether Platform.dc.html#understand'],
  ['How did they get here?', 'Journeys', '→', '#4f7a5e', 'Aether Platform.dc.html#explore'],
  ['What is related?', 'Graph', '↔', '#3a6896', 'Aether Platform.dc.html#explore'],
  ['What changed over time?', 'Timeline', '◷', '#6b6a65', 'Aether Platform.dc.html#explore'],
  ['What influenced this outcome?', 'Attribution and value', '↑', '#4f7a5e', 'Aether Platform.dc.html#act'],
  ['What does this look like from another perspective?', 'Lenses', '◈', '#8a6433', 'Aether Lenses.dc.html'],
  ['What did the agent do?', 'Agent 360', '⬡', '#a8783e', 'Aether Agents.dc.html'],
  ['What communication occurred?', 'Communications', '✉', '#5a85a8', 'Aether Platform.dc.html#act'],
  ['Where is the risk?', 'Risk', '▲', '#a3473c', 'Aether Platform.dc.html#act'],
];
const SCENARIOS: [title: string, g: string, c: string, flow: string[], close: string, href: string][] = [
  ['Understand a customer', '●', '#3a6896', ['Ad impression', 'Website visit', 'Mobile app', 'Email interaction', 'AI agent conversation', 'Purchase', 'Support interaction'], 'Aether understands that as one connected journey rather than seven unrelated records.', 'Aether Customer Intelligence.dc.html'],
  ['Understand an agent', '⬡', '#a8783e', ['Human instruction', 'Orchestrator', 'Research, data, and execution agents', 'Application', 'Customer action', 'Outcome'], 'Aether preserves who acted, under whose authority, against what system, and what resulted.', 'Aether Agents.dc.html'],
  ['Understand value', '↑', '#4f7a5e', ['Campaign', 'Interaction', 'Person', 'Journey', 'Conversion', 'Revenue'], 'Now attribution and value flows make intuitive sense.', 'Aether Applications.dc.html#revenue'],
];
const APPS: [g: string, title: string, body: string, c: string, href: string][] = [
  ['●', 'Customer intelligence', 'One explainable history per customer, across every system.', '#9fbad6', 'Aether Customer Intelligence.dc.html'],
  ['↑', 'Revenue intelligence', 'The path from first signal to revenue, and what put it at risk.', '#9cc4a9', 'Aether Applications.dc.html#revenue'],
  ['⬡', 'Agent intelligence', 'Who created whom, under whose authority, with what result.', '#dcb683', 'Aether Agents.dc.html'],
  ['✉', 'Communications', 'Messages as part of the relationship history, not another inbox.', '#8fb0cc', 'Aether Applications.dc.html#communications'],
  ['▲', 'Risk and trust', 'How risk emerges from relationships — evidence separate from inference.', '#e09a8f', 'Aether Applications.dc.html#risk'],
  ['◉', 'Operations', 'What is happening now, and how it compares to before.', '#c9b088', 'Aether Applications.dc.html#operations'],
];

export function AetherHomePage() {
  const link = useLink();
  usePageMeta('aether-home');
  // Width starts at the prerender default and updates after mount, so the
  // static HTML and the first client render agree.
  const [state, setState] = useDesignState<{ stage: number; w: number }>({ stage: 0, w: 1280 });
  useEffect(() => {
    const onR = () => setState({ w: window.innerWidth });
    const onS = () => {
      const els = document.querySelectorAll('[data-step]');
      if (!els.length) return;
      const mid = window.innerHeight * 0.5;
      let best = 0;
      let bd = Infinity;
      els.forEach((el) => {
        const r = el.getBoundingClientRect();
        const d = Math.abs(r.top + r.height / 2 - mid);
        if (d < bd) {
          bd = d;
          best = Number(el.getAttribute('data-step'));
        }
      });
      setState((s) => (best !== s.stage ? { stage: best } : {}));
    };
    onR();
    window.addEventListener('resize', onR);
    window.addEventListener('scroll', onS, { passive: true });
    const t = setTimeout(onS, 300);
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', onR);
      window.removeEventListener('scroll', onS);
    };
  }, [setState]);
  const st = state.stage;
  const narrow = state.w < 1000;
  const steps = STEPS.map(([kicker, title, body, chips], i) => ({
    i, n: '0' + (i + 1), kicker, title, body, chips,
    style: 'min-height: ' + (narrow ? 'auto' : '64vh') + '; display: flex; flex-direction: column; justify-content: center; gap: 12px; padding: ' + (narrow ? '28px 0' : '0') + '; border-left: 2px solid ' + (i === st ? '#c9975a' : '#2a2a2f') + '; padding-left: 24px; opacity: ' + (i === st || narrow ? 1 : 0.38) + '; transition: opacity 320ms ' + EASE + ', border-color 200ms ' + EASE + ';',
  }));
  const scrollStage = narrow ? null : st;
  const stageLabel = ['01 · fragmented', '02 · connected', '03 · history', '04 · value lens'][st];
  const bars = [0, 1, 2, 3].map((i) => 'height: 2px; border-radius: 2px; background: ' + (i <= st ? '#c9975a' : '#2a2a2f') + '; transition: background-color 200ms ' + EASE + ';');
  const stickyStyle = narrow ? 'position: relative; order: -1;' : 'position: sticky; top: calc(50vh - 290px); margin-top: 18vh;';
  const model = MODEL.map(([n, g, title, body, feats, href, c]) => ({
    n, g, title, body, href, featLine: feats.join(' · '),
    gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';',
    style: 'display: flex; flex-direction: column; gap: 12px; padding-top: 20px; border-top: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: border-color 200ms cubic-bezier(0.22,1,0.36,1);',
  }));
  const questions = QUESTIONS.map(([q, a, g, c, href]) => ({ q, a, g, href, dot: 'width: 6px; height: 6px; border-radius: 999px; flex-shrink: 0; transform: translateY(-3px); background: ' + c + ';', aStyle: 'font-size: 13px; font-weight: 500; white-space: nowrap; color: ' + c + ';' }));
  const scenarios = SCENARIOS.map(([title, g, c, flow, close, href]) => ({
    title, close, href, gStyle: 'font-family: var(--font-mono); color: ' + c + ';',
    topStyle: 'display: flex; flex-direction: column; gap: 20px; padding-top: 20px; border-top: 2px solid ' + c + '; text-decoration: none; color: #1a1a1e;',
    lineStyle: 'display: flex; flex-direction: column; border-left: 1px solid ' + c + '66;',
    arrowStyle: 'font-family: var(--font-mono); color: ' + c + ';',
    flow: flow.map((label, i) => {
      const last = i === flow.length - 1;
      return { label, dot: 'width: 7px; height: 7px; margin-left: -4px; border-radius: 999px; flex-shrink: 0; box-sizing: border-box; ' + (last ? 'background: ' + c + ';' : 'background: #eceae5; border: 1px solid ' + c + ';'), tStyle: 'font-size: 14px; ' + (last ? 'font-weight: 500; color: #1a1a1e;' : 'color: #4a4945;') };
    }),
  }));
  const profileParts = [['⬡', 'Identity'], ['◉', 'Timeline'], ['↔', 'Relationships'], ['→', 'Journeys'], ['↑', 'Value'], ['✓', 'Evidence']].map(([g, l]) => ({ g, l }));
  const apps = APPS.map(([g, title, body, c, href]) => ({ g, title, body, href, gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';' }));
  return (
    <div className="dc pg-aether-home">
    <div data-page="aether-home" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="" />
      <main id="main">
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 7vw, 96px) 24px clamp(48px, 7vw, 80px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: clamp(32px, 5vw, 64px); align-items: center;")}>
            <div style={css("display: flex; flex-direction: column; gap: 24px; min-width: 0;")}>
              <span style={css("display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                <img src={markSrc('aether')} alt="" style={css("width: 16px; height: 16px;")} />
                {"Aether by Olympus Labs"}
              </span>
              <h1 style={css("font-size: clamp(48px, 7vw, 88px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; color: #1a1a1e; text-wrap: balance;")}>
                {"See how everything connects."}
              </h1>
              <p style={css("font-size: 18px; line-height: 1.55; color: #4a4945; margin: 0; max-width: 500px; text-wrap: pretty;")}>
                {"Aether brings together activity from all your tools — customers, AI agents, payments, messages — into one live picture you can actually follow."}
              </p>
              <div style={css("display: flex; flex-wrap: wrap; gap: 8px; align-items: center;")}>
                <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 44px; padding: 0 20px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-979e54bc">
                  {portalLabel("Get started")}
                  <span style={css("font-family: var(--font-mono);")}>
                    {"→"}
                  </span>
                </a>
                <a href={link("Contact.dc.html?brand=aether&type=pilot")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 44px; padding: 0 20px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-dafa5f55">
                  {"Request a pilot"}
                </a>
                <a href={link("Aether How It Works.dc.html")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; padding: 0 8px;")} className="hv-cc8e330e">
                  {"See how Aether works"}
                  <span style={css("font-family: var(--font-mono);")}>
                    {"→"}
                  </span>
                </a>
              </div>
            </div>
            <div style={css("min-width: 0; background: #eceae5; border: 1px solid #d8d6d0; border-radius: 12px; padding: 20px;")}>
              <AetherScene autoplay={true} rotate={true} controls={true} story="customer" />
            </div>
          </div>
          <div style={css("border-top: 1px solid #d8d6d0;")}>
            <div style={css("max-width: 1200px; margin: 0 auto; padding: 0 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr));")}>
              <div style={css("display: flex; align-items: baseline; gap: 10px; padding: 22px 0;")}>
                <span style={css("font-size: 32px; font-weight: 500; letter-spacing: -0.04em; color: #2d5373;")}>
                  {"4"}
                </span>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"steps · connect, understand, explore, act"}
                </span>
              </div>
              <div style={css("display: flex; align-items: baseline; gap: 10px; padding: 22px 0 22px 24px; border-left: 1px solid #d8d6d0;")}>
                <span style={css("font-size: 32px; font-weight: 500; letter-spacing: -0.04em; color: #4f7a5e;")}>
                  {"1"}
                </span>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"picture across all your tools"}
                </span>
              </div>
              <div style={css("display: flex; align-items: baseline; gap: 10px; padding: 22px 0 22px 24px; border-left: 1px solid #d8d6d0;")}>
                <span style={css("font-size: 32px; font-weight: 500; letter-spacing: -0.04em; color: #8a6433;")}>
                  {String(CONNECT_CONNECTORS.length)}
                </span>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"ready-made integrations"}
                </span>
              </div>
              <div style={css("display: flex; align-items: baseline; gap: 10px; padding: 22px 0 22px 24px; border-left: 1px solid #d8d6d0;")}>
                <span style={css("font-size: 32px; font-weight: 500; letter-spacing: -0.04em; color: #7d6538;")}>
                  {"4"}
                </span>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"SDKs for web and mobile"}
                </span>
              </div>
            </div>
          </div>
        </section>
        <section id="story" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px 0; display: flex; flex-direction: column; gap: 12px; max-width: 1200px;")}>
            <span style={css("display: inline-flex; align-items: center; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
              <span style={css("font-family: var(--font-mono); color: #c9975a;")}>
                {"◉"}
              </span>
              {"From fragmented to connected"}
            </span>
            <h2 style={css("font-size: clamp(32px, 4.4vw, 56px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.02; margin: 0; color: #e8e6e1; max-width: 760px; text-wrap: balance;")}>
              {"Something happened. Aether works out what it means."}
            </h2>
          </div>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: 36px 24px clamp(64px, 9vw, 112px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(24px, 5vw, 72px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column;")}>
              {(steps).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <div data-step={s.i} style={css(s.style)}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #c9975a;")}>
                      {s.n}{" · "}{s.kicker}
                    </span>
                    <span style={css("font-size: clamp(24px, 2.6vw, 32px); font-weight: 500; letter-spacing: -0.02em; line-height: 1.15; color: #e8e6e1; text-wrap: balance;")}>
                      {s.title}
                    </span>
                    <span style={css("font-size: 15px; line-height: 1.6; color: #a09f99; max-width: 440px;")}>
                      {s.body}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
                      {s.chips}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
            <div style={css(stickyStyle)}>
              <div style={css("border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 20px; display: flex; flex-direction: column; gap: 14px;")}>
                <div style={css("display: flex; justify-content: space-between; align-items: center; gap: 8px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Understand a customer"}
                  </span>
                  <span style={css("font-family: var(--font-mono); font-size: 11px; color: #c9975a;")}>
                    {stageLabel}
                  </span>
                </div>
                <AetherScene dark={true} story="customer" stage={scrollStage} autoplay={true} controls={false} />
                <div style={css("display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px;")}>
                  {(bars).map((b: any, bIndex: number) => (
                    <Fragment key={bIndex}>
                      <span style={css(b)} />
                    </Fragment>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </section>
        <section id="model" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1100px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; align-items: center; gap: clamp(40px, 6vw, 72px);")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px;")}>
              <h2 style={css("font-size: clamp(32px, 4.6vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-wrap: balance;")}>
                {"Connect. Understand. Explore. Act."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 480px;")}>
                {"Aether does four things. Everything in the product fits into one of them."}
              </p>
            </div>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: clamp(24px, 3vw, 40px);")}>
              {(model).map((m: any, mIndex: number) => (
                <Fragment key={mIndex}>
                  <a href={link(m.href)} style={css(m.style)} className="hv-580d1153">
                    <span style={css("display: flex; align-items: baseline; gap: 10px;")}>
                      <span style={css(m.gStyle)}>
                        {m.g}
                      </span>
                      <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                        {m.n}
                      </span>
                    </span>
                    <span style={css("font-size: 22px; font-weight: 500; letter-spacing: -0.33px;")}>
                      {m.title}
                    </span>
                    <span style={css("font-size: 14px; line-height: 1.6; color: #6b6a65;")}>
                      {m.body}
                    </span>
                    <span style={css("font-size: 12px; line-height: 1.6; color: #9c9b95; margin-top: auto; padding-top: 8px;")}>
                      {m.featLine}
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="understand" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; align-items: center; gap: clamp(36px, 5vw, 56px);")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px;")}>
              <h2 style={css("font-size: clamp(32px, 4.6vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-wrap: balance;")}>
                {"Ask a question. Get a clear answer."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 460px;")}>
                {"Every part of Aether answers one everyday question, from the same connected picture."}
              </p>
            </div>
            <div style={css("width: 100%; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(questions).map((q: any, qIndex: number) => (
                <Fragment key={qIndex}>
                  <a href={link(q.href)} style={css("display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: baseline; gap: 16px; padding: 16px 0; border-bottom: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: padding 200ms cubic-bezier(0.22,1,0.36,1);")} className="hv-33c6c939">
                    <span style={css("display: flex; align-items: baseline; gap: 14px;")}>
                      <span style={css(q.dot)} />
                      <span style={css("font-size: clamp(17px, 1.8vw, 21px); font-weight: 500; letter-spacing: -0.01em;")}>
                        {q.q}
                      </span>
                    </span>
                    <span style={css(q.aStyle)}>
                      <span style={css("font-family: var(--font-mono); margin-right: 6px;")}>
                        {q.g}
                      </span>
                      {q.a}{" "}
                      <span style={css("font-family: var(--font-mono);")}>
                        {"→"}
                      </span>
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="scenarios" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1100px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; align-items: center; gap: clamp(40px, 6vw, 72px);")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px;")}>
              <h2 style={css("font-size: clamp(32px, 4.6vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-wrap: balance;")}>
                {"One product. Very different stories."}
              </h2>
              <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 500px;")}>
                {"A customer’s path to purchase, an AI agent’s chain of tasks, the source of a sale — Aether follows whatever actually happened."}
              </p>
            </div>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: clamp(24px, 4vw, 56px);")}>
              {(scenarios).map((sc: any, scIndex: number) => (
                <Fragment key={scIndex}>
                  <a href={link(sc.href)} style={css(sc.topStyle)} className="hv-75877933">
                    <span style={css("font-size: 20px; font-weight: 500; letter-spacing: -0.3px;")}>
                      {sc.title}
                    </span>
                    <span style={css(sc.lineStyle)}>
                      {(sc.flow).map((f: any, fIndex: number) => (
                        <Fragment key={fIndex}>
                          <span style={css("display: flex; align-items: center; gap: 14px; padding: 6px 0;")}>
                            <span style={css(f.dot)} />
                            <span style={css(f.tStyle)}>
                              {f.label}
                            </span>
                          </span>
                        </Fragment>
                      ))}
                    </span>
                    <span style={css("font-size: 13px; line-height: 1.55; color: #6b6a65; margin-top: auto;")}>
                      {sc.close}{" "}
                      <span style={css(sc.arrowStyle)}>
                        {"→"}
                      </span>
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="product" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(32px, 5vw, 64px); align-items: center;")}>
            <div style={css("min-width: 0; display: flex; justify-content: center; align-items: flex-start;")}>
              <div style={css("zoom: 0.8; flex-shrink: 0; width: 402px; height: 874px;")}>
                <IOSDevice dark={true} style={css("display: block; width: 402px; height: 874px;")}>
                  <div style={css("padding-top: 54px; background: #000; min-height: 100%; box-sizing: border-box; display: flex; flex-direction: column;")}>
                    <Profile360 ios={true} style={css("flex: 1; display: flex; flex-direction: column;")} />
                  </div>
                </IOSDevice>
              </div>
            </div>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                {"What using it looks like"}
              </span>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Everything about one customer, in one view."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 460px;")}>
                {"Your CRM knows an email. Your analytics knows a browser. Stripe knows a customer ID. Aether figures out they’re all the same person — and shows you everything about them in one place, with the reasons why."}
              </p>
              <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 8px; max-width: 460px;")}>
                {(profileParts).map((p: any, pIndex: number) => (
                  <Fragment key={pIndex}>
                    <span style={css("display: flex; gap: 8px; font-size: 13px; padding: 10px 12px; border-radius: 6px; background: #f5f4f1; border: 1px solid #d8d6d0;")}>
                      <span style={css("font-family: var(--font-mono); color: #3a6896;")}>
                        {p.g}
                      </span>
                      {p.l}
                    </span>
                  </Fragment>
                ))}
              </div>
              <a href={link("Aether Platform.dc.html")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; margin-top: 4px;")} className="hv-cc8e330e">
                {"Explore the platform"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        <section id="applications" data-theme="dark" style={css("background: #1a1a1e; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); gap: clamp(32px, 5vw, 72px); align-items: start;")}>
            <div style={css("display: flex; flex-direction: column; gap: 16px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                {"Applications of Aether"}
              </span>
              <h2 style={css("font-size: clamp(30px, 3.8vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; color: #e8e6e1; text-wrap: balance;")}>
                {"Endless applications."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #a09f99; margin: 0; max-width: 440px;")}>
                {"Not separate products — the same Aether, pointed at different questions."}
              </p>
              <div style={css("display: flex; flex-direction: column; align-items: center; gap: 0; margin-top: 16px; padding: 24px; border: 1px solid #2a2a2f; border-radius: 12px; background: #111114; font-family: var(--font-mono); font-size: 13px; max-width: 360px; box-sizing: border-box;")}>
                <span style={css("display: flex; gap: 8px;")}>
                  <span style={css("padding: 6px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #9fbad6;")}>
                    {"● people"}
                  </span>
                  <span style={css("padding: 6px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #dcb683;")}>
                    {"⬡ agents"}
                  </span>
                  <span style={css("padding: 6px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #8fb0cc;")}>
                    {"○ systems"}
                  </span>
                </span>
                <span style={css("color: #6b6a65; padding: 6px 0;")}>
                  {"↓"}
                </span>
                <span style={css("padding: 6px 10px; border: 1px solid #3a3a40; border-radius: 6px; color: #e8e6e1;")}>
                  {"↔ relationships"}
                </span>
                <span style={css("color: #6b6a65; padding: 6px 0;")}>
                  {"↓"}
                </span>
                <span style={css("padding: 6px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #a09f99;")}>
                  {"◉ activity"}
                </span>
                <span style={css("color: #6b6a65; padding: 6px 0;")}>
                  {"↓"}
                </span>
                <span style={css("padding: 6px 10px; border: 1px solid #2a2a2f; border-radius: 6px; color: #9cc4a9;")}>
                  {"↑ value"}
                </span>
                <span style={css("color: #6b6a65; padding: 6px 0;")}>
                  {"↓"}
                </span>
                <span style={css("padding: 6px 12px; border-radius: 6px; background: #e8e6e1; color: #1a1a1e;")}>
                  {"✓ outcomes"}
                </span>
              </div>
            </div>
            <div style={css("display: flex; flex-direction: column; border-top: 1px solid #2a2a2f;")}>
              {(apps).map((a: any, aIndex: number) => (
                <Fragment key={aIndex}>
                  <a href={link(a.href)} style={css("display: grid; grid-template-columns: 28px minmax(0, 1fr) auto; gap: 14px; align-items: baseline; padding: 20px 4px; border-bottom: 1px solid #2a2a2f; text-decoration: none; color: #e8e6e1; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-51ea9421">
                    <span style={css(a.gStyle)}>
                      {a.g}
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                      <span style={css("font-size: 18px; font-weight: 500; letter-spacing: -0.2px;")}>
                        {a.title}
                      </span>
                      <span style={css("font-size: 13px; color: #a09f99; line-height: 1.5;")}>
                        {a.body}
                      </span>
                    </span>
                    <span style={css("font-family: var(--font-mono); color: #6b6a65;")}>
                      {"→"}
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="depth" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(80px, 11vw, 144px) 24px; display: flex; flex-direction: column; align-items: center; gap: clamp(36px, 5vw, 56px);")}>
            <h2 style={css("font-size: clamp(32px, 4.6vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-align: center; text-wrap: balance;")}>
              {"Read as much or as little as you need."}
            </h2>
            <div style={css("width: 100%; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              <a href={link("Olympus Technology.dc.html")} style={css("display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 24px; align-items: baseline; padding: 28px 0; border-bottom: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: padding 200ms cubic-bezier(0.22,1,0.36,1);")} className="hv-33c6c939">
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
                  {"10 seconds"}
                </span>
                <span style={css("font-size: clamp(17px, 1.8vw, 21px); font-weight: 500; letter-spacing: -0.01em; line-height: 1.4;")}>
                  {"Olympus builds technology that connects activity across people, agents and systems so organizations can understand what is happening and act on it."}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Platform.dc.html")} style={css("display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 24px; align-items: baseline; padding: 28px 0; border-bottom: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: padding 200ms cubic-bezier(0.22,1,0.36,1);")} className="hv-33c6c939">
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
                  {"60 seconds"}
                </span>
                <span style={css("font-size: clamp(17px, 1.8vw, 21px); font-weight: 500; letter-spacing: -0.01em; line-height: 1.4;")}>
                  {"Aether creates a connected model of identities, relationships, journeys, activity and value across your systems, then lets you explore that understanding from different perspectives."}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Docs.dc.html")} style={css("display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 24px; align-items: baseline; padding: 28px 0; border-bottom: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: padding 200ms cubic-bezier(0.22,1,0.36,1);")} className="hv-33c6c939">
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
                  {"Technical evaluation"}
                </span>
                <span style={css("font-family: var(--font-mono); font-size: 13px; line-height: 1.65; color: #4a4945;")}>
                  {"Aether is a tenant-scoped intelligence graph and runtime built around canonical event contracts, normalization, entity resolution, temporal relationships, graph projection and application surfaces."}
                </span>
                <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: center; text-align: center;")}>
            <h2 style={css("font-size: clamp(32px, 4.6vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; max-width: 820px; color: #1a1a1e; text-wrap: balance;")}>
              {"Connect your tools. See who’s who, what happened, and how it all fits together."}
            </h2>
            <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 560px;")}>
              {"Start on your own with one connection, or talk to us about a question you want answered."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: center;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 44px; padding: 0 20px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Contact.dc.html?brand=aether&type=pilot")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 44px; padding: 0 20px; box-sizing: border-box; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Request a pilot"}
              </a>
              <a href={link("Aether Pricing.dc.html")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; padding: 0 8px;")} className="hv-cc8e330e">
                {"See pricing"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
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
