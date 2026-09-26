import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, DataTable, PageHero, Section, SectionHead, StepList } from '@site/components/ui';
import { ProviderMark } from '@site/components/provider-mark';
import { ACCENTS, soft, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/**
 * Aether Procurement.dc.html. The design routes "Start procurement" to a
 * procurement contact topic that Contact does not have; security review is
 * the topic that covers DPA, questionnaires, and deployment review.
 */

const PROCESS: Array<{ title: string; body: string; accent: Accent }> = [
  { title: 'Introduction', body: 'The relationship question, the systems involved, and the outcome that matters.', accent: 'cobalt' },
  { title: 'Security review', body: 'Architecture, tenant scope, consent, retention, and deployment model.', accent: 'ember' },
  { title: 'Pilot scope', body: 'Sources, success measures, baseline, and timeline — agreed in writing.', accent: 'ochre' },
  { title: 'Order', body: 'Package, term, and billing. Self-service plans check out through Stripe.', accent: 'solar' },
  { title: 'Onboarding', body: 'Connect sources, verify first events, review the first perspective.', accent: 'sage' },
];

const DOCUMENTS: Array<[string, string, string, string]> = [
  ['Security overview', 'Controls, key scopes, incident response', '● on request', ACCENTS.sage.ink],
  ['Architecture summary', 'Pipeline, storage tiers, tenancy', '● on request', ACCENTS.sage.ink],
  ['Data processing terms', 'Roles, sub-processors, retention', '▲ owner review', ACCENTS.ochre.ink],
  ['Security questionnaire', 'Your standard form, answered', '● on request', ACCENTS.sage.ink],
  ['Certification reports', 'SOC 2 and similar', '○ not available', '#6b6a65'],
];

const FAQ: Array<[string, string, Accent]> = [
  ['Who owns the data?', 'You own raw operational data, event streams, and records. Tenant intelligence never crosses tenants.', 'cobalt'],
  ['Can we deploy in our own environment?', 'Yes. Enterprise isolated, sovereign, on-premise, and air-gapped models are supported.', 'sage'],
  ['What happens at the end of a term?', 'Export through the data exchange API, then request deletion. Deletion removes raw data and stops ingestion.', 'ochre'],
  ['Is Aether generally available?', 'No. Aether is in pre-production private alpha.', 'ember'],
  ['How is support provided?', 'Through contact@olympuslabsml.com and a named contact during pilots.', 'steel'],
];

export function AetherProcurementPage() {
  const { href } = useSite();
  const startProcurement = href('aether', '/contact?type=security');
  return (
    <PageShell title="Procurement — Aether">
      <PageHero
        crumbs={[{ label: 'Aether', href: href('aether', '/') }, { label: 'Procurement' }]}
        accent="cobalt"
        glyph="◈"
        eyebrow="Procurement"
        title="Everything your review will ask for, in one place"
        lede="How Aether is bought, billed, reviewed, and deployed — and what to request at each step."
        actions={
          <>
            <ButtonLink href={startProcurement} arrow>
              Start procurement
            </ButtonLink>
            <ButtonLink href={href('aether', '/pricing')} variant="soft" accent="ochre" glyph="↑">
              Compare packages
            </ButtonLink>
          </>
        }
        toc={[
          { id: 'process', label: 'Process', accent: 'cobalt' },
          { id: 'commercial', label: 'Commercial', accent: 'ochre' },
          { id: 'documents', label: 'Documents', accent: 'sage' },
          { id: 'faq', label: 'Questions', accent: 'steel' },
        ]}
      />

      <Section id="process">
        <SectionHead accent="cobalt" glyph="→" eyebrow="Process" title="Five steps from first call to live" />
        <StepList steps={PROCESS} />
      </Section>

      <Section id="commercial" tone="stone">
        <SectionHead accent="ochre" glyph="↑" eyebrow="Commercial" title="How Aether is priced and billed" />
        <CardRow>
          <Card
            href={href('aether', '/pricing')}
            accent="cobalt"
            flex="1 1 280px"
            glyph="◈"
            title="Packages"
            body="Alpha, Beta, Gamma, and Delta scale with graph depth, entity intelligence, and throughput."
            cta="See pricing"
          />
          <Card flex="1 1 280px" title="Billing" body="Monthly subscriptions and invoices through Stripe. Enterprise terms by agreement.">
            <span className="inline-flex items-center gap-1.5 text-caption text-graphite-body">
              <ProviderMark provider="stripe" size={16} className="rounded-control border border-stone-200 bg-white" />
              Payments processed by Stripe
            </span>
          </Card>
          <Card
            href={href('aether', '/contact?type=pilot')}
            accent="steel"
            flex="1 1 280px"
            glyph="⚗"
            title="Pilots"
            body="Bounded in scope and time, with the success measures agreed up front."
            cta="Request a pilot"
          />
        </CardRow>
      </Section>

      <Section id="documents">
        <SectionHead
          accent="sage"
          glyph="✓"
          eyebrow="Documents"
          title="Available through a review"
          lede="Request any of these through Contact → Security review. Each comes from the current deployment."
        />
        <DataTable
          caption="Procurement documents"
          headers={['Document', 'What it covers', 'Status']}
          rows={DOCUMENTS.map(([doc, covers, status, color]) => [
            doc,
            covers,
            <span key="s" className="font-mono" style={{ color }}>
              {status}
            </span>,
          ])}
        />
      </Section>

      <Section id="faq" tone="stone">
        <SectionHead accent="steel" glyph="?" eyebrow="Questions" title="Common procurement questions" />
        <div className="flex flex-col gap-2">
          {FAQ.map(([q, a, accent]) => (
            <details
              key={q}
              className="group rounded-[10px] border border-l-[3px] border-line bg-stone-50"
              style={{ borderLeftColor: ACCENTS[accent].base }}
            >
              <summary className="flex cursor-pointer list-none items-center gap-2.5 px-4 py-[13px] text-[14px] font-medium [&::-webkit-details-marker]:hidden">
                <span
                  aria-hidden="true"
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-control font-mono"
                  style={{ background: soft(accent), color: ACCENTS[accent].ink }}
                >
                  <span className="group-open:hidden">+</span>
                  <span className="hidden group-open:inline">−</span>
                </span>
                {q}
              </summary>
              <div className="pb-3.5 pl-[46px] pr-4 text-body-sm leading-[1.65] text-[#3a3935]">{a}</div>
            </details>
          ))}
        </div>
      </Section>

      <ClosingCta
        title="Tell us what your process needs."
        body="We will route it to the person who can answer."
        primary={{ href: startProcurement, label: 'Start procurement', accent: 'cobalt' }}
        secondary={{ href: href('aether', '/security'), label: 'Security overview' }}
      />
    </PageShell>
  );
}
