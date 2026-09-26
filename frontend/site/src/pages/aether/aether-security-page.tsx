import type { ReactNode } from 'react';
import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, DataTable, MarkList, PageHero, Section, SectionHead } from '@site/components/ui';
import { ACCENTS, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/** Aether Security.dc.html */

const CONTROLS: Array<[string, string, ReactNode, Accent, string]> = [
  ['⬡', 'Tenant isolation', 'Records, projections, lenses, and cache keys are scoped to one tenant. Cross-tenant reads are not a feature.', 'cobalt', '2 1 380px'],
  ['✓', 'Consent gating', 'Each event type maps to a required purpose. Batches declare their consent state; capture stops when it is revoked.', 'sage', '1 1 260px'],
  ['■', 'No secrets in browsers', 'Tenant and app ids are identifiers. Server keys stay on the backend path.', 'ember', '1 1 260px'],
  ['◈', 'Human authority', 'Approval thresholds hold critical actions until a person decides. Decisions record who, when, and why.', 'ochre', '1 1 260px'],
  ['⌘', 'Auditability', <>Decisions, actions, and approvals keep an inspectable trail, exportable through <code className="text-caption">/v1/audit/exports</code>.</>, 'solar', '1 1 260px'],
  ['↔', 'Explainability', 'Every inference shows its evidence, confidence, and the edges behind it.', 'steel', '2 1 380px'],
];

const KEY_SCOPES: Array<[string, string, string]> = [
  ['write', 'Send observations to ingestion routes', 'SDKs, connectors, server jobs'],
  ['read', 'Read entities, lenses, exports', 'Analysts, dashboards, integrations'],
  ['admin', 'Create exports, manage keys, delete data', 'Tenant owners only'],
];

const DATA: Array<[string, Accent, string, string[]]> = [
  ['Ownership', 'sage', '✓', ['You own raw data, event streams, and records.', 'Tenant intelligence never crosses tenants.', 'No data export happens without explicit approval.']],
  ['Retention and deletion', 'steel', '↺', ['Retention is set per tenant.', 'Deletion removes raw customer data and stops ingestion.', 'Export first if you need a copy.']],
  ['Redaction', 'ember', '■', ['Secrets, keys, tokens, and password-like fields are redacted from exports.', 'SDK redaction rules strip sensitive fields before sending.']],
];

const DEPLOYMENTS: Array<[string, string, Accent]> = [
  ['Multi-tenant cloud', 'default', 'cobalt'],
  ['Enterprise isolated', 'dedicated resources', 'steel'],
  ['Sovereign', 'regional control', 'sage'],
  ['On-premise', 'your infrastructure', 'ochre'],
  ['Air-gapped', 'no external network', 'ember'],
];

const LIMITS = ['Covert monitoring of people', 'Political manipulation', 'Unauthorized enrichment', 'Unlawful targeting', 'Cross-tenant intelligence leakage'];

export function AetherSecurityPage() {
  const { href } = useSite();
  return (
    <PageShell title="Security and trust — Aether" active="Security">
      <PageHero
        crumbs={[{ label: 'Aether', href: href('aether', '/') }, { label: 'Security' }]}
        accent="ember"
        glyph="✓"
        eyebrow="Security and trust"
        title="Boundaries are part of the design"
        lede="Tenant scope, consent, credentials, human authority, and auditability are built into the data model — not added as settings. Aether does not claim certifications it has not earned."
        actions={
          <>
            <ButtonLink href={href('aether', '/contact?type=security')} accent="ember" arrow>
              Request a security review
            </ButtonLink>
            <ButtonLink href={href('aether', '/procurement')} variant="soft" accent="cobalt" glyph="◈">
              Procurement
            </ButtonLink>
          </>
        }
        toc={[
          { id: 'controls', label: 'Controls', accent: 'ember' },
          { id: 'keys', label: 'Access and keys', accent: 'cobalt' },
          { id: 'data', label: 'Your data', accent: 'sage' },
          { id: 'deploy', label: 'Deployment', accent: 'steel' },
          { id: 'limits', label: 'What we do not build', accent: 'ochre' },
        ]}
      />

      <Section id="controls">
        <SectionHead accent="ember" glyph="■" eyebrow="Controls" title="Six controls every record inherits" />
        <CardRow>
          {CONTROLS.map(([glyph, title, body, accent, flex]) => (
            <Card key={title} accent={accent} flex={flex} glyph={glyph} title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="keys" tone="stone">
        <SectionHead accent="cobalt" glyph="⌘" eyebrow="Access and keys" title="Three key scopes, least privilege by default" />
        <DataTable
          caption="API key scopes"
          headers={['Scope', 'Can', 'Typical holder']}
          rows={KEY_SCOPES.map(([scope, can, holder]) => [<code key="c">{scope}</code>, can, holder])}
        />
        <CardRow>
          <Card
            variant="tint"
            accent="cobalt"
            flex="1 1 300px"
            glyph="●"
            title="Sessions"
            body="Product sessions live in the Aether app at aether.olympuslabsml.com/app. Public pages never store credentials."
          />
          <Card
            variant="tint"
            accent="ochre"
            flex="1 1 300px"
            glyph="▲"
            title="Legacy API keys"
            body="Shown once at creation and never again. Rotate from Settings."
          />
        </CardRow>
      </Section>

      <Section id="data">
        <SectionHead accent="sage" glyph="✓" eyebrow="Your data" title="You own it. Aether keeps it in its lane." />
        <CardRow>
          {DATA.map(([label, accent, mark, items]) => (
            <Card key={label} variant="tint" accent={accent} flex="1 1 300px">
              <span className="text-label uppercase" style={{ color: ACCENTS[accent].ink }}>
                {label}
              </span>
              <MarkList items={items} mark={mark} color={ACCENTS[accent].base} />
            </Card>
          ))}
        </CardRow>
      </Section>

      <Section id="deploy" tone="dark">
        <SectionHead
          dark
          accent="steel"
          glyph="◈"
          eyebrow="Deployment"
          title="Five deployment models"
          lede="From shared cloud to air-gapped. The data model and controls stay the same."
        />
        <CardRow>
          {DEPLOYMENTS.map(([title, body, accent]) => (
            <Card key={title} variant="dark" accent={accent} glyph="◈" title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="limits">
        <SectionHead accent="ochre" glyph="■" eyebrow="Limits" title="What Olympus Labs does not build for" />
        <CardRow>
          <Card variant="tint" accent="ember" flex="1 1 380px">
            <MarkList items={LIMITS} mark="■" color={ACCENTS.ember.base} />
          </Card>
          <Card
            accent="ochre"
            flex="1 1 380px"
            glyph="▲"
            title="Certifications"
            body="Designed for GDPR and SOC 2 readiness. No certification is claimed today. Current documents are available through a security review."
          />
        </CardRow>
      </Section>

      <ClosingCta
        title="Ask for what your review needs."
        body="Answers come from the current deployment, not a marketing sheet."
        primary={{ href: href('aether', '/contact?type=security'), label: 'Request a security review', accent: 'ember' }}
        secondary={{ href: href('aether', '/docs/governance'), label: 'Governance docs' }}
      />
    </PageShell>
  );
}
