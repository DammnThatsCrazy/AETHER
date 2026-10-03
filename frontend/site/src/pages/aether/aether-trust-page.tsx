/**
 * Built from design/designs/Aether Trust.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-trust-page.css';

import { pilotOnly } from '@site/site/access';

const TRUST_LINKS: [g: string, t: string, b: string, href: string, c: string][] = [
  ['✓', 'Security', 'Architecture, key scopes, and incident response.', 'Aether Security.dc.html', '#4f7a5e'],
  ['◈', 'Privacy', 'What happens to people’s data.', 'Aether Detail Page.dc.html?p=privacy', '#3a6896'],
  ['⬡', 'Governance', 'Who is in charge of what.', 'Aether Detail Page.dc.html?p=governance', '#3a6896'],
  ['■', 'Tenant isolation', 'Tenant intelligence never crosses tenants.', 'Docs.dc.html?page=tenants', '#a3473c'],
  ['○', 'Consent', 'Canonical consent purposes per event.', 'Docs.dc.html?page=sdk-privacy', '#5a85a8'],
  ['↺', 'Deletion and retention', 'Deletion removes raw data and stops ingestion.', 'Legal.dc.html?doc=privacy', '#6b6a65'],
  ['⬡', 'Responsible agent authority', 'Observe verbs only. Human review for graph changes.', 'Aether Agents.dc.html', '#a8783e'],
  ['◉', 'Deployment options', 'Cloud, dedicated, sovereign.', 'Aether Detail Page.dc.html?p=deployment', '#8a6433'],
  ['≡', 'Procurement', 'What a procurement review needs.', 'Aether Procurement.dc.html', '#7d6538'],
  ['●', 'Status', 'Live service health and 90-day history.', 'Status.dc.html', '#4f7a5e'],
];
const DEPLOY: [t: string, b: string, avail: boolean][] = [['Multi-tenant cloud', 'Aether Cloud, tenant-scoped.', true], ['Enterprise isolated', 'A dedicated environment.', true], ['Sovereign', 'Controlled residency and isolation.', false], ['On-premise', 'Enterprise controlled.', false], ['Air-gapped', 'Where supported.', false]];
const AUTHORITY = [['○', 'requested', 'agt_x_22', '#a09f99'], ['✓', 'authorized', 'usr_2x8kf', '#dcb683'], ['→', 'executed', 'req_9fa', '#dcb683'], ['✓', 'verified', 'oc_118', '#9cc4a9']].map(([g, k, who, c]) => ({ g, k, who, gStyle: 'font-family: var(--font-mono); color: ' + c + ';' }));
const DEPLOY_VALS = DEPLOY.map(([t, b, avail]) => ({
  t,
  b,
  state: avail ? '● available' : '○ planned',
  dot: 'font-family: var(--font-mono); font-size: 11px; color: ' + (avail ? '#4f7a5e' : '#9c9b95') + ';',
  style: 'display: flex; flex-direction: column; gap: 8px; padding: 18px; border-radius: 10px; ' + (avail ? 'background: #f5f4f1; border: 1px solid #d8d6d0;' : 'background: transparent; border: 1px dashed #c9c7c0;'),
}));

export function AetherTrustPage() {
  const link = useLink();
  usePageMeta('aether-trust');
  const [state, setState] = useDesignState({ denied: false });
  const dn = state.denied;
  const toggleConsent = () => setState({ denied: !dn });
  const consentBtn = dn ? 'simulate: granted' : 'simulate: revoked';
  const purpose = dn ? 'analytics ✕' : 'analytics ✓';
  const allowStyle = 'transition: color 200ms cubic-bezier(0.22,1,0.36,1); color: ' + (dn ? '#4a4a52' : '#9cc4a9') + ';';
  const denyStyle = 'transition: color 200ms cubic-bezier(0.22,1,0.36,1); color: ' + (dn ? '#e09a8f' : '#4a4a52') + ';';
  const authority = AUTHORITY;
  // Pilot-only builds have no public status page link.
  const links = TRUST_LINKS.filter((l) => !(pilotOnly() && l[3] === 'Status.dc.html')).map(([g, t, b, href, c]) => ({ g, t, b, href, gStyle: 'font-family: var(--font-mono); font-size: 15px; color: ' + c + ';' }));
  const deploy = DEPLOY_VALS;
  return (
    <div className="dc pg-aether-trust">
    <div data-page="aether-trust" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(64px, 9vw, 112px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              {"Trust"}
            </span>
            <h1 style={css("font-size: clamp(48px, 7.4vw, 100px); font-weight: 500; line-height: 0.94; letter-spacing: -0.05em; margin: 0; text-wrap: balance;")}>
              {"Can you trust Aether with your data?"}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 560px;")}>
              {"Security, privacy, and how Aether is run — all in one place, with no promises it can’t back up."}
            </p>
            <span style={css("font-family: var(--font-mono); font-size: 12px; color: #6b6a65;")}>
              {"Designed for GDPR and SOC 2 readiness · no certification claimed"}
            </span>
          </div>
        </section>
        <section id="boundaries" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1100px; margin: 0 auto; padding: clamp(80px, 11vw, 136px) 24px; display: flex; flex-direction: column; align-items: center; gap: clamp(40px, 6vw, 64px);")}>
            <h2 style={css("font-size: clamp(32px, 4.4vw, 56px); font-weight: 500; letter-spacing: -0.035em; line-height: 1.02; margin: 0; color: #e8e6e1; text-align: center; text-wrap: balance;")}>
              {"Three lines Aether never crosses."}
            </h2>
            <div style={css("width: 100%; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); gap: 1px; background: #2a2a2f; border: 1px solid #2a2a2f; border-radius: 12px; overflow: hidden;")}>
              <div style={css("display: flex; flex-direction: column; gap: 18px; padding: 28px; background: #111114;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"Tenant isolation"}
                </span>
                <div style={css("display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: center;")}>
                  <div style={css("display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid #3a3a40; border-radius: 8px; font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                    <span style={css("color: #e8e6e1; font-family: var(--font-sans); font-size: 13px; font-weight: 500;")}>
                      {"Tenant A"}
                    </span>
                    <span>
                      {"graph"}
                    </span>
                    <span>
                      {"data"}
                    </span>
                    <span>
                      {"keys"}
                    </span>
                  </div>
                  <span style={css("font-family: var(--font-mono); font-size: 20px; color: #e09a8f;")}>
                    {"✕"}
                  </span>
                  <div style={css("display: flex; flex-direction: column; gap: 4px; padding: 12px; border: 1px solid #3a3a40; border-radius: 8px; font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                    <span style={css("color: #e8e6e1; font-family: var(--font-sans); font-size: 13px; font-weight: 500;")}>
                      {"Tenant B"}
                    </span>
                    <span>
                      {"graph"}
                    </span>
                    <span>
                      {"data"}
                    </span>
                    <span>
                      {"keys"}
                    </span>
                  </div>
                </div>
                <span style={css("font-size: 14px; line-height: 1.55; color: #a09f99; margin-top: auto;")}>
                  {"Your data is never shared with another customer."}
                </span>
              </div>
              <div style={css("display: flex; flex-direction: column; gap: 18px; padding: 28px; background: #111114;")}>
                <div style={css("display: flex; justify-content: space-between; align-items: center; gap: 8px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Consent"}
                  </span>
                  <button type="button" onClick={toggleConsent} style={css("font-family: var(--font-mono); font-size: 11px; padding: 4px 10px; border-radius: 999px; border: 1px solid #3a3a40; background: transparent; color: #e8e6e1; cursor: pointer;")}>
                    {consentBtn}
                  </button>
                </div>
                <div style={css("display: flex; flex-direction: column; align-items: flex-start; gap: 6px; font-family: var(--font-mono); font-size: 12px;")}>
                  <span style={css("padding: 6px 10px; border: 1px solid #3a3a40; border-radius: 6px; color: #e8e6e1;")}>
                    {"◉ signal"}
                  </span>
                  <span style={css("color: #6b6a65; padding-left: 14px;")}>
                    {"↓"}
                  </span>
                  <span style={css("padding: 6px 10px; border-radius: 6px; background: #e8e6e1; color: #1a1a1e;")}>
                    {"consent check · "}{purpose}
                  </span>
                  <span style={css("display: flex; gap: 16px; padding-left: 14px;")}>
                    <span style={css(allowStyle)}>
                      {"├ allowed → process"}
                    </span>
                  </span>
                  <span style={css("display: flex; gap: 16px; padding-left: 14px;")}>
                    <span style={css(denyStyle)}>
                      {"└ denied → stop"}
                    </span>
                  </span>
                </div>
                <span style={css("font-size: 14px; line-height: 1.55; color: #a09f99; margin-top: auto;")}>
                  {"If someone hasn’t agreed, their data isn’t used."}
                </span>
              </div>
              <div style={css("display: flex; flex-direction: column; gap: 18px; padding: 28px; background: #111114;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"Agent authority"}
                </span>
                <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                  {(authority).map((a: any, aIndex: number) => (
                    <Fragment key={aIndex}>
                      <span style={css("display: grid; grid-template-columns: 18px minmax(0,1fr) auto; gap: 10px; align-items: center; padding: 8px 10px; border: 1px solid #2a2a2f; border-radius: 6px; font-size: 13px;")}>
                        <span style={css(a.gStyle)}>
                          {a.g}
                        </span>
                        <span style={css("color: #e8e6e1;")}>
                          {a.k}
                        </span>
                        <span style={css("font-family: var(--font-mono); font-size: 11px; color: #6b6a65;")}>
                          {a.who}
                        </span>
                      </span>
                    </Fragment>
                  ))}
                </div>
                <span style={css("font-size: 14px; line-height: 1.55; color: #a09f99; margin-top: auto;")}>
                  {"Aether records what agents do. Big, irreversible actions wait for a person."}
                </span>
              </div>
            </div>
          </div>
        </section>
        <section id="evaluate" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
                  {"Evaluate"}
                </span>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"Everything your security team will ask."}
                </h2>
              </div>
              <a href={link("Contact.dc.html?brand=aether&type=security")} style={css("justify-self: start; display: inline-flex; align-items: center; gap: 8px; min-height: 42px; padding: 0 18px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {"Request a security review"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); gap: 8px;")}>
              {(links).map((l: any, lIndex: number) => (
                <Fragment key={lIndex}>
                  <a href={link(l.href)} style={css("display: flex; flex-direction: column; gap: 6px; padding: 18px; border-radius: 10px; background: #fbfaf8; border: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: border-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-6268baea">
                    <span style={css("display: flex; justify-content: space-between;")}>
                      <span style={css(l.gStyle)}>
                        {l.g}
                      </span>
                      <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                        {"→"}
                      </span>
                    </span>
                    <span style={css("font-size: 15px; font-weight: 500;")}>
                      {l.t}
                    </span>
                    <span style={css("font-size: 13px; line-height: 1.5; color: #6b6a65;")}>
                      {l.b}
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="deployment" style={css("background: #eceae5; border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: flex; flex-direction: column; gap: 12px; max-width: 720px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #8a6433;")}>
                {"Deployment"}
              </span>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                {"Run it where you need it."}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"What’s available today is marked available. Everything else is marked as planned."}
              </p>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); gap: 8px;")}>
              {(deploy).map((d: any, dIndex: number) => (
                <Fragment key={dIndex}>
                  <div style={css(d.style)}>
                    <span style={css(d.dot)}>
                      {d.state}
                    </span>
                    <span style={css("font-size: 16px; font-weight: 500;")}>
                      {d.t}
                    </span>
                    <span style={css("font-size: 13px; line-height: 1.5; color: #4a4945;")}>
                      {d.b}
                    </span>
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
