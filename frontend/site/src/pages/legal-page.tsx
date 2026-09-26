import type { CSSProperties } from 'react';
import { Navigate, useParams } from 'react-router-dom';
import { PageShell } from '@site/components/page-shell';
import { Glyph } from '@site/components/ui';
import { ACCENTS, soft, tint, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/**
 * Legal.dc.html, shared by both sites at /legal/privacy and /legal/terms.
 * The text is the design's plain-language structure, not final legal copy, so
 * the draft notice stays visible until counsel supplies the final text.
 */

type DocId = 'privacy' | 'terms';

interface LegalDoc {
  glyph: string;
  accent: Accent;
  title: string;
  updated: string;
  lead: string;
  summary: Array<[glyph: string, accent: Accent, text: string]>;
  sections: Array<[id: string, title: string, text: string]>;
}

export const LEGAL_DOCS: Record<DocId, LegalDoc> = {
  privacy: {
    glyph: '✓',
    accent: 'sage',
    title: 'Privacy and data use',
    updated: 'draft',
    lead: 'How Olympus Labs handles personal information on its public sites, and how Aether processes customer data on a customer’s behalf.',
    summary: [
      ['✓', 'sage', 'Customers own their data. Aether processes it on their behalf.'],
      ['⬡', 'cobalt', 'Tenant data never crosses tenants.'],
      ['■', 'ember', 'No selling of personal information.'],
    ],
    sections: [
      ['scope', 'Scope', 'This notice covers the Olympus Labs and Aether public websites, documentation, status page, and contact forms. Processing inside a customer’s Aether tenant is governed by that customer’s agreement.'],
      ['collect', 'What is collected', 'Information you submit through contact and sign-up forms, and limited site analytics after consent. Aether SDKs deployed by customers collect only what the customer configures and the purposes a person grants.'],
      ['use', 'How it is used', 'To answer inquiries, provide the service, secure it, and improve it. Contact details are used only to reply unless you opt in to more.'],
      ['roles', 'Controller and processor', 'For public-site data, Olympus Labs is the controller. For data inside a tenant, the customer is the controller and Olympus Labs acts as processor.'],
      ['share', 'Sharing and sub-processors', 'Shared only with service providers needed to run the service, such as payment processing through Stripe. A sub-processor list is available on request.'],
      ['retention', 'Retention and deletion', 'Kept only as long as needed. Deleting operational data removes raw customer data and stops ingestion.'],
      ['rights', 'Your rights', 'Depending on where you live, you may request access, correction, deletion, or a copy of your information.'],
      ['contact', 'Contact', 'Send privacy requests to contact@olympuslabsml.com.'],
    ],
  },
  terms: {
    glyph: '◈',
    accent: 'cobalt',
    title: 'Terms and use',
    updated: 'draft',
    lead: 'The terms that govern use of the Olympus Labs and Aether websites and, where no separate agreement exists, the Aether service.',
    summary: [
      ['◈', 'cobalt', 'A signed customer agreement takes precedence over these terms.'],
      ['▲', 'ochre', 'Aether is pre-production private alpha.'],
      ['■', 'ember', 'Prohibited uses include covert monitoring and unlawful targeting.'],
    ],
    sections: [
      ['acceptance', 'Acceptance', 'Using the sites or service means accepting these terms. A signed agreement with Olympus Labs replaces them where the two conflict.'],
      ['service', 'The service', 'Aether is offered in pre-production private alpha. Features may change, and availability is not guaranteed.'],
      ['accounts', 'Accounts and keys', 'You are responsible for your account, the keys you create, and what is sent with them. Keep server keys out of client code.'],
      ['acceptable', 'Acceptable use', 'Do not use the service for covert monitoring of people, political manipulation, unauthorized enrichment, unlawful targeting, or to access another tenant’s data.'],
      ['data', 'Your data', 'You own the data you send. You grant Olympus Labs the rights needed to process it to provide the service.'],
      ['billing', 'Billing', 'Paid plans are billed through Stripe according to the plan selected at checkout.'],
      ['liability', 'Warranties and liability', 'To be supplied by counsel.'],
      ['changes', 'Changes', 'Material changes will be announced before they take effect.'],
    ],
  },
};

const isDocId = (v: string | undefined): v is DocId => v === 'privacy' || v === 'terms';

export function LegalPage() {
  const { doc: param } = useParams();
  const { site, href } = useSite();
  if (!isDocId(param)) return <Navigate to="/legal/privacy" replace />;
  const doc = LEGAL_DOCS[param];
  const c = ACCENTS[doc.accent];

  return (
    <PageShell title={`${doc.title} — ${site === 'olympus' ? 'Olympus Labs' : 'Aether'}`}>
      <div className="mx-auto grid max-w-page items-start gap-8 px-6 pb-[72px] pt-[clamp(32px,6vw,64px)] md:grid-cols-[minmax(200px,280px)_minmax(0,1fr)] lg:gap-x-[88px]">
        <aside className="flex flex-col gap-3.5 md:sticky md:top-[72px]">
          <span className="text-label uppercase text-slate">Legal</span>
          <nav aria-label="Legal documents" className="flex flex-col gap-1.5">
            {(Object.keys(LEGAL_DOCS) as DocId[]).map((id) => {
              const d = LEGAL_DOCS[id];
              const on = id === param;
              return (
                <a
                  key={id}
                  href={href(site, `/legal/${id}`)}
                  aria-current={on ? 'page' : undefined}
                  className={
                    'flex min-h-[42px] items-center gap-2.5 rounded-control border px-3.5 text-[14px] font-medium no-underline transition-colors duration-120 ease-site ' +
                    (on ? 'text-stone-50 hover:text-stone-50' : 'border-line bg-stone-100 text-ink hover:text-ink hover:[background:var(--hover-bg)]')
                  }
                  style={
                    on
                      ? { background: ACCENTS[d.accent].ink, borderColor: ACCENTS[d.accent].ink }
                      : ({ '--hover-bg': soft(d.accent) } as CSSProperties)
                  }
                >
                  <Glyph>
                    <span style={{ color: on ? '#f5f4f1' : ACCENTS[d.accent].ink }}>{d.glyph}</span>
                  </Glyph>
                  {d.title}
                </a>
              );
            })}
          </nav>
          <nav aria-label="On this page" className="flex flex-col gap-1 border-t border-line pt-2">
            {doc.sections.map(([id, title]) => (
              <a key={id} href={`#${id}`} className="py-1 text-body-sm text-slate no-underline hover:text-ink">
                {title}
              </a>
            ))}
          </nav>
        </aside>

        <article className="flex min-w-0 max-w-[760px] flex-col gap-5">
          <div
            role="note"
            className="flex items-baseline gap-2.5 rounded-[10px] border border-dashed border-ochre px-4 py-3 text-body-sm leading-[1.55]"
            style={{ background: tint('ochre', 0.08) }}
          >
            <Glyph className="text-ochre-ink">▲</Glyph>
            <span>
              <span className="font-medium">Draft for counsel.</span> This page is a structure with plain-language summaries.
              It is not in force and is not legal advice. Counsel must supply the final text before launch.
            </span>
          </div>

          <div className="flex flex-col gap-2.5">
            <span className="inline-flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="flex h-9 w-9 items-center justify-center rounded-[10px] font-mono text-[16px]"
                style={{ background: soft(doc.accent), color: c.ink }}
              >
                {doc.glyph}
              </span>
              <span className="font-mono text-caption text-slate">last updated · {doc.updated}</span>
            </span>
            <h1 className="m-0 text-[clamp(32px,4.4vw,44px)] font-medium leading-[1.08] tracking-[-0.03em]">{doc.title}</h1>
            <p className="m-0 text-[16px] leading-[1.6] text-graphite-body">{doc.lead}</p>
          </div>

          <div className="flex flex-wrap gap-3">
            {doc.summary.map(([glyph, accent, text]) => (
              <div
                key={text}
                className="flex flex-[1_1_200px] items-baseline gap-2.5 rounded-card border p-3.5"
                style={{ background: soft(accent), borderColor: tint(accent, 0.33) }}
              >
                <Glyph>
                  <span style={{ color: ACCENTS[accent].ink }}>{glyph}</span>
                </Glyph>
                <span className="text-body-sm leading-[1.5]">{text}</span>
              </div>
            ))}
          </div>

          {doc.sections.map(([id, title, text], i) => (
            <section key={id} id={id} className="flex scroll-mt-20 flex-col gap-2 border-t border-stone-200 pt-[18px]">
              <h2 className="m-0 flex items-baseline gap-2.5 text-[20px] font-medium tracking-[-0.3px]">
                <span className="font-mono text-caption" style={{ color: c.ink }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                {title}
              </h2>
              <p className="m-0 text-[14px] leading-[1.7] text-[#3a3935]">{text}</p>
            </section>
          ))}

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-line bg-stone-100 px-[18px] py-4">
            <span className="text-[14px]">Questions about this document?</span>
            <a
              href="mailto:contact@olympuslabsml.com"
              className="inline-flex min-h-10 items-center gap-2 whitespace-nowrap rounded-control bg-cobalt-ink px-4 text-body-sm font-medium text-stone-50 no-underline hover:bg-cobalt hover:text-stone-50"
            >
              <Glyph>✉</Glyph>
              contact@olympuslabsml.com
            </a>
          </div>
        </article>
      </div>
    </PageShell>
  );
}
