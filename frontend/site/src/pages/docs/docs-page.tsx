import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { SkipLink } from '@site/components/page-shell';
import { Glyph } from '@site/components/ui';
import { ProviderMark } from '@site/components/provider-mark';
import { ACCENTS, tint, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';
import {
  DEFAULT_DOC,
  DOCS_ORDER,
  DOCS_PAGES,
  DOCS_SECTIONS,
  headingIds,
  inlineSegments,
  resolveDocId,
  searchDocs,
  sectionOf,
  type DocsBlock,
  type DocsColor,
} from './docs-model';

/** Docs.dc.html: /docs/:page on the Aether site. */

interface Colors {
  base: string;
  soft: string;
  ink: string;
}

const colors = (c: DocsColor): Colors =>
  c === 'ash'
    ? { base: '#9c9b95', soft: 'rgba(156, 155, 149, 0.18)', ink: '#6b6a65' }
    : { base: ACCENTS[c].base, soft: tint(c, ACCENTS[c].soft + 0.02), ink: ACCENTS[c].ink };

const CYCLE: Accent[] = ['cobalt', 'sage', 'ochre', 'solar', 'steel', 'ember'];
const cycle = (i: number) => colors(CYCLE[i % CYCLE.length]!);

const CALLOUT: Record<string, [Accent, string]> = { info: ['cobalt', '◈'], warn: ['ochre', '▲'], ok: ['sage', '✓'], risk: ['ember', '■'] };

const LOGO_NAMES = ['Google Analytics', 'Salesforce', 'HubSpot', 'Shopify', 'Stripe', 'Klaviyo', 'Segment', 'PostHog', 'Zendesk', 'Intercom', 'Linear', 'Slack', 'Jira', 'GA4'];
const LOGO_RE = new RegExp(`(${LOGO_NAMES.join('|')})`, 'g');

const docHref = (id: string) => `/docs/${id}`;

function Inline({ text, codeClass = 'rounded border border-stone-200 bg-stone-100 px-[5px] py-px text-caption' }: { text: string; codeClass?: string }) {
  return (
    <>
      {inlineSegments(text).map((s, i) =>
        s.code ? (
          <code key={i} className={codeClass}>
            {s.text}
          </code>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  );
}

/** Table cells mark provider names with their registry mark. */
function CellText({ text }: { text: string }) {
  return (
    <>
      {inlineSegments(text).flatMap((s, i) =>
        s.code
          ? [
              <code key={i} className="whitespace-nowrap rounded bg-stone-100 px-[5px] py-px text-caption">
                {s.text}
              </code>,
            ]
          : s.text
              .split(LOGO_RE)
              .filter(Boolean)
              .map((part, j) =>
                LOGO_NAMES.includes(part) ? (
                  <span
                    key={`${i}-${j}`}
                    className="my-px mr-0.5 inline-flex items-center gap-[5px] whitespace-nowrap rounded-full border border-stone-200 bg-white py-px pl-[3px] pr-[7px] align-middle"
                  >
                    <ProviderMark provider={part} size={14} className="rounded-full bg-stone-100 text-graphite-body" />
                    <span className="font-medium">{part}</span>
                  </span>
                ) : (
                  <span key={`${i}-${j}`}>{part}</span>
                ),
              ),
      )}
    </>
  );
}

function CodeBlock({ lang, code, color }: { lang: string; code: string; color: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard can be unavailable (permissions, insecure context); the code stays selectable.
    }
  };
  return (
    <div className="max-w-[760px] overflow-hidden rounded-lg border border-graphite-hairline bg-graphite-base">
      <div className="flex items-center justify-between border-b border-graphite-hairline py-1.5 pl-3.5 pr-2">
        <span className="font-mono text-[11px]" style={{ color }}>
          ● {lang}
        </span>
        <button
          type="button"
          onClick={copy}
          className="min-h-[26px] cursor-pointer rounded-control border border-graphite-hairline bg-transparent px-[9px] font-mono text-[11px] text-bone hover:bg-graphite-hover"
        >
          {copied ? '✓ copied' : 'copy'}
        </button>
      </div>
      <pre className="m-0 overflow-x-auto p-3.5 font-mono text-body-sm leading-[1.6] text-bone">{code}</pre>
    </div>
  );
}

function Block({ block, headingId, headingColor, codeColor, accent }: { block: DocsBlock; headingId?: string; headingColor: string; codeColor: string; accent: Colors }) {
  switch (block.t) {
    case 'h':
      return (
        <h2 id={headingId} className="m-0 mt-[18px] flex scroll-mt-[110px] items-center gap-2.5 text-[21px] font-medium tracking-[-0.33px]">
          <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-sm" style={{ background: headingColor }} />
          {block.x}
        </h2>
      );
    case 'p':
      return (
        <p className="m-0 max-w-[720px] text-[14px] leading-[1.75]">
          <Inline text={block.x} />
        </p>
      );
    case 'list':
      return (
        <ul className="m-0 flex max-w-[720px] list-none flex-col gap-1.5 p-0">
          {block.items.map((item) => (
            <li key={item} className="flex gap-2.5 text-[14px] leading-[1.6]">
              <span aria-hidden="true" className="pt-1.5 font-mono text-[8px]" style={{ color: accent.base }}>
                ●
              </span>
              <span>
                <Inline text={item} codeClass="rounded bg-stone-100 px-[5px] py-px text-caption" />
              </span>
            </li>
          ))}
        </ul>
      );
    case 'code':
      return <CodeBlock lang={block.lang} code={block.x} color={codeColor} />;
    case 'table':
      return (
        <div className="max-w-[860px] overflow-x-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-body-sm">
            <thead>
              <tr style={{ background: accent.soft, color: accent.ink }}>
                {block.head.map((h) => (
                  <th key={h} scope="col" className="px-3 py-[9px] text-left text-label uppercase">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r} className="border-t border-stone-200">
                  {row.map((cell, c) => (
                    <td key={c} className="px-3 py-[9px] align-top leading-[1.5]">
                      <CellText text={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case 'callout': {
      const [tone, glyph] = CALLOUT[block.tone] ?? CALLOUT.info!;
      const c = colors(tone);
      return (
        <div role="note" className="flex max-w-[760px] gap-3 rounded-lg border px-3.5 py-3" style={{ background: c.soft, borderColor: `${c.base}55`, color: c.ink }}>
          <Glyph className="pt-px">
            <span style={{ color: c.base }}>{glyph}</span>
          </Glyph>
          <span className="flex flex-col gap-[3px]">
            <span className="text-body-sm font-medium">{block.title}</span>
            <span className="text-body-sm leading-[1.55] text-[#3a3935]">
              <Inline text={block.x} codeClass="text-caption" />
            </span>
          </span>
        </div>
      );
    }
    case 'cards':
      return (
        <div className="flex max-w-[860px] flex-wrap gap-2">
          {block.items.map((card, i) => {
            const c = colors(card.c);
            const big = block.items.length % 2 === 1 && i === 0;
            const body = (
              <>
                <span className="flex w-full items-center justify-between">
                  <span
                    aria-hidden="true"
                    className="box-border flex h-8 min-w-8 items-center justify-center rounded-control px-1.5 font-mono font-medium"
                    style={{ color: c.ink, background: c.soft, fontSize: card.g.length > 1 ? 11 : 16 }}
                  >
                    {card.g}
                  </span>
                  {card.link && (
                    <Glyph>
                      <span style={{ color: c.base }}>→</span>
                    </Glyph>
                  )}
                </span>
                <span className="mt-auto text-[15px] font-medium text-ink">{card.title}</span>
                <span className="text-body-sm leading-[1.5] text-slate">
                  <Inline text={card.x} codeClass="text-caption" />
                </span>
              </>
            );
            const className =
              'box-border flex min-h-[138px] flex-col items-start gap-2 rounded-lg border border-t-[3px] border-line bg-stone-100 p-4 text-left no-underline transition-colors duration-120 ease-site';
            const style = { flex: `1 1 ${big ? 360 : 220}px`, borderTopColor: c.base };
            const target = card.link ? resolveDocId(card.link) : null;
            return target ? (
              <Link key={card.title} to={docHref(target)} className={`${className} hover:border-x-line-strong hover:border-b-line-strong hover:bg-stone-200`} style={style}>
                {body}
              </Link>
            ) : (
              <div key={card.title} className={className} style={style}>
                {body}
              </div>
            );
          })}
        </div>
      );
    case 'steps':
      return (
        <ol className="m-0 flex max-w-[760px] list-none flex-col overflow-hidden rounded-lg border border-line p-0">
          {block.items.map((s, i) => {
            const c = cycle(i);
            return (
              <li key={s.title} className="grid items-start gap-3 border-b border-stone-200 px-4 py-3 last:border-b-0 [grid-template-columns:36px_minmax(0,1fr)]">
                <span className="flex h-7 w-7 items-center justify-center rounded-control font-mono text-caption" style={{ background: c.soft, color: c.ink }}>
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="flex flex-col gap-0.5">
                  <span className="text-[14px] font-medium">{s.title}</span>
                  <span className="text-body-sm leading-[1.55] text-slate">
                    <Inline text={s.x} codeClass="text-caption" />
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      );
    case 'flow':
      return (
        <ol data-theme="dark" className="m-0 flex max-w-[860px] list-none flex-wrap items-stretch gap-1.5 rounded-lg border border-graphite-hairline bg-ink p-3.5">
          {block.items.map(([label, sub], i) => (
            <li key={label} className="flex items-center gap-1.5">
              <div className="flex flex-col gap-[3px] rounded-control border border-t-2 border-graphite-hairline bg-graphite-base px-[11px] py-2" style={{ borderTopColor: cycle(i).base }}>
                <span className="font-mono text-caption text-bone">{label}</span>
                <span className="text-[11px] text-mist">
                  <Inline text={sub} codeClass="text-[11px] text-bone" />
                </span>
              </div>
              {i < block.items.length - 1 && (
                <span aria-hidden="true" className="font-mono text-slate">
                  →
                </span>
              )}
            </li>
          ))}
        </ol>
      );
    case 'kv':
      return (
        <dl className="m-0 flex max-w-[860px] flex-wrap gap-2">
          {block.items.map(([k, v], i) => {
            const c = cycle(i);
            return (
              <div key={k} className="flex flex-[1_1_180px] flex-col gap-1 rounded-lg border px-3.5 py-3" style={{ background: c.soft, borderColor: `${c.base}40` }}>
                <dt className="text-label uppercase text-slate">{k.replace(/`/g, '')}</dt>
                <dd className="m-0 text-[14px] font-medium">
                  <Inline text={v} codeClass="text-body-sm" />
                </dd>
              </div>
            );
          })}
        </dl>
      );
    case 'details':
      return (
        <div className="flex max-w-[760px] flex-col gap-1.5">
          {block.items.map((d, i) => {
            const c = cycle(i);
            return (
              <details key={d.q} className="group rounded-[10px] border border-l-[3px] border-line bg-stone-100" style={{ borderLeftColor: c.base }}>
                <summary className="flex cursor-pointer list-none items-center gap-2.5 px-3.5 py-3 text-[14px] font-medium [&::-webkit-details-marker]:hidden">
                  <span aria-hidden="true" className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-control font-mono" style={{ background: c.soft, color: c.ink }}>
                    <span className="group-open:hidden">+</span>
                    <span className="hidden group-open:inline">−</span>
                  </span>
                  {d.q}
                </summary>
                <div className="pb-3.5 pl-9 pr-3.5 text-body-sm leading-[1.6] text-[#3a3935]">
                  <Inline text={d.a} codeClass="text-caption" />
                </div>
              </details>
            );
          })}
        </div>
      );
  }
}

function SearchDialog({ onClose, onOpen }: { onClose: () => void; onOpen: (id: string) => void }) {
  const { href } = useSite();
  const [query, setQuery] = useState('');
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const results = useMemo(() => searchDocs(query), [query]);
  const active = Math.min(sel, Math.max(0, results.length - 1));
  const activeHit = results[active];

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => previous?.focus();
  }, []);

  const onKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') onClose();
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSel(Math.min(active + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSel(Math.max(active - 1, 0));
    } else if (e.key === 'Enter' && activeHit) onOpen(activeHit.id);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-graphite-base/60 px-4 pb-4 pt-[10vh]" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search docs"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-[620px] overflow-hidden rounded-lg border border-line bg-stone-50 shadow-dialog"
      >
        <div className="flex items-center gap-2.5 border-b border-line px-3.5">
          <Glyph className="text-cobalt">⌕</Glyph>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSel(0);
            }}
            onKeyDown={onKey}
            role="combobox"
            aria-expanded={results.length > 0}
            aria-controls={listId}
            aria-activedescendant={activeHit ? `${listId}-${activeHit.id}` : undefined}
            aria-label="Search"
            placeholder="Search signals, connectors, journeys…"
            className="h-12 flex-1 border-0 bg-transparent text-[15px] text-ink outline-none placeholder:text-ash"
          />
          <kbd className="rounded-[3px] border border-line px-[5px] py-px font-mono text-[11px] text-slate">esc</kbd>
        </div>
        {results.length > 0 ? (
          <ul id={listId} role="listbox" aria-label="Results" className="m-0 max-h-[380px] list-none overflow-y-auto p-1.5">
            {results.map((r, i) => {
              const c = colors(r.section.color);
              return (
                <li
                  key={r.id}
                  id={`${listId}-${r.id}`}
                  role="option"
                  aria-selected={i === active}
                  onClick={() => onOpen(r.id)}
                  onMouseEnter={() => setSel(i)}
                  className="flex cursor-pointer flex-col gap-[3px] rounded-control px-3 py-2.5"
                  style={i === active ? { background: '#eceae5', boxShadow: `inset 2px 0 0 ${c.base}` } : undefined}
                >
                  <span className="flex justify-between gap-2">
                    <span className="flex gap-2 text-[14px] font-medium">
                      <span aria-hidden="true" className="w-3.5 font-mono" style={{ color: c.base }}>
                        {r.section.glyph}
                      </span>
                      {r.title}
                    </span>
                    <span className="text-caption text-slate">{r.section.label}</span>
                  </span>
                  <span className="pl-[22px] text-caption leading-[1.5] text-slate">{r.snippet}</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="flex flex-col gap-2 px-[18px] py-6">
            <span className="text-[14px] font-medium">No public pages match “{query}”</span>
            <span className="text-body-sm leading-[1.55] text-slate">
              Try “consent”, “journey”, “Stripe”, or an event like <code className="text-caption">order_completed</code>.
            </span>
            <a href={href('aether', '/contact?type=developer')} className="inline-flex gap-1.5 text-body-sm font-medium text-sage-ink no-underline">
              Ask an engineer<Glyph>→</Glyph>
            </a>
          </div>
        )}
        <div className="flex gap-3.5 border-t border-line bg-stone-100 px-3.5 py-2 font-mono text-[11px] text-slate">
          <span>↑ ↓ move</span>
          <span>↵ open</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  );
}

export function DocsPage() {
  const { page: param } = useParams();
  const navigate = useNavigate();
  const { href } = useSite();
  const [searching, setSearching] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  const pageId = resolveDocId(param);
  const page = pageId ? DOCS_PAGES[pageId]! : null;
  const section = sectionOf(pageId ?? DEFAULT_DOC);
  const acc = colors(section.color);
  const idx = pageId ? DOCS_ORDER.indexOf(pageId) : -1;
  const prev = idx > 0 ? DOCS_ORDER[idx - 1] : undefined;
  const next = idx >= 0 && idx < DOCS_ORDER.length - 1 ? DOCS_ORDER[idx + 1] : undefined;
  const ids = useMemo(() => (page ? headingIds(page) : new Map<number, string>()), [page]);

  const goto = useCallback(
    (id: string) => {
      setSearching(false);
      setNavOpen(false);
      navigate(docHref(id));
    },
    [navigate],
  );

  // Canonical URLs: aliases and bare /docs redirect to the page id.
  useEffect(() => {
    if (pageId && param !== pageId) navigate(docHref(pageId), { replace: true });
  }, [pageId, param, navigate]);

  useEffect(() => {
    document.title = page ? `${page.title} — Aether Docs` : 'Page not public — Aether Docs';
    window.scrollTo?.(0, 0);
  }, [page]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearching(true);
        return;
      }
      const tag = (e.target as HTMLElement | null)?.tagName ?? '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === ']' && next) goto(next);
      if (e.key === '[' && prev) goto(prev);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goto, next, prev]);

  let headingCount = 0;
  let codeCount = 0;

  return (
    <div className="min-h-screen bg-stone-50 font-sans text-ink">
      <SkipLink />
      <header className="sticky top-0 z-30 border-b border-line bg-stone-50">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-4 px-5">
          <div className="flex shrink-0 items-center gap-2.5">
            <Link to={docHref(DEFAULT_DOC)} className="flex items-center gap-2 text-ink no-underline">
              <img src="/logo-aether-layers.svg" alt="" className="h-5 w-5" />
              <span className="text-[15px] font-medium">Aether</span>
              <span className="text-[15px] text-slate">Docs</span>
            </Link>
            <span className="rounded-full border border-ochre/40 bg-ochre/[0.16] px-[7px] py-0.5 font-mono text-[11px] text-ochre-ink">{__PLATFORM_VERSION__}</span>
          </div>
          <button
            type="button"
            onClick={() => setSearching(true)}
            aria-label="Search docs"
            className="flex min-h-9 min-w-11 cursor-pointer items-center justify-between gap-3 rounded-control border border-line bg-stone-100 px-2.5 text-body-sm text-slate transition-colors duration-120 hover:border-line-strong hover:bg-stone-200 min-[860px]:flex-[0_1_360px]"
          >
            <span className="flex items-center gap-2">
              <Glyph className="text-cobalt">⌕</Glyph>
              <span className="hidden min-[860px]:inline">Search {DOCS_ORDER.length} pages</span>
            </span>
            <kbd className="hidden rounded-[3px] border border-line bg-stone-50 px-[5px] py-px font-mono text-[11px] text-slate min-[860px]:inline">⌘K</kbd>
          </button>
          <nav aria-label="Site" className="hidden items-center gap-1 text-body-sm min-[860px]:flex">
            <a href={href('aether', '/')} className="p-2 text-slate no-underline hover:text-ink">
              Aether
            </a>
            <a href={href('aether', '/status')} className="inline-flex items-center gap-1.5 p-2 text-slate no-underline hover:text-ink">
              <Glyph className="text-sage">●</Glyph>Status
            </a>
            <a
              href={href('aether', '/app/signin')}
              className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-control border border-ink bg-ink px-3.5 text-body-sm font-medium text-stone-50 no-underline hover:border-[#2e2e34] hover:bg-[#2e2e34] hover:text-stone-50"
            >
              Open the app<Glyph className="text-ochre">→</Glyph>
            </a>
          </nav>
        </div>
        <div role="tablist" aria-label="Documentation sections" className="mx-auto flex max-w-[1440px] gap-0.5 overflow-x-auto border-t border-stone-200 px-3">
          {DOCS_SECTIONS.map((s) => {
            const on = s.id === section.id && !!page;
            const c = colors(s.color);
            return (
              <button
                key={s.id}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => goto(s.pages[0]!)}
                className={`inline-flex cursor-pointer items-center gap-[7px] whitespace-nowrap border-0 border-b-2 bg-transparent px-3 py-2.5 text-body-sm font-medium transition-colors duration-120 hover:bg-stone-100 hover:text-ink ${on ? 'text-ink' : 'text-slate'}`}
                style={{ borderBottomColor: on ? c.base : 'transparent' }}
              >
                <Glyph>
                  <span style={{ color: c.base }}>{s.glyph}</span>
                </Glyph>
                {s.label}
                <span className="font-mono text-[11px] text-ash">{s.pages.length}</span>
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={() => setNavOpen((v) => !v)}
          aria-expanded={navOpen}
          aria-controls="docs-nav"
          className="flex min-h-11 w-full cursor-pointer items-center justify-between border-0 border-t border-line bg-stone-100 px-5 text-body-sm text-ink min-[860px]:hidden"
        >
          <span className="flex gap-2">
            <Glyph>≡</Glyph>
            <span className="text-slate">{section.label} /</span>
            <span className="font-medium">{page?.title ?? 'Not public'}</span>
          </span>
          <Glyph>{navOpen ? '✕' : '⌄'}</Glyph>
        </button>
      </header>

      <div className="mx-auto grid max-w-[1440px] grid-cols-1 min-[860px]:grid-cols-[250px_minmax(0,1fr)] min-[1180px]:grid-cols-[250px_minmax(0,1fr)_220px]">
        <nav
          id="docs-nav"
          aria-label="Documentation"
          className={`${navOpen ? 'block' : 'hidden'} border-b border-line bg-stone-50 px-3 pb-1 pt-4 min-[860px]:sticky min-[860px]:top-[100px] min-[860px]:block min-[860px]:h-[calc(100vh-100px)] min-[860px]:self-start min-[860px]:overflow-y-auto min-[860px]:border-b-0 min-[860px]:border-r min-[860px]:px-3 min-[860px]:py-5`}
        >
          {DOCS_SECTIONS.map((s) => {
            const c = colors(s.color);
            return (
              <div key={s.id} className="mb-4 flex flex-col gap-0.5">
                <span className="flex items-center gap-1.5 px-2.5 pb-1.5 text-label uppercase text-slate">
                  <Glyph className="text-caption">
                    <span style={{ color: c.base }}>{s.glyph}</span>
                  </Glyph>
                  {s.label}
                </span>
                {s.pages.map((pid) => {
                  const current = pid === pageId;
                  return (
                    <Link
                      key={pid}
                      to={docHref(pid)}
                      onClick={() => setNavOpen(false)}
                      aria-current={current ? 'page' : undefined}
                      className={`rounded-control px-2.5 py-1.5 text-body-sm no-underline transition-colors duration-120 hover:bg-stone-100 hover:text-ink ${current ? 'font-medium text-ink' : 'text-slate'}`}
                      style={current ? { background: c.soft, boxShadow: `inset 2px 0 0 ${c.base}` } : undefined}
                    >
                      {DOCS_PAGES[pid]?.title ?? pid}
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <main id="main" tabIndex={-1} className={`min-w-0 px-[clamp(20px,4vw,48px)] focus:outline-none pb-[72px] pt-7 ${navOpen ? 'hidden min-[860px]:block' : ''}`}>
          {!page ? (
            <div className="flex max-w-[720px] flex-col gap-3.5 pt-6">
              <Glyph className="text-[22px] text-ash">○</Glyph>
              <h1 className="m-0 text-[28px] font-medium tracking-[-0.5px]">This page is not public</h1>
              <p className="m-0 text-[15px] leading-[1.6] text-slate">
                It may be customer-only or internal. Public docs never include those pages in navigation, search, or the sitemap.
              </p>
              <div>
                <Link
                  to={docHref(DEFAULT_DOC)}
                  className="inline-flex min-h-[42px] items-center gap-2 whitespace-nowrap rounded-control border border-ink bg-ink px-[18px] text-[14px] font-medium text-stone-50 no-underline hover:text-stone-50"
                >
                  Go to the overview<Glyph className="text-ochre">→</Glyph>
                </Link>
              </div>
            </div>
          ) : (
            <article className="flex max-w-[860px] flex-col gap-4">
              <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-caption text-slate">
                <Glyph>
                  <span style={{ color: acc.base }}>{section.glyph}</span>
                </Glyph>
                <span>{section.label}</span>
                <span aria-hidden="true">/</span>
                <span aria-current="page" className="text-ink">
                  {page.title}
                </span>
                <span className="ml-auto font-mono">
                  {String(idx + 1).padStart(2, '0')} / {DOCS_ORDER.length}
                </span>
              </nav>
              <div className="flex flex-col gap-2.5 rounded-lg border border-l-[3px] px-[22px] py-5" style={{ background: acc.soft, borderColor: `${acc.base}40`, borderLeftColor: acc.base }}>
                <h1 className="m-0 text-[clamp(28px,4vw,38px)] font-medium leading-[1.1] tracking-[-0.8px]">{page.title}</h1>
                <p className="m-0 max-w-[700px] text-[16px] leading-[1.6] text-graphite-body">{page.lead}</p>
              </div>
              {page.blocks.map((b, i) => (
                <Block
                  key={`${pageId}-${i}`}
                  block={b}
                  headingId={ids.get(i)}
                  headingColor={b.t === 'h' ? cycle(headingCount++).base : ''}
                  codeColor={b.t === 'code' ? cycle(codeCount++).base : ''}
                  accent={acc}
                />
              ))}
              <nav aria-label="Previous and next" className="mt-7 grid max-w-[760px] grid-cols-2 gap-2">
                {prev ? (
                  <Link to={docHref(prev)} rel="prev" className="flex flex-col items-start gap-1 rounded-lg border border-line p-3.5 text-left no-underline transition-colors duration-120 hover:border-line-strong hover:bg-stone-100">
                    <span className="text-caption text-slate">← Previous</span>
                    <span className="text-[14px] font-medium text-ink">{DOCS_PAGES[prev]!.title}</span>
                  </Link>
                ) : (
                  <span />
                )}
                {next ? (
                  <Link to={docHref(next)} rel="next" className="flex flex-col items-end gap-1 rounded-lg border border-line p-3.5 text-right no-underline transition-colors duration-120 hover:border-line-strong hover:bg-stone-100">
                    <span className="text-caption text-slate">Next →</span>
                    <span className="text-[14px] font-medium text-ink">{DOCS_PAGES[next]!.title}</span>
                  </Link>
                ) : (
                  <span />
                )}
              </nav>
              <span className="font-mono text-[11px] text-ash">tip · press [ and ] to move between pages</span>
            </article>
          )}
        </main>

        {page && (
          <aside aria-label="On this page" className="sticky top-[100px] hidden flex-col gap-1.5 self-start px-5 py-7 text-body-sm min-[1180px]:flex">
            <span className="mb-1 text-label uppercase text-slate">On this page</span>
            {[...ids.entries()].map(([i, id], n) => (
              <a
                key={id}
                href={`#${id}`}
                className={`border-l-2 py-[3px] pl-2.5 no-underline hover:text-ink ${n === 0 ? 'text-ink' : 'border-stone-200 text-slate'}`}
                style={n === 0 ? { borderLeftColor: acc.base } : undefined}
              >
                {(page.blocks[i] as { x: string }).x}
              </a>
            ))}
            <div className="mt-[18px] flex flex-col gap-1 rounded-lg p-3" style={{ background: acc.soft }}>
              <span className="text-label uppercase text-slate">In {section.label}</span>
              <span className="text-caption text-slate">{section.pages.length} pages</span>
            </div>
          </aside>
        )}
      </div>

      {searching && <SearchDialog onClose={() => setSearching(false)} onOpen={goto} />}
    </div>
  );
}
