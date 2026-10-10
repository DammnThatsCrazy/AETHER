/**
 * Built from design/designs/Aether Security.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-security-page.css';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';
const CONTROLS = [['⬡', 'Kept separate', 'Each customer’s data, views, and caches belong to that customer alone. There is no way to read across.', '#3a6896'], ['✓', 'Consent first', 'Every kind of event needs a matching permission. If someone withdraws it, collection stops.', '#4f7a5e'], ['■', 'No secrets in browsers', 'Websites and apps only carry public IDs. Private keys stay on your servers.', '#6b6a65'], ['◈', 'People approve big actions', 'Important actions wait for a person. Every decision records who, when, and why.', '#8a6433'], ['⌘', 'Everything is logged', 'Decisions, actions, and approvals leave a trail you can inspect and export.', '#6b6a65'], ['↔', 'Every answer explained', 'Anything Aether works out shows its evidence and how confident it is.', '#3a6896']].map(([g, t, b, c]) => ({ g, t, b, gStyle: 'font-family: var(--font-mono); font-size: 16px; color: ' + c + ';' }));
const KEYS: Record<string, [can: string, cant: string, who: string]> = { write: ['Send data into Aether', 'Read or change anything', 'Websites, apps, integrations, server jobs'], read: ['View people, lenses, and exports', 'Send data, or delete anything', 'Analysts, dashboards, integrations'], admin: ['Create exports, manage keys, delete data', '—', 'Account owners only'] };
const DATA = ([['Ownership', ['You own your raw data and records.', 'Your data is never shared with another customer.', 'Nothing is exported without your approval.']], ['Keeping and deleting', ['You choose how long data is kept.', 'Deleting removes your raw data and stops collection.', 'Export first if you want a copy.']], ['Hiding sensitive fields', ['Passwords, keys, and tokens are removed from exports.', 'The SDKs strip sensitive fields before anything is sent.']]] as [string, string[]][]).map(([k, items]) => ({ k, items }));
const DEPLOY = [['Shared cloud', 'the default'], ['Dedicated', 'your own resources'], ['Sovereign', 'kept in your region'], ['On-premise', 'your infrastructure'], ['Offline', 'no outside network']].map(([t, b]) => ({ t, b }));
const LIMITS = ['Secret monitoring of people', 'Political manipulation', 'Adding data people didn’t agree to', 'Unlawful targeting', 'Sharing one customer’s data with another'];

export function AetherSecurityPage() {
  const link = useLink();
  usePageMeta('aether-security');
  const [state, setState] = useDesignState({ key: 'write' });
  const k = state.key;
  const controls = CONTROLS;
  const keys = Object.keys(KEYS).map((id) => {
    const on = id === k;
    return { id, sel: on ? 'true' : 'false', go: () => setState({ key: id }), style: 'font-family: var(--font-mono); min-height: 36px; padding: 0 18px; border-radius: 7px; border: 0; cursor: pointer; font-size: 13px; transition: background-color 120ms ' + EASE + ', color 120ms ' + EASE + '; ' + (on ? 'background: #1a1a1e; color: #f5f4f1;' : 'background: transparent; color: #6b6a65;') };
  });
  const [can, cant, who] = KEYS[k]!;
  const key = { can, cant, who };
  const data = DATA;
  const deploy = DEPLOY;
  const limits = LIMITS;
  return (
    <div className="dc pg-aether-security">
    <div data-page="aether-security" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Security" />
      <main id="main">
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Security"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.4vw, 100px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; max-width: 900px; text-wrap: balance;")}>
              {"Safety is built in, not bolted on."}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 600px;")}>
              {"Data separation, consent, access keys, human approval, and audit trails are part of how Aether stores data — not settings you have to remember. Aether doesn’t claim certifications it hasn’t earned."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=aether&type=security")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Request a security review"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Aether Procurement.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"Procurement"}
              </a>
            </div>
          </div>
        </section>
        <section id="controls" style={css("border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 40px;")}>
            <h2 style={css("font-size: clamp(30px, 4vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-align: center; text-wrap: balance;")}>
              {"Six protections on every record."}
            </h2>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 1px; background: #d8d6d0; border: 1px solid #d8d6d0; border-radius: 12px; overflow: hidden;")}>
              {(controls).map((c: any, cIndex: number) => (
                <Fragment key={cIndex}>
                  <div style={css("display: flex; flex-direction: column; gap: 8px; padding: 24px; background: #f5f4f1;")}>
                    <span style={css(c.gStyle)}>
                      {c.g}
                    </span>
                    <span style={css("font-size: 16px; font-weight: 500;")}>
                      {c.t}
                    </span>
                    <span style={css("font-size: 14px; line-height: 1.55; color: #6b6a65;")}>
                      {c.b}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="keys" style={css("background: #eceae5; border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 32px;")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 12px;")}>
              <h2 style={css("font-size: clamp(30px, 4vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
                {"Three kinds of key. Each does only its job."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Pick one to see what it can do."}
              </p>
            </div>
            <div role="tablist" aria-label="Key scopes" style={css("display: flex; gap: 4px; padding: 4px; border-radius: 10px; background: #f5f4f1; border: 1px solid #d8d6d0;")}>
              {(keys).map((k: any, kIndex: number) => (
                <Fragment key={kIndex}>
                  <button type="button" role="tab" aria-selected={k.sel} onClick={k.go} style={css(k.style)}>
                    {k.id}
                  </button>
                </Fragment>
              ))}
            </div>
            <div style={css("width: 100%; max-width: 640px; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              <div style={css("display: grid; grid-template-columns: 140px minmax(0,1fr); gap: 20px; padding: 18px 0; border-bottom: 1px solid #d8d6d0; animation: scIn 200ms cubic-bezier(0.22,1,0.36,1) both;")}>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"Can"}
                </span>
                <span style={css("font-size: 17px; font-weight: 500;")}>
                  {key.can}
                </span>
              </div>
              <div style={css("display: grid; grid-template-columns: 140px minmax(0,1fr); gap: 20px; padding: 18px 0; border-bottom: 1px solid #d8d6d0;")}>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"Can’t"}
                </span>
                <span style={css("font-size: 15px; color: #4a4945;")}>
                  {key.cant}
                </span>
              </div>
              <div style={css("display: grid; grid-template-columns: 140px minmax(0,1fr); gap: 20px; padding: 18px 0; border-bottom: 1px solid #d8d6d0;")}>
                <span style={css("font-size: 13px; color: #6b6a65;")}>
                  {"Usually held by"}
                </span>
                <span style={css("font-size: 15px; color: #4a4945;")}>
                  {key.who}
                </span>
              </div>
            </div>
            <p style={css("font-size: 13px; line-height: 1.6; color: #6b6a65; margin: 0; text-align: center; max-width: 560px;")}>
              {"Sign-in sessions live only in the app — public sites never store passwords. Older API keys are shown once when created, and can be rotated from Settings."}
            </p>
          </div>
        </section>
        <section id="data" style={css("border-top: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 40px;")}>
            <h2 style={css("font-size: clamp(30px, 4vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-align: center; text-wrap: balance;")}>
              {"Your data stays yours."}
            </h2>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: clamp(24px, 4vw, 48px);")}>
              {(data).map((d: any, dIndex: number) => (
                <Fragment key={dIndex}>
                  <div style={css("display: flex; flex-direction: column; gap: 12px; padding-top: 16px; border-top: 1px solid #1a1a1e;")}>
                    <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                      {d.k}
                    </span>
                    {(d.items).map((i: any, iIndex: number) => (
                      <Fragment key={iIndex}>
                        <span style={css("font-size: 15px; line-height: 1.5;")}>
                          {i}
                        </span>
                      </Fragment>
                    ))}
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="deploy" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 32px;")}>
            <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 12px;")}>
              <h2 style={css("font-size: clamp(30px, 4vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; color: #e8e6e1;")}>
                {"Run it where you need it."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #a09f99; margin: 0;")}>
                {"From shared cloud to fully offline. The protections stay the same."}
              </p>
            </div>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              {(deploy).map((d: any, dIndex: number) => (
                <Fragment key={dIndex}>
                  <span style={css("display: inline-flex; flex-direction: column; align-items: center; gap: 2px; padding: 14px 20px; border: 1px solid #2a2a2f; border-radius: 10px; min-width: 140px;")}>
                    <span style={css("font-size: 15px; font-weight: 500; color: #e8e6e1;")}>
                      {d.t}
                    </span>
                    <span style={css("font-size: 12px; color: #a09f99;")}>
                      {d.b}
                    </span>
                  </span>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="limits" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 28px;")}>
            <h2 style={css("font-size: clamp(30px, 4vw, 48px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.04; margin: 0; text-wrap: balance;")}>
              {"What Olympus Labs won’t build."}
            </h2>
            <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
              {(limits).map((l: any, lIndex: number) => (
                <Fragment key={lIndex}>
                  <span style={css("font-size: clamp(19px, 2vw, 24px); font-weight: 500; letter-spacing: -0.015em; color: #6b6a65; text-decoration: line-through; text-decoration-color: #c9c7c0; text-decoration-thickness: 1px;")}>
                    {l}
                  </span>
                </Fragment>
              ))}
            </div>
            <p style={css("font-size: 14px; line-height: 1.6; color: #6b6a65; margin: 8px 0 0; max-width: 520px;")}>
              {"Designed to be ready for GDPR and SOC 2. No certification is claimed today — current documents are shared through a security review."}
            </p>
          </div>
        </section>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 13vw, 160px) 24px; display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px;")}>
            <h2 style={css("font-size: clamp(32px, 4.8vw, 60px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; text-wrap: balance;")}>
              {"Ask for what your review needs."}
            </h2>
            <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0; max-width: 480px;")}>
              {"Answers come from the live system, not a marketing sheet."}
            </p>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;")}>
              <a href={link("Contact.dc.html?brand=aether&type=security")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Request a security review"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Docs.dc.html?page=governance")} style={css("display: inline-flex; align-items: center; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-67a914b1">
                {"Governance docs"}
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
