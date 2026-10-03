/**
 * Built from design/designs/Aether Connect.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { createElement as h, type ReactNode } from 'react';
import { asset, css, portalLabel, useDesignState, useLink, useReducedMotion } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-connect.css';

export function AetherConnectPage() {
  const link = useLink();
  usePageMeta('aether-connect');
  const [state, setState] = useDesignState<{ opt: string }>({ opt: 'saas' });
  const reduce = useReducedMotion();
  const vals = connectVals(state.opt, (opt) => setState({ opt }), reduce, asset);
  const { hub, opts, cur, connectors, sdks, formats, importFlow } = vals;
  return (
    <div className="dc pg-aether-connect">
    <div data-page="aether-connect" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active="Connect" />
      <main id="main" tabIndex={-1}>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 9vw, 120px) 24px clamp(40px, 6vw, 72px); display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 440px), 1fr)); gap: 32px; align-items: end;")}>
            <div style={css("display: flex; flex-direction: column; gap: 20px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #3a6896;")}>
                {"Connect"}
              </span>
              <h1 style={css("font-size: clamp(44px, 6.4vw, 84px); font-weight: 500; line-height: 0.96; letter-spacing: -0.045em; margin: 0; text-wrap: balance;")}>
                {"Connect the tools you already use."}
              </h1>
            </div>
            <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 500px; padding-bottom: 8px;")}>
              {"However your data gets in, it ends up in the same place — with where it came from and what it’s allowed to be used for. Start wherever your data already lives."}
            </p>
          </div>
        </section>
        <section id="wizard" data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(48px, 7vw, 88px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <h2 style={css("font-size: clamp(26px, 3vw, 38px); font-weight: 500; letter-spacing: -0.026em; line-height: 1.08; margin: 0; color: #e8e6e1;")}>
              {"Where is your data?"}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch;")}>
              <div role="radiogroup" aria-label="Where is your data" style={css("flex: 1 1 280px; display: flex; flex-direction: column; gap: 6px;")}>
                {(opts).map((o, oIndex) => (
                  <Fragment key={oIndex}>
                    <button type="button" role="radio" aria-checked={o.sel} onClick={o.go} style={css(o.style)}>
                      <span style={css(o.gStyle)}>
                        {o.g}
                      </span>
                      <span style={css("display: flex; flex-direction: column; gap: 2px;")}>
                        <span style={css("font-size: 14px; font-weight: 500;")}>
                          {o.q}
                        </span>
                        <span style={css("font-size: 12px; color: #a09f99;")}>
                          {"→ "}{o.a}
                        </span>
                      </span>
                    </button>
                  </Fragment>
                ))}
              </div>
              <div style={css("flex: 1.2 1 360px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 12px; box-sizing: border-box;")}>
                <div style={css("position: relative; width: 100%; aspect-ratio: 1 / 0.86;")}>
                  {hub}
                </div>
              </div>
              <div style={css("flex: 1.2 1 320px; min-width: 0; border: 1px solid #2a2a2f; border-radius: 12px; background: #1a1a1e; padding: 24px; display: flex; flex-direction: column; gap: 14px; box-sizing: border-box;")}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"Start with"}
                </span>
                <span style={css("font-size: 26px; font-weight: 500; letter-spacing: -0.02em; color: #e8e6e1;")}>
                  {cur.a}
                </span>
                <span style={css("font-size: 14px; line-height: 1.6; color: #a09f99;")}>
                  {cur.body}
                </span>
                <pre style={css("margin: 0; font-family: var(--font-mono); font-size: 11.5px; line-height: 1.7; color: #e8e6e1; background: #111114; border: 1px solid #2a2a2f; border-radius: 8px; padding: 14px; overflow-x: auto; white-space: pre;")}>
                  {cur.code}
                </pre>
                <a href={link(cur.href)} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #e8e6e1; text-decoration: none; margin-top: auto;")} className="hv-6f6d4759">
                  {cur.cta}
                  <span style={css("font-family: var(--font-mono);")}>
                    {"→"}
                  </span>
                </a>
              </div>
            </div>
          </div>
        </section>
        <section id="connectors" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <a href={link("Aether Detail Page.dc.html?p=connectors")} style={css("font-family: var(--font-mono); font-size: 12px; color: #5a85a8; text-decoration: none;")}>
                  {"⚙ connectors →"}
                </a>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"Apps you already use"}
                </h2>
              </div>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Ready-made integrations. Sign in, choose what to share, and Aether keeps it in sync. These are the first — more are being added all the time."}
              </p>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 170px), 1fr)); gap: 8px;")}>
              {(connectors).map((c, cIndex) => (
                <Fragment key={cIndex}>
                  <a href={link("Docs.dc.html?page=connector-catalog")} style={css("display: flex; align-items: center; gap: 12px; padding: 14px; border-radius: 10px; background: #fbfaf8; border: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; transition: border-color 120ms cubic-bezier(0.22,1,0.36,1);")} className="hv-6268baea">
                    <span style={css("width: 32px; height: 32px; border-radius: 8px; background: #ffffff; border: 1px solid #e2e0da; display: flex; align-items: center; justify-content: center; flex-shrink: 0;")}>
                      <img src={asset(c.logo)} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} />
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 2px; min-width: 0;")}>
                      <span style={css("font-size: 13px; font-weight: 500;")}>
                        {c.name}
                      </span>
                      <span style={css("font-size: 11px; color: #6b6a65;")}>
                        {c.kind}
                      </span>
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
            <div style={css("display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; padding: 16px 20px; border: 1px dashed #c9c7c0; border-radius: 10px;")}>
              <span style={css("font-size: 14px; color: #4a4945;")}>
                {"Don’t see your tool? Anything that can send a webhook or call an API can connect today — and new integrations ship regularly."}
              </span>
              <a href={link("Contact.dc.html?brand=aether&type=developer")} style={css("display: inline-flex; gap: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; text-decoration: none; white-space: nowrap;")} className="hv-cc8e330e">
                {"Request an integration"}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
          </div>
        </section>
        <section id="sdks" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <a href={link("Aether Detail Page.dc.html?p=sdks")} style={css("font-family: var(--font-mono); font-size: 12px; color: #3a6896; text-decoration: none;")}>
                  {"⌘ sdks →"}
                </a>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"Your websites and apps"}
                </h2>
              </div>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Small libraries for your website and apps. They only send data people have agreed to share, and do the heavy lifting in Aether — not on your users’ devices."}
              </p>
            </div>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); gap: 10px;")}>
              {(sdks).map((s, sIndex) => (
                <Fragment key={sIndex}>
                  <a href={link(s.href)} style={css("display: flex; flex-direction: column; gap: 8px; min-height: 150px; padding: 20px; border-radius: 12px; background: #f5f4f1; border: 1px solid #d8d6d0; text-decoration: none; color: #1a1a1e; box-sizing: border-box;")} className="hv-2e012587">
                    <span style={css("font-size: 17px; font-weight: 500;")}>
                      {s.name}
                    </span>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #4a4945; margin-top: auto;")}>
                      {s.pkg}
                    </span>
                    <span style={css("font-size: 12px; font-weight: 500; color: #2d5373;")}>
                      {"Quickstart →"}
                    </span>
                  </a>
                </Fragment>
              ))}
            </div>
          </div>
        </section>
        <section id="apis" style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-wrap: wrap; gap: clamp(24px, 4vw, 56px); align-items: center;")}>
            <div style={css("flex: 1 1 320px; display: flex; flex-direction: column; gap: 12px;")}>
              <a href={link("Aether Detail Page.dc.html?p=apis")} style={css("font-family: var(--font-mono); font-size: 12px; color: #4f7a5e; text-decoration: none;")}>
                {"→ apis and webhooks →"}
              </a>
              <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                {"Your servers and other services"}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Send events from your own servers, or let another service push them in automatically. AI agents connect the same way."}
              </p>
            </div>
            <div style={css("flex: 1.2 1 420px; display: flex; flex-direction: column; gap: 8px; min-width: 0;")}>
              <div style={css("font-family: var(--font-mono); font-size: 12px; color: #e8e6e1; padding: 14px 16px; border: 1px solid #2a2a2f; border-radius: 10px; background: #111114;")}>
                <span style={css("color: #9cc4a9;")}>
                  {"POST"}
                </span>
                {" /v1/batch · signed · idempotent"}
              </div>
              <div style={css("font-family: var(--font-mono); font-size: 12px; color: #e8e6e1; padding: 14px 16px; border: 1px solid #2a2a2f; border-radius: 10px; background: #111114;")}>
                <span style={css("color: #9cc4a9;")}>
                  {"POST"}
                </span>
                {" /v1/ingest/feed · server events"}
              </div>
              <div style={css("font-family: var(--font-mono); font-size: 12px; color: #e8e6e1; padding: 14px 16px; border: 1px solid #2a2a2f; border-radius: 10px; background: #111114;")}>
                <span style={css("color: #dcb683;")}>
                  {"HMAC"}
                </span>
                {" webhook · any system that can push"}
              </div>
            </div>
          </div>
        </section>
        <section id="imports" style={css("border-bottom: 1px solid #d8d6d0; background: #eceae5;")}>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-direction: column; gap: 24px;")}>
            <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr)); gap: 24px; align-items: end;")}>
              <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                <a href={link("Aether Detail Page.dc.html?p=imports")} style={css("font-family: var(--font-mono); font-size: 12px; color: #8a6433; text-decoration: none;")}>
                  {"⇪ imports →"}
                </a>
                <h2 style={css("font-size: clamp(28px, 3.4vw, 42px); font-weight: 500; letter-spacing: -0.028em; line-height: 1.06; margin: 0;")}>
                  {"Past data"}
                </h2>
              </div>
              <p style={css("font-size: 15px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
                {"Upload a spreadsheet or an export from another tool. Your existing customers appear first, and new activity joins them automatically later."}
              </p>
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 6px; align-items: center;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65; margin-right: 6px;")}>
                {"Formats"}
              </span>
              {(formats).map((x, xIndex) => (
                <Fragment key={xIndex}>
                  <span style={css(x.style)}>
                    {x.t}
                  </span>
                </Fragment>
              ))}
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 6px; align-items: center;")}>
              {(importFlow).map((f, fIndex) => (
                <Fragment key={fIndex}>
                  <span style={css(f.style)}>
                    {f.l}
                  </span>
                  {(f.arrow) ? (
                    <>
                      <span style={css("font-family: var(--font-mono); color: #9c9b95;")}>
                        {"→"}
                      </span>
                    </>
                  ) : null}
                </Fragment>
              ))}
            </div>
            <div style={css("display: flex; flex-wrap: wrap; gap: 10px; align-items: center; padding: 18px 20px; border-radius: 12px; background: #1a1a1e; color: #e8e6e1; font-family: var(--font-mono); font-size: 12px;")}>
              <span style={css("padding: 6px 10px; border: 1px solid #3a3a40; border-radius: 6px;")}>
                {"historical profile"}
              </span>
              <span style={css("color: #6b6a65;")}>
                {"+"}
              </span>
              <span style={css("padding: 6px 10px; border: 1px solid #3a3a40; border-radius: 6px;")}>
                {"new SDK signal"}
              </span>
              <span style={css("color: #6b6a65;")}>
                {"→"}
              </span>
              <span style={css("padding: 6px 10px; border: 1px solid rgba(220,182,131,0.4); border-radius: 6px; color: #dcb683;")}>
                {"identity resolution"}
              </span>
              <span style={css("color: #6b6a65;")}>
                {"→"}
              </span>
              <span style={css("padding: 6px 10px; border-radius: 6px; background: #e8e6e1; color: #1a1a1e;")}>
                {"same profile"}
              </span>
            </div>
          </div>
        </section>
        <section>
          <div style={css("max-width: 1200px; margin: 0 auto; padding: clamp(64px, 9vw, 112px) 24px; display: flex; flex-direction: column; gap: 20px; align-items: flex-start;")}>
            <h2 style={css("font-size: clamp(30px, 4.2vw, 52px); font-weight: 500; letter-spacing: -0.032em; line-height: 1.04; margin: 0; max-width: 760px; text-wrap: balance;")}>
              {"Connect as many tools as you like. No per-integration fees."}
            </h2>
            <div style={css("display: flex; flex-wrap: wrap; gap: 8px;")}>
              <a href={link("Aether Portal.dc.html?mode=signup")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
                {portalLabel("Get started")}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
              <a href={link("Contact.dc.html?brand=aether&type=developer")} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 20px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #eceae5; color: #1a1a1e; border: 1px solid #d8d6d0;")} className="hv-4d1362f5">
                {"Request a connector"}
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

type ConnectOption = [id: string, glyph: string, question: string, answer: string, color: string, body: string, code: string, href: string, cta: string];

const OPTIONS: ConnectOption[] = [
  ['saas', '⚙', 'Existing SaaS platform?', 'Connector', '#8fb0cc', 'Authorize the provider and Aether handles historical sync, live updates, and normalization. Read-only scopes, chosen per connector.', '// in Aether → Data → Connect\nconnect("shopify")\n  scopes: customers, orders, refunds\n  mode:   historical sync + live', 'Docs.dc.html?page=connector-catalog', 'See every connector'],
  ['web', '◉', 'Website?', 'Web SDK', '#9fbad6', 'Install the SDK after your consent banner records the analytics purpose.', "import { AetherSDK } from '@aether/web';\n\nconst aether = AetherSDK.init({ tenantId: 'your-tenant-id', appId: 'your-app-id' });\naether.consent.grant(['analytics']);\naether.track('page_view', { path: location.pathname });", 'Docs.dc.html?page=quickstart-web', 'Web quickstart'],
  ['mobile', '□', 'Mobile application?', 'iOS, Android, or React Native SDK', '#9fbad6', 'Native SDKs for iOS and Android, plus React Native — the same canonical events on every platform.', "import Aether from '@aether/react-native';\n\nAether.init({ tenantId: 'your-tenant-id', appId: 'your-app-id' });\nAether.consent.grant(['analytics']);\nAether.screen('Home');", 'Docs.dc.html?page=quickstart-react-native', 'Mobile quickstarts'],
  ['backend', '⌘', 'Backend?', 'Server API', '#9cc4a9', 'Send canonical observations from your servers. Batched, signed, and idempotent.', 'POST /v1/batch\nAuthorization: Bearer <write key>\n\n{ "events": [ { "type": "order_completed", ... } ] }', 'Docs.dc.html?page=quickstart-backend', 'Backend quickstart'],
  ['file', '⇪', 'Historical file?', 'Import', '#dcb683', 'CSV, JSON, or JSONL up to 32 MB. Map fields, dry-run, validate, commit — and roll back if needed.', 'import  customers.csv\n→ map     email, name, created_at\n→ dry run 12,408 rows · 3 warnings\n→ commit', 'Docs.dc.html?page=imports', 'Import historical data'],
  ['webhook', '↯', 'External service sending live events?', 'Webhook', '#c9b088', 'Any system that can push can connect with a signed webhook.', 'POST https://ingest.aether…/hooks/<id>\nX-Aether-Signature: sha256=…', 'Docs.dc.html?page=ingestion-api', 'Webhook reference'],
  ['agent', '⬡', 'Agent runtime?', 'Agent integration', '#dcb683', 'Record agent tasks, tool calls, and outcomes so Aether can preserve lineage and authority.', "aether.track('agent_tool_called', {\n  agent_id: 'agt_x_22',\n  tool: 'payments.refund',\n  on_behalf_of: 'usr_2x8kf'\n});", 'Docs.dc.html?page=events', 'Agent events'],
];

/** Ready-made integrations; every logo is a reviewed local mark (packages/brand). */
export const CONNECT_CONNECTORS: [name: string, kind: string, file: string][] = [
  ['HubSpot', 'CRM', 'hubspot'], ['Salesforce', 'CRM', 'salesforce'], ['Shopify', 'commerce', 'shopify'], ['Stripe', 'billing', 'stripe'],
  ['Klaviyo', 'marketing', 'klaviyo'], ['Segment', 'analytics', 'segment'], ['PostHog', 'analytics', 'posthog'], ['GA4', 'analytics', 'googleanalytics'],
  ['Zendesk', 'support', 'zendesk'], ['Intercom', 'support', 'intercom'], ['Jira', 'project · outbound', 'jira'], ['Linear', 'project · outbound', 'linear'],
  ['Slack', 'messaging · outbound', 'slack'], ['Google Ads', 'advertising', 'googleads'], ['Meta', 'advertising', 'meta'], ['Instagram', 'social', 'instagram'],
  ['X', 'social', 'x-dark'], ['Google', 'sign-in · workspace', 'google'], ['Microsoft', 'sign-in · workspace', 'microsoft'], ['Apple', 'sign-in · app store', 'apple'],
  ['Phantom', 'wallets', 'phantom'],
];

const IMPORT_FLOW = ['CSV / JSON', 'Map', 'Validate', 'Normalize', 'Resolve identity', 'Profiles', 'Graph'];

function connectVals(k: string, choose: (id: string) => void, reduce: boolean, assetUrl: (p: string) => string) {
  const ease = 'cubic-bezier(0.22,1,0.36,1)';
  const O = OPTIONS;
  const cur = O.find((o) => o[0] === k) ?? O[0]!;
  const cx = 250, cy = 215, R = 168;
  const spokes = O.map((o, i) => {
    const a = -Math.PI / 2 + i * ((2 * Math.PI) / O.length);
    return { o, x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R * 0.92 };
  });
  const hub: ReactNode = h(
    'svg',
    { viewBox: '0 0 500 430', width: '100%', height: '100%', role: 'img', 'aria-label': 'Connection paths into Aether, ' + cur[3] + ' selected', style: { position: 'absolute', inset: 0, display: 'block', overflow: 'visible' } },
    spokes.map(({ o, x, y }, i) => {
      const on = o[0] === k;
      const d = 'M' + x + ' ' + y + 'L' + cx + ' ' + cy;
      return h(
        'g',
        { key: 'l' + i },
        h('path', { key: on ? 'on' + k : 'off', d, pathLength: 1, stroke: on ? o[4] : '#2a2a2f', strokeWidth: on ? 2 : 1, fill: 'none', strokeDasharray: on ? '1' : '0.02 0.02', style: on ? { animation: 'cnDraw 320ms ' + ease + ' both' } : {} }),
        on && !reduce
          ? h('circle', { key: 'p' + k, r: 3, fill: o[4], opacity: 0 }, h('animateMotion', { dur: '1.6s', repeatCount: 'indefinite', path: d }), h('animate', { attributeName: 'opacity', values: '0;1;1;0', keyTimes: '0;0.1;0.85;1', dur: '1.6s', repeatCount: 'indefinite' }))
          : null,
      );
    }),
    spokes.map(({ o, x, y }, i) => {
      const on = o[0] === k;
      const lab = (o[3].split(',')[0] ?? o[3]).replace(' or React Native SDK', ' SDKs');
      return h(
        'g',
        { key: 'n' + i, style: { cursor: 'pointer' }, onClick: () => choose(o[0]) },
        h('circle', { cx: x, cy: y, r: on ? 22 : 18, fill: on ? o[4] : '#111114', stroke: on ? o[4] : '#3a3a40', style: { transition: 'r 200ms ' + ease + ', fill 200ms ' + ease } }),
        h('text', { x, y: y + 5, textAnchor: 'middle', fill: on ? '#111114' : o[4], style: { fontFamily: 'var(--font-mono)', fontSize: 14 } }, o[1]),
        h('text', { x, y: y + (y > cy ? 40 : -30), textAnchor: 'middle', fill: on ? '#e8e6e1' : '#a09f99', style: { fontFamily: 'var(--font-sans)', fontSize: 11.5, fontWeight: on ? 500 : 400 } }, lab),
      );
    }),
    h('rect', { x: cx - 52, y: cy - 30, width: 104, height: 60, rx: 10, fill: '#e8e6e1' }),
    h('image', { href: assetUrl('../assets/logo-aether-layers.svg'), x: cx - 40, y: cy - 12, width: 24, height: 24 }),
    h('text', { x: cx - 10, y: cy + 5, fill: '#1a1a1e', style: { fontFamily: 'var(--font-sans)', fontSize: 15, fontWeight: 500 } }, 'Aether'),
  );
  return {
    hub,
    opts: O.map(([id, g, q, a, c]) => {
      const on = id === k;
      return {
        g,
        q,
        a,
        sel: on,
        go: () => choose(id),
        gStyle:
          'width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-family: var(--font-mono); font-size: 14px; ' +
          (on ? 'background: ' + c + '; color: #111114;' : 'background: #111114; color: ' + c + '; border: 1px solid #2a2a2f; box-sizing: border-box;'),
        style:
          'font-family: inherit; text-align: left; display: flex; align-items: center; gap: 12px; padding: 10px 12px; border-radius: 10px; cursor: pointer; color: #e8e6e1; transition: background-color 120ms ' +
          ease +
          ', border-color 120ms ' +
          ease +
          '; ' +
          (on ? 'background: #1a1a1e; border: 1px solid #3a3a40;' : 'background: transparent; border: 1px solid transparent;'),
      };
    }),
    cur: { a: cur[3], body: cur[5], code: cur[6], href: cur[7], cta: cur[8] },
    connectors: CONNECT_CONNECTORS.map(([name, kind, f]) => ({ name, kind, logo: '../assets/brand/' + f + '.svg' })),
    sdks: [
      ['Web', '@aether/web', 'quickstart-web'],
      ['iOS', 'AetherSDK (Swift SPM)', 'quickstart-ios'],
      ['Android', 'io.aether:sdk-android', 'quickstart-android'],
      ['React Native', '@aether/react-native', 'quickstart-react-native'],
    ].map(([name, pkg, p]) => ({ name, pkg, href: 'Docs.dc.html?page=' + p })),
    formats: ([
      ['CSV', 1], ['JSON', 1], ['JSONL', 1], ['TSV', 0], ['Excel (.xlsx)', 0], ['Parquet', 0],
      ['Exports from Shopify, HubSpot, Stripe, Salesforce', 0], ['Cloud storage sync', 0], ['Database snapshots', 0],
    ] as [string, number][]).map(([t, live]) => ({
      t: live ? t : t + ' · soon',
      style: 'font-size: 13px; padding: 6px 12px; border-radius: 999px; ' + (live ? 'background: #f5f4f1; border: 1px solid #d8d6d0; color: #1a1a1e;' : 'border: 1px dashed #c9c7c0; color: #6b6a65;'),
    })),
    importFlow: IMPORT_FLOW.map((l, i) => ({
      l,
      arrow: i < IMPORT_FLOW.length - 1,
      style:
        'font-size: 13px; padding: 8px 12px; border-radius: 8px; ' +
        (i === IMPORT_FLOW.length - 1
          ? 'background: #1a1a1e; color: #e8e6e1;'
          : i === 4
            ? 'background: rgba(201,151,90,0.18); color: #8a6433; border: 1px solid rgba(201,151,90,0.4);'
            : 'background: #f5f4f1; border: 1px solid #d8d6d0;'),
    })),
  };
}
