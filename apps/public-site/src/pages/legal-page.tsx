/**
 * Built from design/designs/Legal.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './legal-page.css';

import { Navigate, useNavigate, useParams } from 'react-router-dom';

type DocId = 'privacy' | 'terms';

interface LegalDoc {
  title: string;
  label: string;
  lead: string;
  summary: [g: string, x: string][];
  sections: [id: string, title: string, x: string][];
}

/** Legal.dc.html: plain-language structure for /legal/privacy and /legal/terms (shared by both sites). */
export const LEGAL_DOCS: Record<DocId, LegalDoc> = {
  privacy: { title: 'Privacy and data use', label: 'Privacy and data use', lead: 'How Olympus Labs handles personal information on its public websites, and how Aether handles customer data on a customer’s behalf.',
    summary: [['✓', 'Customers own their data. Aether handles it for them.'], ['⬡', 'One customer’s data is never shared with another.'], ['■', 'Personal information is never sold.']],
    sections: [['scope', 'Scope', 'This notice covers the Olympus Labs and Aether public websites, documentation, status page, and contact forms. What happens inside a customer’s own Aether account is covered by that customer’s agreement.'], ['collect', 'What is collected', 'Information you submit through contact and sign-up forms, and limited site analytics after consent. Aether SDKs added to a customer’s site or app collect only what the customer sets up and what a person agrees to.'], ['use', 'How it is used', 'To answer inquiries, provide the service, secure it, and improve it. Contact details are used only to reply unless you opt in to more.'], ['roles', 'Controller and processor', 'For public-site data, Olympus Labs is the controller. For data inside a customer’s account, the customer decides how it is used and Olympus Labs handles it on their behalf.'], ['share', 'Sharing and sub-processors', 'Shared only with service providers needed to run the service, such as payment processing through Stripe. A sub-processor list is available on request.'], ['retention', 'Retention and deletion', 'Kept only as long as needed. Deleting data removes the raw customer data and stops new data from coming in.'], ['rights', 'Your rights', 'Depending on where you live, you may request access, correction, deletion, or a copy of your information.'], ['contact', 'Contact', 'Send privacy requests to team@olympuslabsml.com.']] },
  terms: { title: 'Terms and use', label: 'Terms and use', lead: 'The terms that govern use of the Olympus Labs and Aether websites and, where no separate agreement exists, the Aether service.',
    summary: [['◈', 'A signed customer agreement overrides these terms.'], ['▲', 'Aether is in private alpha, before public release.'], ['■', 'Not allowed: secret monitoring and unlawful targeting.']],
    sections: [['acceptance', 'Acceptance', 'Using the sites or service means accepting these terms. A signed agreement with Olympus Labs replaces them where the two conflict.'], ['service', 'The service', 'Aether is offered as a private alpha, before public release. Features may change, and availability isn’t guaranteed.'], ['accounts', 'Accounts and keys', 'You’re responsible for your account, the keys you create, and what is sent with them. Keep private keys out of website and app code.'], ['acceptable', 'Acceptable use', 'Don’t use the service to secretly monitor people, manipulate politics, add data people didn’t agree to, target people unlawfully, or reach another customer’s data.'], ['data', 'Your data', 'You own the data you send. You grant Olympus Labs the rights needed to process it to provide the service.'], ['billing', 'Billing', 'Paid plans are billed through Stripe according to the plan selected at checkout.'], ['liability', 'Warranties and liability', 'To be supplied by counsel.'], ['changes', 'Changes', 'Material changes will be announced before they take effect.']] },
};

export function LegalPage() {
  const link = useLink();
  const { doc: param = '' } = useParams();
  const navigate = useNavigate();
  const known = param === 'privacy' || param === 'terms';
  const cur = LEGAL_DOCS[known ? (param as DocId) : 'privacy'];
  usePageMeta('legal', { title: cur.title + ' — Olympus Labs', description: cur.lead });
  const docs = (Object.keys(LEGAL_DOCS) as DocId[]).map((k) => {
    const on = k === param;
    return { label: LEGAL_DOCS[k].label, sel: on ? 'true' : 'false', go: () => navigate('/legal/' + k), tab: 'font-family: inherit; background: transparent; border: 0; padding: 10px 0; margin-bottom: -1px; cursor: pointer; font-size: 14px; font-weight: 500; border-bottom: 2px solid ' + (on ? '#1a1a1e' : 'transparent') + '; color: ' + (on ? '#1a1a1e' : '#6b6a65') + '; transition: color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1);' };
  });
  const doc = { title: cur.title, lead: cur.lead, summary: cur.summary.map(([g, x]) => ({ g, x })), sections: cur.sections.map(([id, title, x]) => ({ id, title, x })) };
  if (!known) return <Navigate to="/legal/privacy" replace />;
  return (
    <div className="dc pg-legal">
    <div data-page="legal" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader active="" />
      <main style={css("max-width: 720px; margin: 0 auto; padding: clamp(64px, 10vw, 128px) 24px clamp(72px, 10vw, 128px); display: flex; flex-direction: column; gap: 32px;")}>
        <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 20px;")}>
          <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6a65;")}>
            {"Legal"}
          </span>
          <h1 style={css("font-size: clamp(36px, 5.4vw, 60px); font-weight: 500; letter-spacing: -0.04em; line-height: 1; margin: 0;")}>
            {doc.title}
          </h1>
          <p style={css("font-size: 17px; line-height: 1.6; color: #4a4945; margin: 0; max-width: 560px;")}>
            {doc.lead}
          </p>
          <div role="tablist" aria-label="Legal documents" style={css("display: flex; gap: 20px; border-bottom: 1px solid #d8d6d0;")}>
            {(docs).map((d: any, dIndex: number) => (
              <Fragment key={dIndex}>
                <button type="button" role="tab" aria-selected={d.sel} onClick={d.go} style={css(d.tab)}>
                  {d.label}
                </button>
              </Fragment>
            ))}
          </div>
        </div>
        <div role="note" style={css("display: flex; gap: 10px; align-items: baseline; padding: 12px 16px; border: 1px dashed #c9975a; border-radius: 10px; background: rgba(201,151,90,0.08); font-size: 13px; line-height: 1.55; color: #4a4945;")}>
          <span style={css("font-family: var(--font-mono); color: #8a6433;")}>
            {"▲"}
          </span>
          <span>
            <span style={css("font-weight: 500; color: #1a1a1e;")}>
              {"Draft for counsel."}
            </span>
            {" This page is a structure with plain-language summaries. It is not in force and is not legal advice. Counsel must supply the final text before launch."}
          </span>
        </div>
        <ul style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border-top: 1px solid #d8d6d0;")}>
          {(doc.summary).map((s: any, sIndex: number) => (
            <Fragment key={sIndex}>
              <li style={css("display: flex; gap: 14px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid #d8d6d0; font-size: 15px; line-height: 1.5;")}>
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #9c9b95;")}>
                  {s.g}
                </span>
                {s.x}
              </li>
            </Fragment>
          ))}
        </ul>
        {(doc.sections).map((sec: any, secIndex: number) => (
          <Fragment key={secIndex}>
            <section id={sec.id} style={css("display: flex; flex-direction: column; gap: 8px;")}>
              <h2 style={css("font-size: 19px; font-weight: 500; letter-spacing: -0.2px; margin: 0;")}>
                {sec.title}
              </h2>
              <p style={css("font-size: 15px; line-height: 1.7; margin: 0; color: #4a4945;")}>
                {sec.x}
              </p>
            </section>
          </Fragment>
        ))}
        <p style={css("font-size: 14px; color: #6b6a65; margin: 16px 0 0; padding-top: 24px; border-top: 1px solid #d8d6d0; text-align: center;")}>
          {"Questions? "}
          <a href={link("mailto:team@olympuslabsml.com")} style={css("color: #1a1a1e;")}>
            {"team@olympuslabsml.com"}
          </a>
        </p>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
