import { useCallback, useEffect, useState, type CSSProperties } from 'react';
import { PageShell } from '@site/components/page-shell';
import { RelationshipExplorer } from '@site/components/relationship-explorer';
import { useSite } from '@site/site/site-context';
import { ACCENTS, tint } from '@site/site/palette';
import { ProviderMark } from '@site/components/provider-mark';
import {
  ACTOR_CHIPS,
  CONTACT_ROUTES,
  GENERIC_CONNECTOR_GLYPHS,
  HOME_TABS,
  PRINCIPLES,
  RESEARCH_AREAS,
  UNIFY_GROUPS,
  isHomeTab,
  type HomeTab,
} from './olympus-home-content';
import { BrandMark } from '@site/components/brand-mark';

const eyebrow = 'text-label uppercase';
/** Hover to a runtime accent color: set --hover-bg / --hover-border on the element. */
const accentHover = 'hover:[background:var(--hover-bg)] hover:[border-color:var(--hover-border)]';
const vars = (values: Record<string, string>) => values as CSSProperties;

/**
 * Per-side border colors. Mixing the borderColor shorthand with one side's
 * color breaks when either changes on rerender.
 */
const sideBorders = (color: string): CSSProperties => ({
  borderTopColor: color,
  borderRightColor: color,
  borderBottomColor: color,
  borderLeftColor: color,
});

function tabFromHash(): HomeTab | null {
  if (typeof window === 'undefined') return null;
  const hash = window.location.hash.replace('#', '');
  return isHomeTab(hash) ? hash : null;
}

export function OlympusHomePage() {
  const { href } = useSite();
  const [tab, setTab] = useState<HomeTab>(() => tabFromHash() ?? 'company');
  const [unify, setUnify] = useState(UNIFY_GROUPS[0]!.id);
  const [openResearch, setOpenResearch] = useState<string | null>(null);

  const show = useCallback((next: HomeTab) => {
    setTab(next);
    const el = document.getElementById('tabs');
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 56, behavior: 'smooth' });
  }, []);

  // Header links such as /#contact select a tab.
  useEffect(() => {
    const onHash = () => {
      const next = tabFromHash();
      if (next) show(next);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, [show]);

  const group = UNIFY_GROUPS.find((g) => g.id === unify) ?? UNIFY_GROUPS[0]!;
  const groupColors = ACCENTS[group.accent];
  const unifyTotal = UNIFY_GROUPS.reduce((sum, g) => sum + g.items.length, 0);
  const isConnectors = group.id === 'connectors';

  return (
    <PageShell title="Olympus Labs — Governed intelligence infrastructure">
      {/* Hero */}
      <section className="border-b border-line">
        <div className="mx-auto flex max-w-page flex-col gap-8 px-6 pb-[clamp(48px,7vw,88px)] pt-[clamp(56px,9vw,128px)]">
          <div className="grid items-end gap-10 [grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr))]">
            <div className="flex flex-col gap-[22px]">
              <span className={`inline-flex items-center gap-2 ${eyebrow} text-slate`}>
                <BrandMark brand="olympus" className="h-[18px] w-[18px]" />
                Olympus Labs · research and infrastructure
              </span>
              <h1 className="m-0 text-balance text-[clamp(44px,6.4vw,80px)] font-medium leading-[0.98] tracking-[-0.042em]">
                Intelligence infrastructure for human and agentic economies.
              </h1>
            </div>
            <div className="flex flex-col gap-[22px] pb-1.5">
              <p className="m-0 max-w-[520px] text-pretty text-[17px] leading-[1.6] text-graphite-body">
                Olympus Labs builds governed intelligence systems that unify people, organizations, autonomous agents, and
                economic activity — so relationships can be understood, explained, and acted on by the people accountable
                for them.
              </p>
              <div className="flex flex-wrap gap-3">
                <a
                  href={href('aether', '/')}
                  className="inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-control border border-cobalt-ink bg-cobalt-ink px-5 text-[14px] font-medium text-stone-50 no-underline transition-colors duration-120 ease-site hover:bg-[#244563] hover:text-stone-50"
                >
                  <span className="inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-control bg-stone-50">
                    <BrandMark brand="aether" className="h-4 w-4" />
                  </span>
                  Meet Aether
                  <span aria-hidden="true" className="font-mono">
                    →
                  </span>
                </a>
                <button
                  type="button"
                  onClick={() => show('principles')}
                  className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-control border border-sage/45 bg-sage/[0.16] px-5 text-[14px] font-medium text-sage-ink transition-colors duration-120 ease-site hover:bg-sage/[0.26]"
                >
                  <span aria-hidden="true" className="font-mono">
                    ✓
                  </span>
                  Our principles
                </button>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap gap-3">
            {ACTOR_CHIPS.map((chip) => (
              <div
                key={chip.label}
                className="flex flex-[1_1_200px] flex-col gap-1 rounded-lg border px-5 py-[18px]"
                style={{ background: tint(chip.accent, 0.12), borderColor: tint(chip.accent, 0.35) }}
              >
                <span className="font-mono text-body-sm" style={{ color: ACCENTS[chip.accent].ink }}>
                  {chip.label}
                </span>
                <span className="text-caption text-graphite-body">{chip.body}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Thesis */}
      <section data-theme="dark" className="bg-ink text-bone">
        <div className="mx-auto grid max-w-page gap-10 px-6 py-[clamp(64px,9vw,112px)] [grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr))]">
          <div className="flex flex-col gap-3.5">
            <span className={`${eyebrow} text-ochre`}>◈ The thesis</span>
            <h2 className="m-0 text-balance text-[clamp(28px,3.6vw,44px)] font-medium leading-[1.08] tracking-[-0.025em] text-bone">
              The future economy will not run only through people.
            </h2>
          </div>
          <div className="flex flex-col gap-3.5 text-[16px] leading-[1.65]">
            <p className="m-0 text-mist">
              It will run through people, autonomous agents, machine systems, and AI-native organizations working together.
              Today their data, identities, and attribution are fragmented across systems.
            </p>
            <p className="m-0 text-mist">
              As those interactions multiply, fragmented awareness becomes expensive: lost visibility, lost leverage, lost
              adaptability.
            </p>
            <p className="m-0 text-bone">
              The organizations that succeed will understand and coordinate those relationships in real time. Olympus Labs
              builds the infrastructure for that.
            </p>
          </div>
        </div>
      </section>

      {/* What we build */}
      <section id="build" className="border-b border-line">
        <div className="mx-auto flex max-w-page flex-col gap-6 px-6 py-[clamp(64px,9vw,112px)]">
          <div className="grid items-end gap-6 [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
            <div className="flex flex-col gap-3">
              <span className={`${eyebrow} text-cobalt`}>What we build</span>
              <h2 className="m-0 text-[clamp(28px,3.6vw,44px)] font-medium leading-[1.06] tracking-[-0.028em]">
                Relationships are the unit of intelligence
              </h2>
            </div>
            <p className="m-0 text-[15px] leading-[1.6] text-slate">
              Every relationship between a person and an agent, or an agent and another agent, is evidence. Choose one to see
              what it means and what comes from understanding it.
            </p>
          </div>
          <RelationshipExplorer />
        </div>
      </section>

      {/* Tabs */}
      <section id="tabs" className="border-b border-line bg-stone-100">
        <div className="mx-auto flex max-w-page flex-col gap-6 px-6 pb-[clamp(48px,7vw,88px)] pt-[clamp(40px,6vw,72px)]">
          <div
            role="tablist"
            aria-label="Olympus Labs"
            className="flex max-w-full flex-wrap gap-1.5 self-start rounded-[14px] border border-line bg-stone-50 p-1"
          >
            {HOME_TABS.map((t) => {
              const on = t.id === tab;
              const c = ACCENTS[t.accent];
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  id={`tab-${t.id}`}
                  aria-selected={on}
                  aria-controls={`panel-${t.id}`}
                  onClick={() => setTab(t.id)}
                  className={
                    'inline-flex min-h-10 cursor-pointer items-center gap-2 whitespace-nowrap rounded-control border-0 px-4 text-[14px] font-medium transition-colors duration-120 ease-site ' +
                    (on ? 'text-stone-50' : 'bg-transparent text-ink hover:[background:var(--hover-bg)]')
                  }
                  style={on ? { background: c.ink } : vars({ '--hover-bg': tint(t.accent, 0.12) })}
                >
                  <span aria-hidden="true" className="font-mono" style={{ color: on ? '#f5f4f1' : c.base }}>
                    {t.glyph}
                  </span>
                  {t.label}
                </button>
              );
            })}
          </div>

          {tab === 'company' && (
            <div role="tabpanel" id="panel-company" aria-labelledby="tab-company" className="flex flex-wrap gap-3">
              <div className="box-border flex min-h-[240px] flex-[2_1_460px] flex-col gap-3 rounded-card bg-ink p-6 text-bone">
                <span className={`${eyebrow} text-mist`}>The company</span>
                <span className="text-[24px] font-medium leading-[1.3] tracking-[-0.4px] text-bone">
                  A research and infrastructure company building governed intelligence systems for the next generation of
                  operational, economic, and autonomous infrastructure.
                </span>
                <span className="mt-auto text-body-sm text-mist">
                  Goal: enduring infrastructure for human and agentic coordination.
                </span>
              </div>
              <a
                href={href('aether', '/')}
                className="box-border flex min-h-[240px] flex-[1_1_280px] flex-col gap-3 rounded-card border border-cobalt/35 bg-cobalt/10 p-6 text-ink no-underline transition-colors duration-120 ease-site hover:border-cobalt hover:bg-cobalt/[0.16] hover:text-ink"
              >
                <span className="flex items-center gap-2.5">
                  <BrandMark brand="aether" className="h-[30px] w-[30px]" />
                  <span className="text-[20px] font-medium">Aether</span>
                  <span className="rounded-full bg-ochre/20 px-2 py-0.5 font-mono text-[11px] text-ochre-ink">private alpha</span>
                </span>
                <span className="text-[15px] leading-[1.5]">
                  The flagship product: intelligence graph infrastructure that maps people, agents, organizations, and value
                  flows.
                </span>
                <span className="mt-auto text-[14px] font-medium text-cobalt-ink">Explore Aether →</span>
              </a>

              <div className="box-border flex flex-[1_1_100%] flex-col gap-3.5 rounded-lg border border-line bg-stone-50 p-6">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className={`${eyebrow} text-sage-ink`}>What we unify</span>
                  <span className="text-caption text-slate">
                    {unifyTotal} connections across {UNIFY_GROUPS.length} groups · pick one
                  </span>
                </div>
                <div role="tablist" aria-label="What we unify" className="flex flex-wrap gap-1.5">
                  {UNIFY_GROUPS.map((g) => {
                    const on = g.id === group.id;
                    const c = ACCENTS[g.accent];
                    return (
                      <button
                        key={g.id}
                        type="button"
                        role="tab"
                        aria-selected={on}
                        onClick={() => setUnify(g.id)}
                        className={
                          'inline-flex min-h-9 cursor-pointer items-center gap-[7px] whitespace-nowrap rounded-full border px-3 text-body-sm font-medium transition-colors duration-120 ease-site ' +
                          (on ? 'text-stone-50' : `border-line bg-stone-100 ${accentHover}`)
                        }
                        style={
                          on
                            ? { background: c.ink, borderColor: c.ink }
                            : { color: c.ink, ...vars({ '--hover-bg': tint(g.accent, 0.16), '--hover-border': c.base }) }
                        }
                      >
                        <span aria-hidden="true" className="font-mono">
                          {g.glyph}
                        </span>
                        {g.label}
                        <span
                          className="rounded-full px-1.5 py-px font-mono text-[11px]"
                          style={{ background: on ? 'rgba(245,244,241,0.25)' : tint(g.accent, 0.16) }}
                        >
                          {g.items.length}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <div
                  className="flex flex-col gap-3 rounded-card border border-l-[3px] p-4"
                  style={{ background: tint(group.accent, 0.14), ...sideBorders(tint(group.accent, 0.33)), borderLeftColor: groupColors.base }}
                >
                  <div className="flex flex-col gap-1">
                    <span className="text-[16px] font-medium">{group.title}</span>
                    <span className="max-w-[760px] text-body-sm text-graphite-body">{group.body}</span>
                  </div>
                  <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                    {group.items.map(([name, detail]) => (
                      <li
                        key={name}
                        className={
                          'inline-flex items-baseline gap-[7px] rounded-full border bg-stone-50 text-caption ' +
                          (isConnectors ? 'py-[5px] pl-[5px] pr-3' : 'px-[11px] py-1.5')
                        }
                        style={{ borderColor: tint(group.accent, 0.33) }}
                      >
                        {isConnectors && <ConnectorMark name={name} />}
                        <span className="font-medium text-ink">{name}</span>
                        {detail && <span className="text-slate">{detail}</span>}
                      </li>
                    ))}
                  </ul>
                  {isConnectors && (
                    <div className="flex flex-wrap gap-1.5 border-t border-dashed border-line-strong pt-1">
                      <a
                        href={href('aether', '/docs/connector-catalog')}
                        className="inline-flex min-h-[34px] items-center gap-2 whitespace-nowrap rounded-full bg-steel-ink px-3 text-caption font-medium text-stone-50 no-underline hover:bg-[#345a78] hover:text-stone-50"
                      >
                        <span aria-hidden="true" className="font-mono">
                          +
                        </span>
                        Connect any system with a signed webhook or the feed API
                      </a>
                      <a
                        href={href('olympus', '/contact?type=developer')}
                        className="inline-flex min-h-[34px] items-center gap-2 whitespace-nowrap rounded-full border border-steel/50 bg-stone-50 px-3 text-caption font-medium text-steel-ink no-underline hover:bg-steel/[0.14] hover:text-steel-ink"
                      >
                        <span aria-hidden="true" className="font-mono">
                          ✉
                        </span>
                        Request a connector
                      </a>
                    </div>
                  )}
                  <span className="font-mono text-[11px] text-slate">source · {group.source}</span>
                </div>
              </div>

              <div className="box-border flex flex-[1_1_300px] flex-col gap-2 rounded-lg border border-ochre/40 bg-ochre/10 p-6">
                <span className={`${eyebrow} text-ochre-ink`}>Why ecommerce first</span>
                <span className="text-[14px] leading-[1.55]">
                  High-volume signals, attribution complexity, fraud exposure, and fragmented identity — with outcomes that
                  are fast to measure.
                </span>
              </div>
              <div className="box-border flex flex-[1_1_300px] flex-col gap-2 rounded-lg border border-line bg-stone-50 p-6">
                <span className={`${eyebrow} text-steel-ink`}>How we work</span>
                <span className="text-[14px] leading-[1.55]">
                  Rigor, truth-seeking, stewardship, and intellectual honesty. Quiet excellence over performance.
                </span>
              </div>
            </div>
          )}

          {tab === 'principles' && (
            <div role="tabpanel" id="panel-principles" aria-labelledby="tab-principles" className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-3">
                {PRINCIPLES.map((p, i) => (
                  <div
                    key={p.numeral}
                    className="box-border flex min-h-[160px] flex-col gap-3 rounded-lg border p-6"
                    style={{ flex: `1 1 ${i < 2 ? 420 : 280}px`, background: tint(p.accent, 0.16), borderColor: tint(p.accent, 0.4) }}
                  >
                    <span
                      className="self-start rounded-full px-2.5 py-1 font-mono text-caption font-medium text-stone-50"
                      style={{ background: ACCENTS[p.accent].base }}
                    >
                      Principle {p.numeral}
                    </span>
                    <span className="mt-auto text-[17px] font-medium leading-[1.35]">{p.text}</span>
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-3">
                <div className="box-border flex flex-[1_1_320px] flex-col gap-2.5 rounded-lg border border-line bg-stone-50 p-6">
                  <span className={`${eyebrow} text-cobalt-ink`}>Human in the loop</span>
                  <span className="text-[14px] leading-[1.6]">
                    Critical actions above set thresholds need a person’s authorization. Aether recommends, identifies, and
                    explains. It does not execute irreversible, high-impact actions on its own.
                  </span>
                </div>
                <div className="box-border flex flex-[1_1_320px] flex-col gap-2 rounded-lg border border-ember/35 bg-ember/[0.08] p-6">
                  <span className={`${eyebrow} text-ember-ink`}>■ We do not build for</span>
                  <span className="text-[14px] leading-[1.6]">
                    Covert monitoring of people, political manipulation, unauthorized enrichment, unlawful targeting, or
                    leaking intelligence between tenants. Olympus Labs is politically neutral.
                  </span>
                </div>
                <div className="box-border flex flex-[1_1_320px] flex-col gap-2 rounded-lg border border-sage/40 bg-sage/10 p-6">
                  <span className={`${eyebrow} text-sage-ink`}>✓ Data doctrine</span>
                  <span className="text-[14px] leading-[1.6]">
                    Customers own their raw data. Tenant intelligence stays inside the tenant. Deletion removes raw data and
                    stops ingestion.
                  </span>
                </div>
              </div>
            </div>
          )}

          {tab === 'research' && (
            <div role="tabpanel" id="panel-research" aria-labelledby="tab-research" className="flex flex-col gap-3">
              <div className="flex items-baseline gap-2.5 rounded-card border border-dashed border-line-strong bg-stone-50 px-4 py-3 text-body-sm text-graphite-body">
                <span aria-hidden="true" className="font-mono text-ash">
                  ○
                </span>
                Research is a direction, not a production claim. It becomes a capability only with an owner, a contract,
                tests, and deployment evidence.
              </div>
              <div className="flex flex-wrap gap-3">
                {RESEARCH_AREAS.map((r) => {
                  const open = openResearch === r.id;
                  const c = ACCENTS[r.accent];
                  return (
                    <button
                      key={r.id}
                      type="button"
                      aria-expanded={open}
                      onClick={() => setOpenResearch(open ? null : r.id)}
                      className="box-border flex min-h-[170px] flex-[1_1_300px] cursor-pointer flex-col items-start gap-2 rounded-lg border border-t-[3px] bg-stone-50 p-6 text-left text-ink transition-colors duration-120 ease-site hover:[background:var(--hover-bg)]"
                      style={{ ...sideBorders(open ? c.base : '#d8d6d0'), borderTopColor: c.base, ...vars({ '--hover-bg': tint(r.accent, 0.14) }) }}
                    >
                      <span className="flex w-full items-center justify-between">
                        <span
                          aria-hidden="true"
                          className="flex h-[34px] w-[34px] items-center justify-center rounded-[10px] font-mono text-[16px]"
                          style={{ background: tint(r.accent, 0.14), color: c.ink }}
                        >
                          {r.glyph}
                        </span>
                        <span className="font-mono text-[11px] text-slate">{open ? '− open question' : '+ open question'}</span>
                      </span>
                      <span className="mt-auto text-[16px] font-medium">{r.title}</span>
                      <span className="text-body-sm leading-[1.5] text-slate">{r.body}</span>
                      {open && (
                        <span
                          className="box-border w-full rounded-lg px-3 py-2.5 text-body-sm leading-[1.5]"
                          style={{ background: tint(r.accent, 0.14), color: c.ink }}
                        >
                          {r.question}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
              <a
                href={href('olympus', '/contact?type=research')}
                className="inline-flex min-h-[42px] items-center gap-2 self-start whitespace-nowrap rounded-control border border-steel-ink bg-steel-ink px-[18px] text-[14px] font-medium text-stone-50 no-underline hover:bg-[#345a78] hover:text-stone-50"
              >
                <span aria-hidden="true" className="font-mono">
                  ⚗
                </span>
                Discuss a research path
              </a>
            </div>
          )}

          {tab === 'contact' && (
            <div role="tabpanel" id="panel-contact" aria-labelledby="tab-contact" className="flex flex-wrap gap-3">
              {CONTACT_ROUTES.map((r, i) => {
                const c = ACCENTS[r.accent];
                return (
                  <a
                    key={r.type}
                    href={href('olympus', `/contact?type=${r.type}`)}
                    className={`box-border flex min-h-[170px] flex-col items-start gap-2 rounded-lg border p-6 text-ink no-underline transition-colors duration-120 ease-site [background:var(--bg)] [border-color:var(--border)] hover:text-ink hover:[border-color:var(--hover-border)]`}
                    style={{
                      flex: i === 0 ? '2 1 380px' : '1 1 240px',
                      // Resting colors are variables so the hover class can override them.
                      ...vars({ '--bg': tint(r.accent, 0.14), '--border': tint(r.accent, 0.33), '--hover-border': c.base }),
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-[34px] w-[34px] items-center justify-center rounded-[10px] font-mono text-[16px] text-stone-50"
                      style={{ background: c.base }}
                    >
                      {r.glyph}
                    </span>
                    <span className="mt-auto text-[16px] font-medium">{r.title}</span>
                    <span className="text-body-sm leading-[1.5] text-graphite-body">{r.body}</span>
                    <span className="text-body-sm font-medium" style={{ color: c.ink }}>
                      {r.cta} →
                    </span>
                  </a>
                );
              })}
              <div className="box-border flex flex-[1_1_100%] flex-wrap items-center justify-between gap-3 rounded-card bg-ink px-5 py-4 text-bone">
                <span className="text-[14px]">
                  Prefer email? <span className="text-mist">Anything you send is used only to reply.</span>
                </span>
                <a href="mailto:contact@olympuslabsml.com" className="font-mono text-body-sm text-mint no-underline">
                  contact@olympuslabsml.com
                </a>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Closing */}
      <section>
        <div className="mx-auto flex max-w-page flex-col gap-5 px-6 py-[clamp(72px,10vw,128px)]">
          <h2 className="m-0 max-w-[780px] text-balance text-[clamp(30px,4.4vw,52px)] font-medium leading-[1.04] tracking-[-0.03em]">
            Start with the question, not the package.
          </h2>
          <p className="m-0 max-w-[560px] text-[15px] leading-[1.6] text-slate">
            Tell us the relationship you need to understand, the systems that hold the evidence, and the outcome that would
            matter.
          </p>
          <div className="flex flex-wrap gap-3">
            <a
              href={href('olympus', '/contact?type=pilot')}
              className="inline-flex min-h-11 items-center gap-2 whitespace-nowrap rounded-control border border-sage-ink bg-sage-ink px-5 text-[14px] font-medium text-stone-50 no-underline hover:bg-[#41664e] hover:text-stone-50"
            >
              Start a conversation
              <span aria-hidden="true" className="font-mono">
                →
              </span>
            </a>
            <a
              href={href('aether', '/docs')}
              className="inline-flex min-h-11 items-center gap-2 whitespace-nowrap rounded-control border border-ochre/45 bg-ochre/[0.16] px-5 text-[14px] font-medium text-ochre-ink no-underline hover:bg-ochre/[0.26] hover:text-ochre-ink"
            >
              <span aria-hidden="true" className="font-mono">
                ⌘
              </span>
              Read the docs
            </a>
          </div>
        </div>
      </section>
    </PageShell>
  );
}

function ConnectorMark({ name }: { name: string }) {
  const generic = GENERIC_CONNECTOR_GLYPHS[name];
  return (
    <span className="inline-flex h-[22px] w-[22px] shrink-0 items-center justify-center self-center rounded-control border border-stone-200 bg-raised text-steel-ink">
      {generic ? (
        <span aria-hidden="true" className="font-mono text-[10px] font-medium">
          {generic}
        </span>
      ) : (
        <ProviderMark provider={name} size={16} />
      )}
    </span>
  );
}
