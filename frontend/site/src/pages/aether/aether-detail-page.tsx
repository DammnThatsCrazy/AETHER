/**
 * Built from design/designs/Aether Detail Page.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './aether-detail-page.css';

import { Navigate, useLocation, useParams } from 'react-router-dom';

interface Detail {
  name: string;
  parent: string;
  parentHref: string;
  nav: string;
  q: string;
  lead: string;
  cta: string;
  ctaHref: string;
  stepsTitle: string;
  steps: [string, string][];
  code: string;
  facts: string[];
  next: string;
}

const T = 'Aether Trust.dc.html';
const C = 'Aether Connect.dc.html';
const Self = 'Aether Detail Page.dc.html?p=';

/** Trust topics live under /trust/<topic>, connection topics under /connect/<topic>. */
export const DETAILS: Record<string, Detail> = {
  privacy: { name: 'Privacy', parent: 'Trust', parentHref: T, nav: '', q: 'What happens to people’s data?', lead: 'Aether only uses data people have agreed to share, keeps it separate from every other customer, and removes it when asked.', cta: 'Read the privacy notice', ctaHref: 'Legal.dc.html?doc=privacy', stepsTitle: 'The life of a piece of data', steps: [['Collected with a purpose', 'Every event carries the permission it needs. No permission, no collection.'], ['Kept separate', 'Your data lives in your own space. It is never mixed with, or visible to, another customer.'], ['Sensitive fields removed', 'Passwords, keys, and tokens are stripped before sending and again before any export.'], ['Deleted on request', 'Deleting removes raw data and stops new collection. Export first if you want a copy.']], code: '// Withdrawing consent stops collection immediately\naether.consent.revoke([\'analytics\']);', facts: ['You own your raw data and records', 'Retention is set per account', 'No data is exported without approval', 'Visitor consent is respected in every SDK'], next: 'governance' },
  governance: { name: 'Governance', parent: 'Trust', parentHref: T, nav: '', q: 'Who is in charge of what?', lead: 'Aether records what happens and who allowed it. People stay in charge of the decisions that matter.', cta: 'Read the governance docs', ctaHref: 'Docs.dc.html?page=governance', stepsTitle: 'How decisions are kept accountable', steps: [['Aether recommends', 'It spots patterns and explains them, with evidence and how sure it is.'], ['A person decides', 'Big or irreversible actions wait for a person to approve.'], ['Everything is recorded', 'Who decided, when, and why — in a trail you can inspect and export.'], ['Agents are watched, not driven', 'Aether records what AI agents do. It does not approve, block, or send their actions.']], code: 'decision:dc_0912\n  by      usr_2x8kf\n  at      2026-03-10T14:22Z\n  reason  "refund above $40 limit"', facts: ['Approval limits are set by your team', 'Every decision keeps who, when, and why', 'Audit trails can be exported', 'Agents are observed, never controlled'], next: 'deployment' },
  deployment: { name: 'Deployment', parent: 'Trust', parentHref: T, nav: '', q: 'Where does Aether run?', lead: 'Shared cloud to start. Dedicated, sovereign, on-premise, or offline when you need more control. The protections stay the same.', cta: 'Request a security review', ctaHref: 'Contact.dc.html?brand=aether&type=security', stepsTitle: 'Five ways to run it', steps: [['Shared cloud', 'The default. Available today.'], ['Dedicated', 'Your own resources. Available today.'], ['Sovereign', 'Kept in your region. Planned.'], ['On-premise', 'Your own infrastructure. Planned.'], ['Offline', 'No outside network. Planned.']], code: '# availability is marked honestly\ncloud       available\ndedicated   available\nsovereign   planned', facts: ['Only available options are marked available', 'The data model is the same everywhere', 'Ask us what your review needs', 'No certification is claimed today'], next: 'privacy' },
  connectors: { name: 'Connectors', parent: 'Connect', parentHref: C, nav: 'Connect', q: 'How do I connect an app I already use?', lead: 'Sign in to the app, choose what to share, and Aether keeps it in sync. No code needed.', cta: 'See every connector', ctaHref: 'Docs.dc.html?page=connector-catalog', stepsTitle: 'Connecting takes four steps', steps: [['Pick the app', 'Choose from Shopify, Stripe, HubSpot, Salesforce, Klaviyo and more.'], ['Choose what to share', 'Read-only permissions, one checkbox at a time.'], ['History comes in first', 'Existing customers and orders appear as profiles.'], ['Then it stays live', 'New activity keeps flowing and joins the same profiles.']], code: 'connect("shopify")\n  scopes: customers, orders, refunds\n  mode:   historical sync + live', facts: ['No fee per connector', 'Every connector is read-only', 'Anything that can send a webhook can connect', 'More connectors are added regularly'], next: 'sdks' },
  sdks: { name: 'SDKs', parent: 'Connect', parentHref: C, nav: 'Connect', q: 'How do I connect my website or app?', lead: 'Add a small library to your website or app. It sends only what people have agreed to share.', cta: 'Open the quickstart', ctaHref: 'Docs.dc.html?page=quickstart-web', stepsTitle: 'From install to first event', steps: [['Install', 'Web, iOS, Android, or React Native.'], ['Start after consent', 'Initialize once your consent banner records permission.'], ['Send an event', 'Page views, sign-ups, purchases — one line each.'], ['See it arrive', 'Watch the event appear on a profile within seconds.']], code: "import { AetherSDK } from '@aether/web';\n\nconst aether = AetherSDK.init({ tenantId: 'your-tenant-id', appId: 'your-app-id' });\naether.consent.grant(['analytics']);\naether.track('page_view', { path: location.pathname });", facts: ['Only public IDs live in the browser', 'Events are batched and retried safely', 'The heavy work happens in Aether, not on devices', 'Four SDKs: web, iOS, Android, React Native'], next: 'apis' },
  apis: { name: 'APIs and webhooks', parent: 'Connect', parentHref: C, nav: 'Connect', q: 'How do I send data from my servers?', lead: 'Post events from your own servers, or let another service push them in automatically with a signed webhook.', cta: 'Read the API reference', ctaHref: 'Docs.dc.html?page=ingestion-api', stepsTitle: 'Two ways in', steps: [['Server events', 'Send batches from your backend with a write key.'], ['Signed webhooks', 'Let a service push events; each one is verified.'], ['Safe to retry', 'Requests are idempotent, so retries never duplicate.'], ['AI agents too', 'Agent runtimes send tasks, tool calls, and outcomes the same way.']], code: 'POST /v1/batch\nAuthorization: Bearer <write key>\n\n{ "events": [ { "type": "order_completed", "value": 149 } ] }', facts: ['Write keys can only send, never read', 'Webhook signatures are verified', 'Requests are idempotent', 'Rate limits and errors are documented'], next: 'imports' },
  imports: { name: 'Imports', parent: 'Connect', parentHref: C, nav: 'Connect', q: 'How do I bring in past data?', lead: 'Upload a file of existing customers. They become profiles first, so new activity joins them automatically later.', cta: 'Read the import guide', ctaHref: 'Docs.dc.html?page=imports', stepsTitle: 'Import with a safety net', steps: [['Upload', 'CSV, JSON, or JSONL up to 32 MB.'], ['Map the columns', 'Aether suggests a mapping; you adjust it.'], ['Dry run', 'See what would happen before anything changes.'], ['Commit — or roll back', 'Confirm the import, and undo it if needed.']], code: 'import  customers.csv\n→ map     email, name, created_at\n→ dry run 12,408 rows · 3 warnings\n→ commit', facts: ['History becomes profiles first', 'New activity joins the same profile', 'A person approves every import', 'Imports can be rolled back'], next: 'connectors' },
};

export const TRUST_TOPICS = ['privacy', 'governance', 'deployment'] as const;
export const CONNECT_TOPICS = ['connectors', 'sdks', 'apis', 'imports'] as const;

export function AetherDetailPage() {
  const link = useLink();
  const { topic = '' } = useParams();
  const { pathname } = useLocation();
  const section = pathname.startsWith('/trust') ? 'trust' : 'connect';
  const known = (section === 'trust' ? (TRUST_TOPICS as readonly string[]) : (CONNECT_TOPICS as readonly string[])).includes(topic);
  const p = DETAILS[known ? topic : section === 'trust' ? 'privacy' : 'connectors']!;
  const nx = DETAILS[p.next]!;
  usePageMeta('aether-detail', { title: p.name + ' — Aether', description: p.lead });
  const d = { ...p, nextLabel: nx.name, nextHref: Self + p.next };
  const steps = p.steps.map(([t, b], i) => ({ t, b, n: '0' + (i + 1), style: 'display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 16px; align-items: baseline; padding: 20px 0; border-bottom: 1px solid #2a2a2f; animation: dtIn 320ms cubic-bezier(0.22,1,0.36,1) ' + (i * 80) + 'ms both;' }));
  if (!known) return <Navigate to={section === 'trust' ? '/trust' : '/connect'} replace />;
  return (
    <div className="dc pg-aether-detail">
    <div data-page="aether-detail" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand="aether" active={d.nav} />
      <main id="main" tabIndex={-1}>
        <section>
          <div style={css("max-width: 960px; margin: 0 auto; padding: clamp(96px, 14vw, 176px) 24px clamp(56px, 8vw, 96px); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 24px;")}>
            <span style={css("display: flex; gap: 8px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
              <a href={link(d.parentHref)} style={css("color: #6b6a65; text-decoration: none;")}>
                {d.parent}
              </a>
              <span>
                {"/"}
              </span>
              <span style={css("color: #1a1a1e;")}>
                {d.name}
              </span>
            </span>
            <h1 style={css("font-size: clamp(44px, 7vw, 96px); font-weight: 500; line-height: 0.95; letter-spacing: -0.048em; margin: 0; text-wrap: balance;")}>
              {d.q}
            </h1>
            <p style={css("font-size: clamp(17px, 1.6vw, 19px); line-height: 1.55; color: #4a4945; margin: 0; max-width: 580px; text-wrap: pretty;")}>
              {d.lead}
            </p>
            <a href={link(d.ctaHref)} style={css("display: inline-flex; align-items: center; gap: 8px; min-height: 46px; padding: 0 22px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1;")} className="hv-7e3a2e7d">
              {d.cta}
              <span style={css("font-family: var(--font-mono);")}>
                {"→"}
              </span>
            </a>
          </div>
        </section>
        <section data-theme="dark" style={css("background: #111114; color: #e8e6e1;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 36px;")}>
            <h2 style={css("font-size: clamp(28px, 3.6vw, 44px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.06; margin: 0; color: #e8e6e1; text-align: center; text-wrap: balance;")}>
              {d.stepsTitle}
            </h2>
            <ol style={css("width: 100%; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #2a2a2f;")}>
              {(steps).map((s: any, sIndex: number) => (
                <Fragment key={sIndex}>
                  <li style={css(s.style)}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #8a8984;")}>
                      {s.n}
                    </span>
                    <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                      <span style={css("font-size: 19px; font-weight: 500; color: #e8e6e1;")}>
                        {s.t}
                      </span>
                      <span style={css("font-size: 14px; line-height: 1.55; color: #a09f99;")}>
                        {s.b}
                      </span>
                    </span>
                  </li>
                </Fragment>
              ))}
            </ol>
            <pre style={css("width: 100%; box-sizing: border-box; margin: 0; font-family: var(--font-mono); font-size: 12.5px; line-height: 1.7; color: #e8e6e1; background: #0b0b0d; border: 1px solid #2a2a2f; border-radius: 10px; padding: 18px 20px; overflow-x: auto;")}>
              {d.code}
            </pre>
          </div>
        </section>
        <section style={css("border-bottom: 1px solid #d8d6d0;")}>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(72px, 10vw, 128px) 24px; display: flex; flex-direction: column; align-items: center; gap: 32px;")}>
            <h2 style={css("font-size: clamp(28px, 3.6vw, 44px); font-weight: 500; letter-spacing: -0.03em; line-height: 1.06; margin: 0; text-align: center;")}>
              {"Good to know"}
            </h2>
            <ul style={css("width: 100%; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
              {(d.facts).map((f: any, fIndex: number) => (
                <Fragment key={fIndex}>
                  <li style={css("display: flex; gap: 16px; align-items: baseline; padding: 18px 0; border-bottom: 1px solid #d8d6d0; font-size: 17px; font-weight: 500;")}>
                    <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                      {"→"}
                    </span>
                    {f}
                  </li>
                </Fragment>
              ))}
            </ul>
          </div>
        </section>
        <section>
          <div style={css("max-width: 880px; margin: 0 auto; padding: clamp(56px, 8vw, 96px) 24px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 24px;")}>
            <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
              <span style={css("font-size: 13px; color: #6b6a65;")}>
                {"Next"}
              </span>
              <a href={link(d.nextHref)} style={css("font-size: clamp(22px, 2.4vw, 30px); font-weight: 500; letter-spacing: -0.02em; color: #1a1a1e; text-decoration: none;")} className="hv-cc8e330e">
                {d.nextLabel}{" "}
                <span style={css("font-family: var(--font-mono);")}>
                  {"→"}
                </span>
              </a>
            </div>
            <a href={link(d.parentHref)} style={css("font-size: 14px; font-weight: 500; color: #6b6a65; text-decoration: none;")} className="hv-75877933">
              {"Back to "}{d.parent}
            </a>
          </div>
        </section>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
