/**
 * Public docs content (src/content/docs.json, from the handoff's
 * docs-content.js) plus the helpers the docs page needs: page order, section
 * lookup, heading ids, inline code, and search.
 */
import raw from '@site/content/docs.json';
import type { Accent } from '@site/site/palette';

export type DocsColor = Accent | 'ash';

export interface DocsSection {
  id: string;
  label: string;
  glyph: string;
  color: DocsColor;
  pages: string[];
}

export type DocsBlock =
  | { t: 'h'; x: string }
  | { t: 'p'; x: string }
  | { t: 'list'; items: string[] }
  | { t: 'code'; lang: string; x: string }
  | { t: 'table'; head: string[]; rows: string[][] }
  | { t: 'callout'; tone: 'info' | 'warn' | 'ok' | 'risk'; title: string; x: string }
  | { t: 'cards'; items: Array<{ g: string; c: DocsColor; title: string; x: string; link?: string }> }
  | { t: 'steps'; items: Array<{ title: string; x: string }> }
  | { t: 'flow'; items: Array<[string, string]> }
  | { t: 'kv'; items: Array<[string, string]> }
  | { t: 'details'; items: Array<{ q: string; a: string }> };

export interface DocsPageContent {
  title: string;
  lead: string;
  blocks: DocsBlock[];
}

export const DOCS_SECTIONS = raw.sections as DocsSection[];
export const DOCS_PAGES = raw.pages as unknown as Record<string, DocsPageContent>;
export const DOCS_ORDER = DOCS_SECTIONS.flatMap((s) => s.pages);
export const DEFAULT_DOC = 'overview';

/** Short names used by links in the designs and older pages. */
export const DOC_ALIASES: Record<string, string> = {
  quickstart: 'quickstart-web',
  how: 'how-it-works',
  concepts: 'signals',
};

export function resolveDocId(id: string | undefined): string | null {
  if (!id) return DEFAULT_DOC;
  const target = DOC_ALIASES[id] ?? id;
  return DOCS_PAGES[target] ? target : null;
}

export function sectionOf(pageId: string): DocsSection {
  return DOCS_SECTIONS.find((s) => s.pages.includes(pageId)) ?? DOCS_SECTIONS[0]!;
}

/** Split `code` spans out of a string. */
export function inlineSegments(text: string): Array<{ text: string; code: boolean }> {
  return String(text)
    .split(/(`[^`]+`)/g)
    .filter(Boolean)
    .map((t) => (t.startsWith('`') && t.endsWith('`') && t.length > 1 ? { text: t.slice(1, -1), code: true } : { text: t, code: false }));
}

export function headingId(text: string): string {
  return text
    .toLowerCase()
    .replace(/[`'’]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

/** Heading ids for a page, made unique when two headings share text. */
export function headingIds(page: DocsPageContent): Map<number, string> {
  const ids = new Map<number, string>();
  const seen = new Map<string, number>();
  page.blocks.forEach((b, i) => {
    if (b.t !== 'h') return;
    const base = headingId(b.x) || `section-${i}`;
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    ids.set(i, n ? `${base}-${n + 1}` : base);
  });
  return ids;
}

function blockText(b: DocsBlock): string {
  switch (b.t) {
    case 'h':
    case 'p':
    case 'code':
      return b.x;
    case 'callout':
      return `${b.title} ${b.x}`;
    case 'list':
      return b.items.join(' ');
    case 'table':
      return [b.head.join(' '), ...b.rows.map((r) => r.join(' '))].join(' ');
    case 'cards':
      return b.items.map((c) => `${c.title} ${c.x}`).join(' ');
    case 'steps':
      return b.items.map((s) => `${s.title} ${s.x}`).join(' ');
    case 'flow':
    case 'kv':
      return b.items.map((pair) => pair.join(' ')).join(' ');
    case 'details':
      return b.items.map((d) => `${d.q} ${d.a}`).join(' ');
  }
}

export interface SearchHit {
  id: string;
  title: string;
  section: DocsSection;
  snippet: string;
}

const INDEX = DOCS_ORDER.map((id) => {
  const page = DOCS_PAGES[id]!;
  const text = `${page.title} ${page.lead} ${page.blocks.map(blockText).join(' ')}`.replace(/`/g, '');
  return { id, page, text, lower: text.toLowerCase() };
});

/** Case-insensitive substring search across every public page. */
export function searchDocs(query: string, limit = 8): SearchHit[] {
  const q = query.trim().toLowerCase();
  const matches = q ? INDEX.filter((e) => e.lower.includes(q)) : INDEX.slice(0, 6);
  return matches.slice(0, limit).map((e) => {
    let snippet = e.page.lead;
    if (q) {
      const i = e.lower.indexOf(q);
      snippet = `${i > 40 ? '…' : ''}${e.text.slice(Math.max(0, i - 40), i + 90)}…`;
    }
    return { id: e.id, title: e.page.title, section: sectionOf(e.id), snippet };
  });
}
