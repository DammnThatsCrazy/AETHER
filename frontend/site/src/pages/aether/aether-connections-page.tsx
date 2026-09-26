import { PageShell } from '@site/components/page-shell';
import { ButtonLink, Card, CardRow, ClosingCta, DataTable, PageHero, Section, SectionHead } from '@site/components/ui';
import { BRAND_LOGOS } from '@site/site/brand-logos';
import { MANAGED_CONNECTORS, type ConnectorDirection } from '@site/site/connectors';
import { ACCENTS, soft, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/** Aether Connections.dc.html */

const DIRECTION: Record<ConnectorDirection, [label: string, accent: Accent]> = {
  both: ['↔ in + out', 'steel'],
  in: ['← in', 'sage'],
  out: ['→ out', 'ochre'],
};

const CARRIES: Array<[string, string, string, Accent]> = [
  ['⬡', 'Tenant', 'Every row, vertex, and key is tenant-scoped.', 'cobalt'],
  ['✓', 'Consent', 'The purpose that allowed capture travels with the record.', 'sage'],
  ['↔', 'Provenance', 'The source system, connector, and original id.', 'steel'],
  ['◉', 'Freshness', 'When it was observed and when it arrived.', 'ochre'],
  ['◈', 'Authority', 'Who or what was allowed to produce it.', 'solar'],
];

/** Readiness vocabulary shared with the app's connection views. */
export const READINESS: Array<[string, string, string]> = [
  ['● available', 'Enabled with current deployment evidence.', ACCENTS.sage.ink],
  ['◈ gated', 'Available after configuration, credentials, or plan activation.', ACCENTS.cobalt.ink],
  ['▲ pilot', 'Bounded validation in progress.', ACCENTS.ochre.ink],
  ['■ unavailable', 'A required dependency is not present.', ACCENTS.ember.ink],
  ['○ planned', 'Documented direction, not a current capability.', '#6b6a65'],
];

const chip = 'rounded-full border border-line bg-stone-50 px-2 py-[3px] font-mono text-[11px]';

export function AetherConnectionsPage() {
  const { href } = useSite();
  const count = MANAGED_CONNECTORS.length;
  return (
    <PageShell title="Connections — Aether" active="Connections">
      <PageHero
        crumbs={[{ label: 'Aether', href: href('aether', '/') }, { label: 'Connections' }]}
        accent="steel"
        glyph="↔"
        eyebrow="Connections"
        title="Many ways in. One governed record."
        lede="Aether connects to the systems where people, agents, and value flows already leave evidence. Every path lands in the same record with its source, tenant, consent, and freshness attached."
        actions={
          <>
            <ButtonLink href={href('aether', '/docs/connector-catalog')} accent="steel" glyph="⚙">
              Connector catalog
            </ButtonLink>
            <ButtonLink href={href('aether', '/contact?type=developer')} variant="soft" accent="ochre">
              Request a connector
            </ButtonLink>
          </>
        }
        toc={[
          { id: 'paths', label: 'Connection paths', accent: 'steel' },
          { id: 'catalog', label: 'Managed connectors', accent: 'cobalt' },
          { id: 'carries', label: 'What every record carries', accent: 'sage' },
          { id: 'readiness', label: 'Readiness', accent: 'ochre' },
        ]}
      />

      <Section id="paths">
        <SectionHead
          accent="steel"
          glyph="→"
          eyebrow="Connection paths"
          title="Six ways to connect, no rip-and-replace"
          lede="Start with the smallest set of sources that answers the first question. Add the rest as the graph compounds."
        />
        <CardRow>
          <Card
            href={href('aether', '/docs/sdk-overview')}
            accent="cobalt"
            flex="2 1 420px"
            glyph="⌘"
            tag="4 SDKs"
            title="First-party SDKs"
            body="Consent-gated page, screen, identity, commerce, and journey evidence from your own apps."
            cta="SDK overview"
          >
            <span className="flex flex-wrap gap-1.5">
              {['@aether/web', 'AetherSDK', 'sdk-android', '@aether/react-native'].map((x) => (
                <span key={x} className={chip}>
                  {x}
                </span>
              ))}
            </span>
          </Card>
          <Card
            href="#catalog"
            accent="steel"
            flex="1 1 260px"
            glyph="⚙"
            tag={`${count} providers`}
            title="Managed connectors"
            body="Authorization, sync, cursors, and normalization handled by Aether."
            cta="See the catalog"
          />
          <Card accent="ochre" flex="1 1 220px" glyph="↯" tag="push" title="Signed webhooks" body="Any system that can POST. HMAC-verified and idempotent." />
          <Card
            accent="sage"
            flex="1 1 220px"
            glyph="≡"
            tag="server"
            title="Feed API"
            body={
              <>
                Server-side events through <code className="text-caption">/v1/ingest/feed</code>.
              </>
            }
          />
          <Card
            href={href('aether', '/docs/imports')}
            accent="solar"
            flex="1 1 220px"
            glyph="⇪"
            tag="files"
            title="Imports"
            body="CSV, JSON, and JSONL mapped onto nine primitives, with rollback."
            cta="How imports work"
          />
          <Card accent="ember" flex="1 1 220px" glyph="⬡" tag="agents" title="Agent observations" body="Tasks, tool calls, and outcomes from agents acting for people." />
        </CardRow>
      </Section>

      <Section id="catalog" tone="stone">
        <SectionHead
          accent="cobalt"
          glyph="⚙"
          eyebrow="Managed connectors"
          title={`${count} providers today, plus anything you can reach`}
          lede="Inbound connectors bring evidence in. Outbound connectors carry approved decisions to the tools your team works in."
        />
        <ul className="m-0 flex list-none flex-wrap gap-3 p-0">
          {MANAGED_CONNECTORS.map((c) => {
            const [label, accent] = DIRECTION[c.direction];
            return (
              <li
                key={c.name}
                className="box-border flex min-w-0 flex-[1_1_250px] flex-col gap-2.5 rounded-card border border-line bg-stone-50 p-4 transition-colors duration-120 hover:border-line-strong hover:bg-white"
              >
                <span className="flex items-center gap-2.5">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] border border-stone-200 bg-white">
                    <img src={BRAND_LOGOS[c.name]} alt="" className="h-5 w-5 object-contain" />
                  </span>
                  <span className="flex flex-col gap-px">
                    <span className="text-[15px] font-medium">{c.name}</span>
                    <span className="text-caption text-slate">{c.category}</span>
                  </span>
                  <span
                    className="ml-auto whitespace-nowrap rounded-full px-2 py-0.5 font-mono text-[11px]"
                    style={{ background: soft(accent), color: ACCENTS[accent].ink }}
                  >
                    {label}
                  </span>
                </span>
                <span className="text-caption leading-[1.5] text-graphite-body">{c.carries}</span>
              </li>
            );
          })}
        </ul>
        <CardRow>
          <Card
            variant="tint"
            accent="ochre"
            flex="1 1 300px"
            glyph="↯"
            title="Signed webhook"
            body={
              <>
                Connect any other system. Aether verifies the signature and dedupes on <code className="text-caption">tenant_id:event_id</code>.
              </>
            }
          />
          <Card
            variant="tint"
            accent="steel"
            flex="1 1 300px"
            href={href('aether', '/contact?type=developer')}
            glyph="+"
            title="Need another connector?"
            body="Tell us the system and the evidence it holds. Requests shape the roadmap."
            cta="Request a connector"
          />
        </CardRow>
      </Section>

      <Section id="carries">
        <SectionHead
          accent="sage"
          glyph="●"
          eyebrow="What every record carries"
          title="The connection method answers where evidence came from"
          lede="Value appears when that evidence keeps its context and joins the right relationships."
        />
        <CardRow>
          {CARRIES.map(([glyph, title, body, accent]) => (
            <Card key={title} variant="rule" accent={accent} glyph={glyph} title={title} body={body} />
          ))}
        </CardRow>
      </Section>

      <Section id="readiness" tone="stone">
        <SectionHead accent="ochre" glyph="▲" eyebrow="Readiness" title="Readiness is shown per connection and per tenant" />
        <DataTable
          caption="Connection readiness states"
          headers={['State', 'Meaning']}
          rows={READINESS.map(([state, meaning, color]) => [
            <span key="s" className="font-mono" style={{ color }}>
              {state}
            </span>,
            meaning,
          ])}
        />
      </Section>

      <ClosingCta
        title="Start with the sources you already run."
        body="Most pilots begin with two or three connectors and the web SDK."
        primary={{ href: href('aether', '/contact?type=pilot'), label: 'Request a pilot', accent: 'sage' }}
        secondary={{ href: href('aether', '/docs/quickstart-web'), label: 'Read the quickstart' }}
      />
    </PageShell>
  );
}
