/**
 * Built from design/designs/Docs.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { asset, css, useDesignState, useLink } from '@site/design/runtime';
import { markSrc } from '@site/components/brand-mark';
import { usePageMeta } from '@site/design/page-meta';

import './docs-page.css';

import { useCallback, useEffect, useRef, type ChangeEvent, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent } from 'react';
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom';
import { useSite } from '@site/site/site-context';
import { pilotOnly } from '@site/site/access';
import { NotFoundPage } from '@site/pages/not-found-page';
import { SkipLink } from '@site/components/skip-link';
import { DOCS_ORDER, DOCS_PAGES, DOCS_SECTIONS, headingIds, resolveDocId, searchDocs } from './docs-model';

type Seg = { t: string; code: boolean; plain: boolean; hasLogo?: boolean; logo?: string };

const AC: [string, string, string] = ['#9fbad6', 'rgba(159,186,214,0.08)', '#c4d6e8'];
const segs = (str: string): Seg[] =>
  String(str || '')
    .split(/(`[^`]+`)/g)
    .filter(Boolean)
    .map((t) => (t.startsWith('`') ? { t: t.slice(1, -1), code: true, plain: false } : { t, code: false, plain: true }));
/** Provider names in reference tables show their reviewed logo (packages/brand). */
const LOGOS: Record<string, string> = { HubSpot: 'hubspot', Salesforce: 'salesforce', Shopify: 'shopify', Stripe: 'stripe', Klaviyo: 'klaviyo', Segment: 'segment', PostHog: 'posthog', GA4: 'googleanalytics', 'Google Analytics': 'googleanalytics', Zendesk: 'zendesk', Intercom: 'intercom', Jira: 'jira', Linear: 'linear', Slack: 'slack', 'Google Ads': 'googleads', Meta: 'meta', Instagram: 'instagram', Microsoft: 'microsoft', Apple: 'apple', Phantom: 'phantom' };
const logoRe = new RegExp('\\b(' + Object.keys(LOGOS).sort((a, b) => b.length - a.length).join('|') + ')\\b', 'g');
const logoSegs = (str: string): Seg[] =>
  segs(str).flatMap((sg) =>
    sg.code ? [sg] : sg.t.split(logoRe).filter(Boolean).map((t) => (LOGOS[t] ? { t, hasLogo: true, logo: '../assets/brand/' + LOGOS[t] + '.svg', code: false, plain: false } : { t, hasLogo: false, code: false, plain: true })),
  );
const DEPTH_MAP: Record<string, string[]> = {
  profiles: ['profiles', 'Aether Customer Intelligence.dc.html', 'imports', 'data-exchange-api', 'how-it-works', 'events'],
  signals: ['signals', 'Aether Platform.dc.html#understand', 'quickstart-web', 'ingestion-api', 'how-it-works', 'events'],
  journeys: ['journeys', 'Aether Customer Intelligence.dc.html', 'connectors', 'data-exchange-api', 'how-it-works', 'events'],
  lenses: ['lenses', 'Aether Lenses.dc.html', 'connectors', 'data-exchange-api', 'how-it-works', 'api-conventions'],
};
const DEPTH_KEYS = [['Understand', 'What it is'], ['Use', 'Investigate one'], ['Connect', 'How it populates'], ['Build', 'Query the API'], ['Architecture', 'How it works'], ['Reference', 'Exact contract']];
const HOME_CARDS = [['understand', 'Understand Aether', 'Learn the concepts behind Aether and how its pieces work together.'], ['use', 'Use Aether', 'Learn how to investigate people, agents, journeys, relationships, communications, value and risk.'], ['connect', 'Connect your systems', 'Add historical data, live applications, providers, SDKs, webhooks and agents.'], ['build', 'Build with Aether', 'Use the APIs, SDKs, webhooks, MCP and developer interfaces.'], ['operate', 'Operate Aether', 'Manage tenants, access, privacy, governance, deployment and observability.'], ['reference', 'Reference', 'Exact APIs, schemas, event types, errors, limits and contracts.']];
const PATH = [['Start here', 'start-here'], ['Understand the model', 'how-it-works'], ['Connect one source', 'connectors'], ['See your first Profile', 'profiles'], ['Explore its Journey', 'journeys'], ['Inspect the Graph', 'relationships'], ['Apply a Lens', 'lenses']];


export function DocsPage() {
  const link = useLink();
  const { page: pageParam, section: sectionParam } = useParams();
  const navigate = useNavigate();
  const { href } = useSite();
  const pilot = pilotOnly();
  const [s, setState] = useDesignState({ w: 1280, searching: false, navOpen: false, query: '', sel: 0, copied: -1 });
  const searchRef = useRef<HTMLInputElement>(null);
  const docPath = useCallback((id: string) => (id === 'home' ? '/docs' : id.startsWith('sec:') ? '/docs/section/' + id.slice(4) : '/docs/' + id), []);
  const goto = useCallback(
    (id: string) => {
      setState({ searching: false, navOpen: false });
      navigate(docPath(id));
    },
    [navigate, docPath, setState],
  );
  const resolved = pageParam === undefined ? null : resolveDocId(pageParam);
  const secObj = sectionParam ? DOCS_SECTIONS.find((x) => x.id === sectionParam) : undefined;
  const isHomeRoute = pageParam === undefined && sectionParam === undefined;
  const pageId = resolved ?? (secObj ? secObj.pages[0]! : 'overview');
  const page = DOCS_PAGES[pageId]!;
  const section = DOCS_SECTIONS.find((x) => x.pages.includes(pageId)) ?? DOCS_SECTIONS[0]!;
  const idx = DOCS_ORDER.indexOf(pageId);
  usePageMeta('docs', isHomeRoute ? undefined : { title: (secObj ? secObj.label : page.title) + ' — Aether docs', description: secObj ? undefined : page.lead });

  useEffect(() => {
    const onR = () => setState({ w: window.innerWidth });
    onR();
    window.addEventListener('resize', onR);
    return () => window.removeEventListener('resize', onR);
  }, [setState]);
  useEffect(() => {
    const onK = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setState({ searching: true, sel: 0 });
        return;
      }
      const tag = (e.target as HTMLElement | null)?.tagName ?? '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (isHomeRoute || secObj) return;
      const n = e.key === ']' ? DOCS_ORDER[idx + 1] : e.key === '[' ? DOCS_ORDER[idx - 1] : undefined;
      if (n) goto(n);
    };
    window.addEventListener('keydown', onK);
    return () => window.removeEventListener('keydown', onK);
  }, [goto, idx, isHomeRoute, secObj, setState]);
  useEffect(() => {
    if (s.searching) setTimeout(() => searchRef.current?.focus(), 0);
  }, [s.searching]);
  const { hash } = useLocation();
  // A link to a heading lands on it; any other page change starts at the top.
  useEffect(() => {
    const target = hash ? document.getElementById(decodeURIComponent(hash.slice(1))) : null;
    if (target) target.scrollIntoView();
    else window.scrollTo?.(0, 0);
  }, [pageId, hash]);
  const dialogRef = useRef<HTMLDivElement>(null);
  const trapKeys = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      setState({ searching: false });
      return;
    }
    if (e.key !== 'Tab' || !dialogRef.current) return;
    const items = [...dialogRef.current.querySelectorAll<HTMLElement>('input, a[href], button')];
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const wide = s.w >= 860;
  const xwide = s.w >= 1180;
  const narrow = !wide;
  const isHomeView = isHomeRoute;
  const isSectionView = !!secObj;
  const acc = AC;
  const pageCount = DOCS_ORDER.length;
  const toggleNav = () => setState({ navOpen: !s.navOpen });
  const navOpenStr = s.navOpen ? 'true' : 'false';
  const navGlyph = s.navOpen ? '✕' : '⌄';
  const searchBtnStyle = 'font-family: inherit; flex: ' + (wide ? '0 1 360px' : '0 0 auto') + '; display: flex; justify-content: space-between; align-items: center; gap: 12px; min-height: 36px; padding: 0 10px; border: 1px solid #2a2a2f; border-radius: 6px; background: #17171a; color: #a09f99; font-size: 13px; cursor: pointer; min-width: 44px; transition: background-color 120ms;';
  const nav = DOCS_SECTIONS.map((x) => ({
    label: x.label, glyph: x.glyph, go: () => goto(x.pages[0]!), glyphStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + acc[0] + ';',
    items: x.pages.map((pid) => ({
      label: DOCS_PAGES[pid]?.title ?? pid,
      href: href('aether', docPath(pid)),
      current: pid === pageId && !isHomeView && !isSectionView ? 'page' : 'false',
      go: (e: MouseEvent) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        goto(pid);
      },
      style: 'font-size: 13px; text-decoration: none; padding: 6px 10px; border-radius: 6px; transition: background-color 120ms; ' + (pid === pageId && !isHomeView && !isSectionView ? 'background: ' + acc[1] + '; color: #e8e6e1; font-weight: 500; box-shadow: inset 2px 0 0 ' + acc[0] + ';' : 'color: #a09f99;'),
    })),
  }));
  const ids = headingIds(page);
  const blocks = page.blocks.map((b, bi) => {
    const o: Record<string, unknown> = { isH: b.t === 'h', isP: b.t === 'p', isList: b.t === 'list', isCode: b.t === 'code', isTable: b.t === 'table', isCallout: b.t === 'callout', isCards: b.t === 'cards', isSteps: b.t === 'steps', isFlow: b.t === 'flow', isKv: b.t === 'kv', isDetails: b.t === 'details' };
    switch (b.t) {
      case 'details':
        o.details = b.items.map((d) => ({ q: d.q, segs: segs(d.a), gStyle: 'font-family: var(--font-mono); width: 20px; height: 20px; border-radius: 6px; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; background: ' + acc[1] + '; color: ' + acc[2] + ';', style: 'border-radius: 10px; background: #17171a; border: 1px solid #2a2a2f; border-left: 1px solid #2a2a2f;' }));
        break;
      case 'h':
        Object.assign(o, { x: b.x, id: ids.get(bi), hStyle: 'font-size: 21px; font-weight: 500; letter-spacing: -0.33px; margin: 18px 0 0; color: #e8e6e1; display: flex; align-items: center; gap: 10px; scroll-margin-top: 110px;', hDot: 'width: 8px; height: 8px; border-radius: 2px; background: ' + acc[0] + '; flex-shrink: 0;' });
        break;
      case 'p':
        o.segs = segs(b.x);
        break;
      case 'list':
        Object.assign(o, { items: b.items.map(segs), bullet: 'font-family: var(--font-mono); font-size: 8px; color: ' + acc[0] + '; padding-top: 6px;' });
        break;
      case 'code': {
        const k = bi;
        Object.assign(o, {
          x: b.x, lang: b.lang, langStyle: 'font-family: var(--font-mono); font-size: 11px; color: ' + acc[0] + ';', copyLabel: s.copied === k ? '✓ copied' : 'copy',
          copy: () => {
            void navigator.clipboard?.writeText(b.x).catch(() => undefined);
            setState({ copied: k });
            setTimeout(() => setState({ copied: -1 }), 1400);
          },
        });
        break;
      }
      case 'table':
        Object.assign(o, { head: b.head, rows: b.rows.map((r) => r.map(logoSegs)), headStyle: 'background: ' + acc[1] + '; color: ' + acc[2] + ';' });
        break;
      case 'callout': {
        const g = { info: '◈', warn: '▲', ok: '✓', risk: '■' }[b.tone] ?? '◈';
        Object.assign(o, { title: b.title, glyph: g, segs: segs(b.x), calloutStyle: 'display: flex; gap: 12px; padding: 12px 14px; border-radius: 8px; max-width: 760px; background: ' + acc[1] + '; border: 1px solid ' + acc[0] + '55; color: ' + acc[2] + ';', calloutGlyphStyle: 'font-family: var(--font-mono); color: ' + acc[0] + '; padding-top: 1px;' });
        break;
      }
      case 'cards':
        o.cards = b.items.map((c, i) => {
          const big = b.items.length % 2 === 1 && i === 0;
          return {
            g: c.g, title: c.title, segs: segs(c.x), linked: !!c.link, logo: c.logo, go: () => c.link && goto(c.link),
            chip: c.logo
              ? 'width: 32px; height: 32px; box-sizing: border-box; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: #ffffff; border: 1px solid #2a2a2f;'
              : 'min-width: 32px; height: 32px; padding: 0 6px; box-sizing: border-box; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: ' + (c.g.length > 1 ? 11 : 16) + 'px; font-weight: 500; color: ' + acc[2] + '; background: ' + acc[1] + ';',
            arrowStyle: 'font-family: var(--font-mono); color: ' + acc[0] + ';',
            style: 'font-family: inherit; text-align: left; flex: 1 1 ' + (big ? 360 : 220) + 'px; min-height: 138px; box-sizing: border-box; border-radius: 8px; padding: 16px; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; background: #17171a; border: 1px solid #2a2a2f; border-top: 1px solid #2a2a2f; cursor: ' + (c.link ? 'pointer' : 'default') + '; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1), border-color 120ms cubic-bezier(0.22,1,0.36,1);',
          };
        });
        break;
      case 'steps':
        o.steps = b.items.map((x, i) => ({ n: String(i + 1).padStart(2, '0'), title: x.title, segs: segs(x.x), numStyle: 'font-family: var(--font-mono); font-size: 12px; width: 28px; height: 28px; border-radius: 6px; display: flex; align-items: center; justify-content: center; background: ' + acc[1] + '; color: ' + acc[2] + ';' }));
        break;
      case 'flow':
        o.flow = b.items.map(([label, sub], i) => ({ label, segs: segs(sub), arrow: i < b.items.length - 1, style: 'display: flex; flex-direction: column; gap: 3px; padding: 8px 11px; border-radius: 6px; background: #0b0b0d; border: 1px solid #2a2a2f; border-top: 1px solid #2a2a2f;' }));
        break;
      case 'kv':
        o.kv = b.items.map(([k, v]) => ({ ks: segs(k), vs: segs(v), style: 'flex: 1 1 180px; display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border-radius: 8px; background: ' + acc[1] + '; border: 1px solid ' + acc[0] + '40;' }));
        break;
    }
    return o as any;
  });
  const outline = page.blocks
    .map((b, bi) => (b.t === 'h' ? { href: '#' + ids.get(bi), label: b.x } : null))
    .filter((x): x is { href: string; label: string } => x !== null)
    .map((o, i) => ({ ...o, style: 'text-decoration: none; padding: 3px 0 3px 10px; border-left: 2px solid ' + (i === 0 ? acc[0] + '; color: #e8e6e1;' : '#2a2a2f; color: #a09f99;') }));
  const hits = searchDocs(s.query);
  const sel = Math.min(s.sel, Math.max(0, hits.length - 1));
  const results = hits.map((r, i) => ({
    title: r.title, section: r.section.label, glyph: r.section.glyph, snippet: r.snippet,
    sel: i === sel ? 'true' : 'false', go: () => goto(r.id), hover: () => setState({ sel: i }),
    glyphStyle: 'font-family: var(--font-mono); color: ' + acc[0] + '; width: 14px;',
    style: 'padding: 10px 12px; border-radius: 6px; cursor: pointer; display: flex; flex-direction: column; gap: 3px; ' + (i === sel ? 'background: #17171a; box-shadow: inset 2px 0 0 ' + acc[0] + ';' : ''),
  }));
  const searchOpen = s.searching;
  const hasResults = results.length > 0;
  const noResults = !hasResults;
  const query = s.query;
  const onQuery = (e: ChangeEvent<HTMLInputElement>) => setState({ query: e.target.value, sel: 0 });
  const onKey = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') setState({ searching: false });
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setState({ sel: Math.min(sel + 1, hits.length - 1) });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setState({ sel: Math.max(sel - 1, 0) });
    } else if (e.key === 'Enter' && hits[sel]) goto(hits[sel]!.id);
  };
  const openSearch = () => setState({ searching: true, sel: 0 });
  const closeSearch = () => setState({ searching: false });
  const stop = (e: MouseEvent) => e.stopPropagation();
  const goHome = () => goto('overview');
  const goDocsHome = (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    e.preventDefault();
    goto('home');
  };
  const nb = (dir: number) => {
    const pid = DOCS_ORDER[idx + dir];
    const base = 'font-family: inherit; border: 1px solid #2a2a2f; border-radius: 8px; padding: 14px; display: flex; flex-direction: column; gap: 4px; background: transparent; cursor: pointer; text-align: ' + (dir > 0 ? 'right; align-items: flex-end;' : 'left; align-items: flex-start;') + ' transition: background-color 120ms;';
    return pid ? { label: DOCS_PAGES[pid]!.title, none: false, go: () => goto(pid), style: base } : { label: '—', none: true, go: () => undefined, style: base + ' opacity: 0.5; cursor: default;' };
  };
  const prev = nb(-1);
  const next = nb(1);
  const sectionCount = section.pages.length;
  const position = String(idx + 1).padStart(2, '0') + ' / ' + DOCS_ORDER.length;
  const crumbGlyphStyle = 'font-family: var(--font-mono); color: ' + acc[0] + ';';
  const heroStyle = 'display: flex; flex-direction: column; gap: 12px; padding: 8px 0 24px; border-bottom: 1px solid #2a2a2f;';
  const relatedStyle = 'margin-top: 18px; padding: 12px; border-radius: 8px; display: flex; flex-direction: column; gap: 4px; background: ' + acc[1] + ';';
  const showSidebar = wide || s.navOpen;
  const showOutline = xwide;
  const gridStyle = 'max-width: 1440px; margin: 0 auto; display: grid; grid-template-columns: ' + (xwide ? '250px minmax(0,1fr) 220px' : wide ? '250px minmax(0,1fr)' : 'minmax(0,1fr)') + ';';
  const sidebarStyle = wide ? 'position: sticky; top: 100px; align-self: start; height: calc(100vh - 100px); overflow-y: auto; padding: 20px 12px; border-right: 1px solid #2a2a2f; box-sizing: border-box;' : 'padding: 16px 12px 4px; border-bottom: 1px solid #2a2a2f; background: #111114;';
  const mobileNav = !wide && s.navOpen;
  // Unknown ids (customer-only or internal pages) are never public.
  const isPrivate = pageParam !== undefined && !resolved;
  const isPage = !isHomeView && !isSectionView && !isPrivate && !mobileNav;
  const isHome = isHomeView && !mobileNav;
  const isSection = isSectionView && !mobileNav;
  const secTitle = secObj ? secObj.label : '';
  const secGlyph = secObj ? secObj.glyph : '';
  const secPages = secObj ? secObj.pages.map((pid) => ({ t: DOCS_PAGES[pid]!.title, b: DOCS_PAGES[pid]!.lead, go: () => goto(pid) })) : [];
  const doors = ([['Learn', "I'm trying to understand Aether", 'Concepts · guides · examples', 'understand', true], ['Build', "I'm trying to build with Aether", 'Quickstarts · SDKs · API · reference', 'build', false]] as const).map(([k, t, sub, sid, light]) => {
    const sx = DOCS_SECTIONS.find((x) => x.id === sid) ?? DOCS_SECTIONS[0]!;
    return { k, t, sub, go: () => goto(sx.pages[0]!), kStyle: 'font-family: var(--font-mono); font-size: 12px; color: ' + (light ? '#9fbad6' : '#dcb683') + ';', subStyle: 'font-size: 13px; color: #a09f99;', style: 'font-family: inherit; text-align: left; flex: 1 1 320px; display: flex; flex-direction: column; gap: 10px; min-height: 150px; padding: 24px; border-radius: 12px; cursor: pointer; background: #17171a; color: #e8e6e1; border: 1px solid #2a2a2f;' };
  });
  const homeCards = HOME_CARDS.map(([sid, t, b]) => {
    const sx = DOCS_SECTIONS.find((x) => x.id === sid) ?? DOCS_SECTIONS[0]!;
    return { t, b, g: sx.glyph, n: sx.pages.length + ' pages', go: () => goto('sec:' + sid), chip: 'width: 32px; height: 32px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 15px; background: ' + acc[1] + '; color: ' + acc[2] + ';', style: 'font-family: inherit; text-align: left; display: flex; flex-direction: column; align-items: flex-start; gap: 8px; min-height: 160px; padding: 18px; border-radius: 10px; cursor: pointer; background: #17171a; border: 1px solid #2a2a2f; border-top: 1px solid #2a2a2f; color: #e8e6e1; transition: background-color 120ms cubic-bezier(0.22,1,0.36,1);' };
  });
  const path = PATH.map(([l, pid], i) => ({ l, n: '0' + (i + 1), arrow: i < PATH.length - 1, go: () => goto(DOCS_PAGES[pid!] ? pid! : 'overview') }));
  const dm = DEPTH_MAP[pageId];
  const hasDepth = !!dm && !isHomeView;
  const depth = (dm ?? []).map((t, i) => {
    const ext = t.includes('.dc.html');
    return {
      k: DEPTH_KEYS[i]![0], l: DEPTH_KEYS[i]![1], href: ext ? t : href('aether', docPath(t)),
      go: ext ? () => undefined : (e: MouseEvent) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey) return;
        e.preventDefault();
        goto(t);
      },
      kStyle: 'font-family: var(--font-mono); font-size: 11px; color: #a09f99;',
    };
  });
  if (sectionParam !== undefined && !secObj) return <NotFoundPage />;
  // Aliases (quickstart → quickstart-web) settle on the canonical URL.
  if (resolved && pageParam !== resolved) return <Navigate to={docPath(resolved) + hash} replace />;
  return (
    <div className="dc pg-docs">
    <div data-page="docs" style={css("min-height: 100vh; background: #111114; color: #e8e6e1; font-family: var(--font-sans);")}>
      <header style={css("position: sticky; top: 0; z-index: 30; background: #111114; border-bottom: 1px solid #2a2a2f;")}>
        <SkipLink />
        <div style={css("padding: 0 20px; height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 16px; max-width: 1440px; margin: 0 auto;")}>
          <div style={css("display: flex; align-items: center; gap: 10px; flex-shrink: 0;")}>
            <a href={link("Docs.dc.html")} onClick={goDocsHome} style={css("display: flex; align-items: center; gap: 8px; text-decoration: none; color: #e8e6e1;")}>
              <img src={markSrc('aether')} alt="" style={css("width: 20px; height: 20px;")} />
              <span style={css("font-size: 15px; font-weight: 500;")}>
                {"Aether"}
              </span>
              <span style={css("font-size: 15px; color: #a09f99;")}>
                {"Docs"}
              </span>
            </a>
            <span style={css("font-family: var(--font-mono); font-size: 11px; padding: 2px 7px; border-radius: 999px; background: rgba(201,151,90,0.14); border: 1px solid rgba(201,151,90,0.4); color: #dcb683;")}>
              {__PLATFORM_VERSION__}
            </span>
          </div>
          <button type="button" onClick={openSearch} aria-label="Search docs" style={css(searchBtnStyle)} className="hv-b871c9ca">
            <span style={css("display: flex; align-items: center; gap: 8px;")}>
              <span style={css("font-family: var(--font-mono); color: #9fbad6;")}>
                {"⌕"}
              </span>
              {(wide) ? (
                <>
                  <span>
                    {"Search "}{pageCount}{" pages"}
                  </span>
                </>
              ) : null}
            </span>
            {(wide) ? (
              <>
                <kbd style={css("font-family: var(--font-mono); font-size: 11px; padding: 1px 5px; border: 1px solid #2a2a2f; border-radius: 3px; color: #a09f99; background: #111114;")}>
                  {"⌘K"}
                </kbd>
              </>
            ) : null}
          </button>
          {(wide) ? (
            <>
              <nav aria-label="Site" style={css("display: flex; align-items: center; gap: 4px; font-size: 13px;")}>
                <a href={link("Aether Home.dc.html")} style={css("color: #a09f99; text-decoration: none; padding: 8px;")} className="hv-761d44c6">
                  {"Aether"}
                </a>
                <a href={link("Glossary.dc.html")} style={css("color: #a09f99; text-decoration: none; padding: 8px;")} className="hv-761d44c6">
                  {"Glossary"}
                </a>
                <a href={link("Symbol Key.dc.html")} style={css("color: #a09f99; text-decoration: none; padding: 8px;")} className="hv-761d44c6">
                  {"Symbols"}
                </a>
                {pilot ? null : (
                <a href={link("Status.dc.html")} style={css("color: #a09f99; text-decoration: none; padding: 8px; display: inline-flex; gap: 6px; align-items: center;")} className="hv-761d44c6">
                  <span style={css("font-family: var(--font-mono); color: #9cc4a9;")}>
                    {"●"}
                  </span>
                  {"Status"}
                </a>
                )}
                <a href={link("Aether Portal.dc.html?mode=signin")} style={css("display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; flex-shrink: 0; min-height: 36px; padding: 0 14px; box-sizing: border-box; border-radius: 6px; font-size: 13px; font-weight: 500; text-decoration: none; background: #e8e6e1; color: #111114; border: 1px solid #e8e6e1;")} className="hv-ed2a1fe4">
                  {pilot ? "Request a pilot" : "Open the app"}
                  <span style={css("font-family: var(--font-mono); color: #c9975a;")}>
                    {"→"}
                  </span>
                </a>
              </nav>
            </>
          ) : null}
        </div>
        {(narrow) ? (
          <>
            <button type="button" onClick={toggleNav} aria-expanded={navOpenStr} style={css("font-family: inherit; width: 100%; display: flex; justify-content: space-between; align-items: center; min-height: 44px; padding: 0 20px; border: 0; border-top: 1px solid #2a2a2f; background: #17171a; font-size: 13px; color: #e8e6e1; cursor: pointer;")}>
              <span style={css("display: flex; gap: 8px;")}>
                <span style={css("font-family: var(--font-mono);")}>
                  {"≡"}
                </span>
                <span style={css("color: #a09f99;")}>
                  {section.label}{" /"}
                </span>
                <span style={css("font-weight: 500;")}>
                  {page.title}
                </span>
              </span>
              <span style={css("font-family: var(--font-mono);")}>
                {navGlyph}
              </span>
            </button>
          </>
        ) : null}
      </header>
      <div style={css(gridStyle)}>
        {(showSidebar) ? (
          <>
            <nav aria-label="Documentation" style={css(sidebarStyle)}>
              {(nav).map((sec: any, secIndex: number) => (
                <Fragment key={secIndex}>
                  <div style={css("display: flex; flex-direction: column; gap: 2px; margin-bottom: 16px;")}>
                    <button type="button" onClick={sec.go} style={css("font-family: inherit; display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99; padding: 0 10px 6px; background: transparent; border: 0; cursor: pointer; text-align: left;")}>
                      <span style={css(sec.glyphStyle)}>
                        {sec.glyph}
                      </span>
                      {sec.label}
                    </button>
                    {(sec.items).map((it: any, itIndex: number) => (
                      <Fragment key={itIndex}>
                        <a href={link(it.href)} onClick={it.go} aria-current={it.current} style={css(it.style)} className="hv-3837c3f1">
                          {it.label}
                        </a>
                      </Fragment>
                    ))}
                  </div>
                </Fragment>
              ))}
            </nav>
          </>
        ) : null}
        <main id="main" tabIndex={-1} style={css("min-width: 0; padding: 28px clamp(20px, 4vw, 48px) 72px;")}>
          {(isPrivate) ? (
            <>
              <div style={css("max-width: 720px; display: flex; flex-direction: column; gap: 14px; padding-top: 24px;")}>
                <span style={css("font-family: var(--font-mono); font-size: 22px; color: #7d7c77;")}>
                  {"○"}
                </span>
                <h1 style={css("font-size: 28px; font-weight: 500; letter-spacing: -0.5px; margin: 0; color: #e8e6e1;")}>
                  {"This page is not public"}
                </h1>
                <p style={css("font-size: 15px; line-height: 1.6; color: #a09f99; margin: 0;")}>
                  {"It may be customer-only or internal. Public docs never include those pages in navigation, search, or the sitemap."}
                </p>
                <div style={css("display: flex; flex-wrap: wrap; gap: 12px;")}>
                  <button type="button" onClick={goHome} style={css("font-family: inherit; display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; min-height: 42px; padding: 0 18px; border-radius: 6px; font-size: 14px; font-weight: 500; background: #e8e6e1; color: #111114; border: 1px solid #e8e6e1; cursor: pointer;")}>
                    {"Go to the overview"}
                    <span style={css("font-family: var(--font-mono); color: #c9975a;")}>
                      {"→"}
                    </span>
                  </button>
                </div>
              </div>
            </>
          ) : null}
          {(isHome) ? (
            <>
              <div style={css("max-width: 1000px; display: flex; flex-direction: column; gap: 36px; padding-top: 8px;")}>
                <div style={css("display: flex; flex-direction: column; gap: 14px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"Aether documentation"}
                  </span>
                  <h1 style={css("font-size: clamp(36px, 5vw, 60px); font-weight: 500; letter-spacing: -0.04em; line-height: 1; margin: 0; color: #e8e6e1;")}>
                    {"What are you trying to do?"}
                  </h1>
                  <p style={css("font-size: 16px; line-height: 1.6; color: #c9c7c0; margin: 0; max-width: 620px;")}>
                    {"Aether brings activity from all your tools together, so you can see the people, AI agents, connections, and results behind it."}
                  </p>
                </div>
                <div style={css("display: flex; flex-wrap: wrap; gap: 10px;")}>
                  {(doors).map((d: any, dIndex: number) => (
                    <Fragment key={dIndex}>
                      <button type="button" onClick={d.go} style={css(d.style)}>
                        <span style={css(d.kStyle)}>
                          {d.k}
                        </span>
                        <span style={css("font-size: 22px; font-weight: 500; letter-spacing: -0.33px;")}>
                          {d.t}
                        </span>
                        <span style={css(d.subStyle)}>
                          {d.sub}
                        </span>
                      </button>
                    </Fragment>
                  ))}
                </div>
                <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr)); gap: 8px;")}>
                  {(homeCards).map((c: any, cIndex: number) => (
                    <Fragment key={cIndex}>
                      <button type="button" onClick={c.go} style={css(c.style)} className="hv-8992effa">
                        <span style={css("display: flex; justify-content: space-between; width: 100%;")}>
                          <span style={css(c.chip)}>
                            {c.g}
                          </span>
                          <span style={css("font-family: var(--font-mono); font-size: 11px; color: #7d7c77;")}>
                            {c.n}
                          </span>
                        </span>
                        <span style={css("font-size: 17px; font-weight: 500; margin-top: auto;")}>
                          {c.t}
                        </span>
                        <span style={css("font-size: 13px; line-height: 1.5; color: #a09f99;")}>
                          {c.b}
                        </span>
                      </button>
                    </Fragment>
                  ))}
                </div>
                <div style={css("display: flex; flex-direction: column; gap: 12px; padding: 22px; border-radius: 12px; background: #17171a; color: #e8e6e1;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {"New to Aether? The default learning path"}
                  </span>
                  <div style={css("display: flex; flex-wrap: wrap; gap: 6px; align-items: center;")}>
                    {(path).map((p: any, pIndex: number) => (
                      <Fragment key={pIndex}>
                        <button type="button" onClick={p.go} style={css("font-family: inherit; display: inline-flex; gap: 8px; align-items: center; min-height: 34px; padding: 0 12px; border-radius: 999px; border: 1px solid #3a3a40; background: #0b0b0d; color: #e8e6e1; font-size: 13px; cursor: pointer;")}>
                          <span style={css("font-family: var(--font-mono); font-size: 11px; color: #dcb683;")}>
                            {p.n}
                          </span>
                          {p.l}
                        </button>
                        {(p.arrow) ? (
                          <>
                            <span style={css("font-family: var(--font-mono); color: #a09f99;")}>
                              {"→"}
                            </span>
                          </>
                        ) : null}
                      </Fragment>
                    ))}
                  </div>
                </div>
                <a href={link("Glossary.dc.html")} style={css("display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 18px 20px; border-radius: 12px; background: #17171a; border: 1px solid #2a2a2f; text-decoration: none; color: #e8e6e1;")} className="hv-a9ee1797">
                  <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                    <span style={css("font-size: 15px; font-weight: 500;")}>
                      {"Glossary"}
                    </span>
                    <span style={css("font-size: 13px; color: #a09f99;")}>
                      {"Every term in three forms: plain language, product meaning, technical meaning."}
                    </span>
                  </span>
                  <span style={css("font-family: var(--font-mono); color: #7d7c77;")}>
                    {"→"}
                  </span>
                </a>
              </div>
            </>
          ) : null}
          {(isSection) ? (
            <>
              <div style={css("max-width: 760px; display: flex; flex-direction: column; gap: 32px; padding-top: 8px;")}>
                <div style={css("display: flex; flex-direction: column; gap: 12px;")}>
                  <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                    {secGlyph}{" Docs"}
                  </span>
                  <h1 style={css("font-size: clamp(34px, 4.6vw, 52px); font-weight: 500; letter-spacing: -0.04em; line-height: 1; margin: 0; color: #e8e6e1;")}>
                    {secTitle}
                  </h1>
                </div>
                <div style={css("border-top: 1px solid #2a2a2f;")}>
                  {(secPages).map((p: any, pIndex: number) => (
                    <Fragment key={pIndex}>
                      <button type="button" onClick={p.go} style={css("font-family: inherit; text-align: left; width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: baseline; padding: 18px 0; border: 0; border-bottom: 1px solid #2a2a2f; background: transparent; color: #e8e6e1; cursor: pointer;")} className="hv-6f6d4759">
                        <span style={css("display: flex; flex-direction: column; gap: 4px;")}>
                          <span style={css("font-size: 17px; font-weight: 500;")}>
                            {p.t}
                          </span>
                          <span style={css("font-size: 14px; line-height: 1.5; color: #a09f99;")}>
                            {p.b}
                          </span>
                        </span>
                        <span style={css("font-family: var(--font-mono); color: #7d7c77;")}>
                          {"→"}
                        </span>
                      </button>
                    </Fragment>
                  ))}
                </div>
              </div>
            </>
          ) : null}
          {(isPage) ? (
            <>
              <article style={css("max-width: 860px; display: flex; flex-direction: column; gap: 16px;")}>
                <nav aria-label="Breadcrumb" style={css("font-size: 12px; color: #a09f99; display: flex; gap: 6px; align-items: center;")}>
                  <span style={css(crumbGlyphStyle)}>
                    {section.glyph}
                  </span>
                  <span>
                    {section.label}
                  </span>
                  <span>
                    {"/"}
                  </span>
                  <span style={css("color: #e8e6e1;")}>
                    {page.title}
                  </span>
                  <span style={css("margin-left: auto; font-family: var(--font-mono);")}>
                    {position}
                  </span>
                </nav>
                <div style={css(heroStyle)}>
                  <h1 style={css("font-size: clamp(28px, 4vw, 38px); font-weight: 500; letter-spacing: -0.8px; line-height: 1.1; margin: 0; color: #e8e6e1;")}>
                    {page.title}
                  </h1>
                  <p style={css("font-size: 16px; line-height: 1.6; color: #c9c7c0; margin: 0; max-width: 700px;")}>
                    {page.lead}
                  </p>
                </div>
                {(blocks).map((b: any, bIndex: number) => (
                  <Fragment key={bIndex}>
                    {(b.isH) ? (
                      <>
                        <h2 id={b.id} style={css(b.hStyle)}>
                          <span style={css(b.hDot)} />
                          {b.x}
                        </h2>
                      </>
                    ) : null}
                    {(b.isP) ? (
                      <>
                        <p style={css("font-size: 14px; line-height: 1.75; margin: 0; max-width: 720px; color: #e8e6e1;")}>
                          {(b.segs).map((s: any, sIndex: number) => (
                            <Fragment key={sIndex}>
                              {(s.code) ? (
                                <>
                                  <code style={css("font-size: 12px; padding: 1px 5px; border-radius: 4px; background: #17171a; border: 1px solid #2a2a2f;")}>
                                    {s.t}
                                  </code>
                                </>
                              ) : null}
                              {(s.plain) ? (
                                <>
                                  {s.t}
                                </>
                              ) : null}
                            </Fragment>
                          ))}
                        </p>
                      </>
                    ) : null}
                    {(b.isList) ? (
                      <>
                        <ul style={css("margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; max-width: 720px;")}>
                          {(b.items).map((li: any, liIndex: number) => (
                            <Fragment key={liIndex}>
                              <li style={css("display: flex; gap: 10px; font-size: 14px; line-height: 1.6;")}>
                                <span style={css(b.bullet)}>
                                  {"●"}
                                </span>
                                <span>
                                  {(li).map((s: any, sIndex: number) => (
                                    <Fragment key={sIndex}>
                                      {(s.code) ? (
                                        <>
                                          <code style={css("font-size: 12px; padding: 1px 5px; border-radius: 4px; background: #17171a;")}>
                                            {s.t}
                                          </code>
                                        </>
                                      ) : null}
                                      {(s.plain) ? (
                                        <>
                                          {s.t}
                                        </>
                                      ) : null}
                                    </Fragment>
                                  ))}
                                </span>
                              </li>
                            </Fragment>
                          ))}
                        </ul>
                      </>
                    ) : null}
                    {(b.isCode) ? (
                      <>
                        <div style={css("border: 1px solid #2a2a2f; border-radius: 8px; background: #0b0b0d; overflow: hidden; max-width: 760px;")}>
                          <div style={css("display: flex; justify-content: space-between; align-items: center; padding: 6px 8px 6px 14px; border-bottom: 1px solid #2a2a2f;")}>
                            <span style={css(b.langStyle)}>
                              {"● "}{b.lang}
                            </span>
                            <button type="button" onClick={b.copy} style={css("font-family: var(--font-mono); font-size: 11px; color: #e8e6e1; background: transparent; border: 1px solid #2a2a2f; border-radius: 6px; min-height: 26px; padding: 0 9px; cursor: pointer;")} className="hv-09c9425e">
                              {b.copyLabel}
                            </button>
                          </div>
                          <pre style={css("margin: 0; padding: 14px; overflow-x: auto; font-family: var(--font-mono); font-size: 13px; line-height: 1.6; color: #e8e6e1;")}>
                            {b.x}
                          </pre>
                        </div>
                      </>
                    ) : null}
                    {(b.isTable) ? (
                      <>
                        <div style={css("border: 1px solid #2a2a2f; border-radius: 8px; overflow-x: auto; max-width: 860px;")}>
                          <table style={css("width: 100%; border-collapse: collapse; font-size: 13px;")}>
                            <thead>
                              <tr style={css(b.headStyle)}>
                                {(b.head).map((h: any, hIndex: number) => (
                                  <Fragment key={hIndex}>
                                    <th style={css("text-align: left; padding: 9px 12px; font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase;")}>
                                      {h}
                                    </th>
                                  </Fragment>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {(b.rows).map((r: any, rIndex: number) => (
                                <Fragment key={rIndex}>
                                  <tr style={css("border-top: 1px solid #2a2a2f;")}>
                                    {(r).map((cell: any, cellIndex: number) => (
                                      <Fragment key={cellIndex}>
                                        <td style={css("padding: 9px 12px; vertical-align: top; line-height: 1.5;")}>
                                          {(cell).map((s: any, sIndex: number) => (
                                            <Fragment key={sIndex}>
                                              {(s.hasLogo) ? (
                                                <>
                                                  <span style={css("display: inline-flex; align-items: center; gap: 5px; padding: 1px 7px 1px 3px; margin: 1px 2px 1px 0; border-radius: 999px; background: #1f1f24; border: 1px solid #2a2a2f; white-space: nowrap; vertical-align: middle;")}>
                                                    <img src={asset(s.logo)} alt="" style={css("width: 14px; height: 14px; object-fit: contain;")} />
                                                    <span style={css("font-weight: 500;")}>
                                                      {s.t}
                                                    </span>
                                                  </span>
                                                </>
                                              ) : null}
                                              {(s.code) ? (
                                                <>
                                                  <code style={css("font-size: 12px; padding: 1px 5px; border-radius: 4px; background: #17171a; white-space: nowrap;")}>
                                                    {s.t}
                                                  </code>
                                                </>
                                              ) : null}
                                              {(s.plain) ? (
                                                <>
                                                  {s.t}
                                                </>
                                              ) : null}
                                            </Fragment>
                                          ))}
                                        </td>
                                      </Fragment>
                                    ))}
                                  </tr>
                                </Fragment>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </>
                    ) : null}
                    {(b.isCallout) ? (
                      <>
                        <div role="note" style={css(b.calloutStyle)}>
                          <span style={css(b.calloutGlyphStyle)}>
                            {b.glyph}
                          </span>
                          <span style={css("display: flex; flex-direction: column; gap: 3px;")}>
                            <span style={css("font-weight: 500; font-size: 13px;")}>
                              {b.title}
                            </span>
                            <span style={css("font-size: 13px; line-height: 1.55; color: #c9c7c0;")}>
                              {(b.segs).map((s: any, sIndex: number) => (
                                <Fragment key={sIndex}>
                                  {(s.code) ? (
                                    <>
                                      <code style={css("font-size: 12px;")}>
                                        {s.t}
                                      </code>
                                    </>
                                  ) : null}
                                  {(s.plain) ? (
                                    <>
                                      {s.t}
                                    </>
                                  ) : null}
                                </Fragment>
                              ))}
                            </span>
                          </span>
                        </div>
                      </>
                    ) : null}
                    {(b.isCards) ? (
                      <>
                        <div style={css("display: flex; flex-wrap: wrap; gap: 8px; max-width: 860px;")}>
                          {(b.cards).map((c: any, cIndex: number) => (
                            <Fragment key={cIndex}>
                              <button type="button" onClick={c.go} style={css(c.style)} className="hv-b871c9ca">
                                <span style={css("display: flex; justify-content: space-between; align-items: center; width: 100%;")}>
                                  <span style={css(c.chip)}>
                                    {c.logo ? <img src={asset(c.logo)} alt="" style={css("width: 18px; height: 18px; object-fit: contain;")} /> : c.g}
                                  </span>
                                  {(c.linked) ? (
                                    <>
                                      <span style={css(c.arrowStyle)}>
                                        {"→"}
                                      </span>
                                    </>
                                  ) : null}
                                </span>
                                <span style={css("font-size: 15px; font-weight: 500; color: #e8e6e1; margin-top: auto;")}>
                                  {c.title}
                                </span>
                                <span style={css("font-size: 13px; line-height: 1.5; color: #a09f99;")}>
                                  {(c.segs).map((s: any, sIndex: number) => (
                                    <Fragment key={sIndex}>
                                      {(s.code) ? (
                                        <>
                                          <code style={css("font-size: 12px;")}>
                                            {s.t}
                                          </code>
                                        </>
                                      ) : null}
                                      {(s.plain) ? (
                                        <>
                                          {s.t}
                                        </>
                                      ) : null}
                                    </Fragment>
                                  ))}
                                </span>
                              </button>
                            </Fragment>
                          ))}
                        </div>
                      </>
                    ) : null}
                    {(b.isSteps) ? (
                      <>
                        <ol style={css("list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; border: 1px solid #2a2a2f; border-radius: 8px; overflow: hidden; max-width: 760px;")}>
                          {(b.steps).map((st: any, stIndex: number) => (
                            <Fragment key={stIndex}>
                              <li style={css("display: grid; grid-template-columns: 36px minmax(0,1fr); gap: 12px; padding: 12px 16px; border-bottom: 1px solid #2a2a2f; align-items: start;")}>
                                <span style={css(st.numStyle)}>
                                  {st.n}
                                </span>
                                <span style={css("display: flex; flex-direction: column; gap: 2px;")}>
                                  <span style={css("font-size: 14px; font-weight: 500;")}>
                                    {st.title}
                                  </span>
                                  <span style={css("font-size: 13px; line-height: 1.55; color: #a09f99;")}>
                                    {(st.segs).map((s: any, sIndex: number) => (
                                      <Fragment key={sIndex}>
                                        {(s.code) ? (
                                          <>
                                            <code style={css("font-size: 12px;")}>
                                              {s.t}
                                            </code>
                                          </>
                                        ) : null}
                                        {(s.plain) ? (
                                          <>
                                            {s.t}
                                          </>
                                        ) : null}
                                      </Fragment>
                                    ))}
                                  </span>
                                </span>
                              </li>
                            </Fragment>
                          ))}
                        </ol>
                      </>
                    ) : null}
                    {(b.isFlow) ? (
                      <>
                        <div style={css("display: flex; flex-wrap: wrap; gap: 6px; align-items: stretch; max-width: 860px; padding: 14px; border: 1px solid #2a2a2f; border-radius: 8px; background: #17171a;")}>
                          {(b.flow).map((f: any, fIndex: number) => (
                            <Fragment key={fIndex}>
                              <div style={css("display: flex; align-items: center; gap: 6px;")}>
                                <div style={css(f.style)}>
                                  <span style={css("font-family: var(--font-mono); font-size: 12px; color: #e8e6e1;")}>
                                    {f.label}
                                  </span>
                                  <span style={css("font-size: 11px; color: #a09f99;")}>
                                    {(f.segs).map((s: any, sIndex: number) => (
                                      <Fragment key={sIndex}>
                                        {(s.code) ? (
                                          <>
                                            <code style={css("font-size: 11px; color: #e8e6e1;")}>
                                              {s.t}
                                            </code>
                                          </>
                                        ) : null}
                                        {(s.plain) ? (
                                          <>
                                            {s.t}
                                          </>
                                        ) : null}
                                      </Fragment>
                                    ))}
                                  </span>
                                </div>
                                {(f.arrow) ? (
                                  <>
                                    <span style={css("font-family: var(--font-mono); color: #a09f99;")}>
                                      {"→"}
                                    </span>
                                  </>
                                ) : null}
                              </div>
                            </Fragment>
                          ))}
                        </div>
                      </>
                    ) : null}
                    {(b.isKv) ? (
                      <>
                        <div style={css("display: flex; flex-wrap: wrap; gap: 8px; max-width: 860px;")}>
                          {(b.kv).map((k: any, kIndex: number) => (
                            <Fragment key={kIndex}>
                              <div style={css(k.style)}>
                                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                                  {(k.ks).map((s: any, sIndex: number) => (
                                    <Fragment key={sIndex}>
                                      {s.t}
                                    </Fragment>
                                  ))}
                                </span>
                                <span style={css("font-size: 14px; font-weight: 500;")}>
                                  {(k.vs).map((s: any, sIndex: number) => (
                                    <Fragment key={sIndex}>
                                      {(s.code) ? (
                                        <>
                                          <code style={css("font-size: 13px;")}>
                                            {s.t}
                                          </code>
                                        </>
                                      ) : null}
                                      {(s.plain) ? (
                                        <>
                                          {s.t}
                                        </>
                                      ) : null}
                                    </Fragment>
                                  ))}
                                </span>
                              </div>
                            </Fragment>
                          ))}
                        </div>
                      </>
                    ) : null}
                    {(b.isDetails) ? (
                      <>
                        <div style={css("display: flex; flex-direction: column; gap: 6px; max-width: 760px;")}>
                          {(b.details).map((d: any, dIndex: number) => (
                            <Fragment key={dIndex}>
                              <details style={css(d.style)}>
                                <summary style={css("cursor: pointer; font-size: 14px; font-weight: 500; padding: 12px 14px; display: flex; gap: 10px; align-items: center;")}>
                                  <span style={css(d.gStyle)}>
                                    {"+"}
                                  </span>
                                  {d.q}
                                </summary>
                                <div style={css("padding: 0 14px 14px 36px; font-size: 13px; line-height: 1.6; color: #c9c7c0;")}>
                                  {(d.segs).map((s: any, sIndex: number) => (
                                    <Fragment key={sIndex}>
                                      {(s.code) ? (
                                        <>
                                          <code style={css("font-size: 12px;")}>
                                            {s.t}
                                          </code>
                                        </>
                                      ) : null}
                                      {(s.plain) ? (
                                        <>
                                          {s.t}
                                        </>
                                      ) : null}
                                    </Fragment>
                                  ))}
                                </div>
                              </details>
                            </Fragment>
                          ))}
                        </div>
                      </>
                    ) : null}
                  </Fragment>
                ))}
                {(hasDepth) ? (
                  <>
                    <div style={css("display: flex; flex-direction: column; gap: 10px; margin-top: 24px; max-width: 860px; padding: 18px; border-radius: 10px; background: #17171a; border: 1px solid #2a2a2f;")}>
                      <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                        {"Same concept, different resolution"}
                      </span>
                      <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 130px), 1fr)); gap: 6px;")}>
                        {(depth).map((d: any, dIndex: number) => (
                          <Fragment key={dIndex}>
                            <a href={link(d.href)} onClick={d.go} style={css("display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border-radius: 8px; background: #111114; border: 1px solid #2a2a2f; text-decoration: none; color: #e8e6e1;")} className="hv-a9ee1797">
                              <span style={css(d.kStyle)}>
                                {d.k}
                              </span>
                              <span style={css("font-size: 13px; font-weight: 500;")}>
                                {d.l}
                              </span>
                            </a>
                          </Fragment>
                        ))}
                      </div>
                    </div>
                  </>
                ) : null}
                <div style={css("display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 28px; max-width: 760px;")}>
                  <button type="button" onClick={prev.go} disabled={prev.none} style={css(prev.style)} className="hv-83180a19">
                    <span style={css("font-size: 12px; color: #a09f99;")}>
                      {"← Previous"}
                    </span>
                    <span style={css("font-size: 14px; font-weight: 500; color: #e8e6e1;")}>
                      {prev.label}
                    </span>
                  </button>
                  <button type="button" onClick={next.go} disabled={next.none} style={css(next.style)} className="hv-83180a19">
                    <span style={css("font-size: 12px; color: #a09f99;")}>
                      {"Next →"}
                    </span>
                    <span style={css("font-size: 14px; font-weight: 500; color: #e8e6e1;")}>
                      {next.label}
                    </span>
                  </button>
                </div>
              </article>
            </>
          ) : null}
        </main>
        {(showOutline) ? (
          <>
            <aside aria-label="On this page" style={css("position: sticky; top: 100px; align-self: start; padding: 28px 20px; display: flex; flex-direction: column; gap: 6px; font-size: 13px;")}>
              <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99; margin-bottom: 4px;")}>
                {"On this page"}
              </span>
              {(outline).map((o: any, oIndex: number) => (
                <Fragment key={oIndex}>
                  <a href={link(o.href)} style={css(o.style)} className="hv-761d44c6">
                    {o.label}
                  </a>
                </Fragment>
              ))}
              <div style={css(relatedStyle)}>
                <span style={css("font-size: 11px; font-weight: 500; letter-spacing: 0.04em; text-transform: uppercase; color: #a09f99;")}>
                  {"In "}{section.label}
                </span>
                <span style={css("font-size: 12px; color: #a09f99;")}>
                  {sectionCount}{" pages"}
                </span>
              </div>
            </aside>
          </>
        ) : null}
      </div>
      {(searchOpen) ? (
        <>
          <div onClick={closeSearch} style={css("position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,0.7); display: flex; justify-content: center; align-items: flex-start; padding: 10vh 16px 16px;")}>
            <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Search docs" onClick={stop} onKeyDown={trapKeys} style={css("width: 100%; max-width: 620px; background: #111114; border: 1px solid #2a2a2f; border-radius: 8px; box-shadow: 0 8px 16px rgba(26,26,30,0.06), 0 24px 64px rgba(26,26,30,0.12); overflow: hidden;")}>
              <div style={css("display: flex; align-items: center; gap: 10px; padding: 0 14px; border-bottom: 1px solid #2a2a2f;")}>
                <span style={css("font-family: var(--font-mono); color: #9fbad6;")}>
                  {"⌕"}
                </span>
                <input ref={searchRef} value={query} onChange={onQuery} onKeyDown={onKey} aria-label="Search" role="combobox" aria-expanded={hasResults} aria-controls="docs-search-results" aria-autocomplete="list" placeholder="Search signals, connectors, journeys…" style={css("flex: 1; font-family: inherit; font-size: 15px; height: 48px; border: 0; background: transparent; color: #e8e6e1; outline: none;")} />
                <kbd style={css("font-family: var(--font-mono); font-size: 11px; padding: 1px 5px; border: 1px solid #2a2a2f; border-radius: 3px; color: #a09f99;")}>
                  {"esc"}
                </kbd>
              </div>
              {(hasResults) ? (
                <>
                  <ul id="docs-search-results" role="listbox" style={css("list-style: none; margin: 0; padding: 6px; max-height: 380px; overflow-y: auto;")}>
                    {(results).map((r: any, rIndex: number) => (
                      <Fragment key={rIndex}>
                        <li role="option" aria-selected={r.sel} onClick={r.go} onMouseEnter={r.hover} style={css(r.style)}>
                          <span style={css("display: flex; justify-content: space-between; gap: 8px;")}>
                            <span style={css("font-size: 14px; font-weight: 500; display: flex; gap: 8px;")}>
                              <span style={css(r.glyphStyle)}>
                                {r.glyph}
                              </span>
                              {r.title}
                            </span>
                            <span style={css("font-size: 12px; color: #a09f99;")}>
                              {r.section}
                            </span>
                          </span>
                          <span style={css("font-size: 12px; line-height: 1.5; color: #a09f99; padding-left: 22px;")}>
                            {r.snippet}
                          </span>
                        </li>
                      </Fragment>
                    ))}
                  </ul>
                </>
              ) : null}
              {(noResults) ? (
                <>
                  <div style={css("padding: 24px 18px; display: flex; flex-direction: column; gap: 8px;")}>
                    <span style={css("font-size: 14px; font-weight: 500;")}>
                      {"No public pages match “"}{query}{"”"}
                    </span>
                    <span style={css("font-size: 13px; line-height: 1.55; color: #a09f99;")}>
                      {"Try “consent”, “journey”, “Stripe”, or an event like "}
                      <code style={css("font-size: 12px;")}>
                        {"order_completed"}
                      </code>
                      {"."}
                    </span>
                    <a href={link("Contact.dc.html?brand=aether&type=developer")} style={css("display: inline-flex; gap: 6px; font-size: 13px; font-weight: 500; color: #9cc4a9; text-decoration: none;")}>
                      {"Ask an engineer"}
                      <span style={css("font-family: var(--font-mono);")}>
                        {"→"}
                      </span>
                    </a>
                  </div>
                </>
              ) : null}
              <div style={css("display: flex; gap: 14px; padding: 8px 14px; border-top: 1px solid #2a2a2f; background: #17171a; font-family: var(--font-mono); font-size: 11px; color: #a09f99;")}>
                <span>
                  {"↑ ↓ move"}
                </span>
                <span>
                  {"↵ open"}
                </span>
                <span>
                  {"esc close"}
                </span>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
    </div>
  );
}
