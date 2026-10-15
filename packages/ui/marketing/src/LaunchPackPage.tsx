import { Fragment, type ReactNode } from 'react';
import type { LaunchPackPage as LaunchPackPageData } from './content-loader';

interface Props {
  readonly page: LaunchPackPageData;
}

const AETHER_MARKETING_URL = 'https://aether.olympuslabsml.com';
const AETHER_DOCS_URL = 'https://docs.olympuslabsml.com';
const AETHER_STATUS_URL = 'https://status.olympuslabsml.com';

function ctaHref(page: LaunchPackPageData, label: string): string {
  const normalized = label.trim().toLowerCase();
  if (
    normalized.includes('developer docs') ||
    normalized.includes('technical documentation') ||
    normalized.includes('api documentation') ||
    normalized.includes('api reference') ||
    normalized.includes('open the api reference') ||
    normalized.includes('sdk guide') ||
    normalized.includes('developer guide') ||
    normalized.includes('quickstart') ||
    normalized.includes('event model') ||
    normalized.includes('event contract') ||
    normalized.includes('events and consent') ||
    normalized.includes('sdk parity') ||
    normalized.includes('connection model')
  ) {
    return AETHER_DOCS_URL;
  }
  if (normalized.includes('open status') || normalized.includes('system status')) {
    return AETHER_STATUS_URL;
  }
  if (normalized.includes('how aether works') || normalized.includes('see how aether works')) {
    return '/how-it-works';
  }
  if (normalized.includes('explore olympus research')) {
    return 'https://www.olympuslabsml.com/research';
  }
  if (
    normalized.includes('aether') ||
    normalized.includes('visit aether') ||
    normalized.includes('explore aether') ||
    normalized.includes('meet aether')
  ) {
    return AETHER_MARKETING_URL;
  }
  if (normalized.includes('product story') || normalized.includes('product overview')) {
    return page.brand === 'Olympus Labs' ? '/products/aether' : '/platform';
  }
  if (normalized.includes('developer path') || normalized.includes('developer journey')) return '/developers';
  if (normalized.includes('why olympus')) return 'https://www.olympuslabsml.com/why-olympus';
  if (normalized.includes('benchmark') || normalized.includes('propose a benchmark')) {
    return '/proof/benchmark';
  }
  if (normalized.includes('research brief')) return '/proof/research-brief';
  if (normalized.includes('methodology')) return '/proof/methodology';
  if (
    normalized.includes('read the proof') ||
    normalized.includes('proof standard') ||
    normalized.includes('synthetic demonstration') ||
    normalized.includes('customer story')
  ) {
    return '/stories';
  }
  if (normalized.includes('document an outcome')) return '/proof/customer-outcomes';
  if (normalized.includes('proof partner')) return '/proof-partner';
  if (
    normalized.includes('start a pilot') ||
    normalized.includes('pilot path') ||
    normalized.includes('pilot brief') ||
    normalized.includes('pilot')
  ) {
    return '/start-pilot';
  }
  if (normalized.includes('architecture review')) return '/architecture-review';
  if (normalized.includes('architecture')) return '/architecture';
  if (normalized.includes('identity model')) return '/identity-resolution';
  if (normalized.includes('profile perspective')) return '/profile-360';
  if (normalized.includes('graph loop') || normalized.includes('intelligence graph')) {
    return '/intelligence-graph';
  }
  if (normalized.includes('journey')) return '/how-it-works';
  if (normalized.includes('connection') || normalized.includes('connect ')) return '/connections';
  if (normalized.includes('security review')) return '/security-review';
  if (normalized.includes('procurement') || normalized.includes('assurance review')) return '/procurement';
  if (normalized.includes('trust') || normalized.includes('security')) return '/security';
  if (normalized.includes('privacy')) return '/legal/privacy';
  if (normalized.includes('terms')) return '/legal/terms';
  if (normalized.includes('resource')) return '/resources';
  if (normalized.includes('research')) return '/research';
  if (normalized.includes('faq')) return '/faq';
  if (normalized.includes('solution')) return '/solutions';
  if (normalized.includes('book a') || normalized.includes('conversation') || normalized.includes('brief')) {
    return '/contact';
  }
  if (page.brand === 'Olympus Labs') return '/contact';
  return '/contact';
}

function isExternalHref(href: string): boolean {
  return /^https?:\/\//.test(href);
}

function inlineMarkup(text: string): ReactNode[] {
  const tokens = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^\)]+\))/g);
  return tokens.map((token, index) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={index}>{token.slice(2, -2)}</strong>;
    }
    const link = /^\[([^\]]+)\]\(([^\)]+)\)$/.exec(token);
    if (link) {
      const label = link[1] ?? '';
      const href = link[2] ?? '';
      return (
        <a
          key={index}
          href={href}
          className="text-accent underline underline-offset-2"
          rel={href.startsWith('http') ? 'noreferrer' : undefined}
        >
          {label}
        </a>
      );
    }
    return <Fragment key={index}>{token}</Fragment>;
  });
}

function MarkdownBody({ body }: { readonly body: string }) {
  const lines = body.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let listKind: 'ordered' | 'unordered' | null = null;
  let listItems: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length === 0) return;
    const text = paragraph.join(' ').replace(/\s+/g, ' ').trim();
    if (text) {
      blocks.push(
        <p key={'p-' + blocks.length} className="mkt-body">
          {inlineMarkup(text)}
        </p>,
      );
    }
    paragraph = [];
  };

  const flushList = () => {
    if (listKind === null || listItems.length === 0) return;
    const Tag = listKind === 'ordered' ? 'ol' : 'ul';
    blocks.push(
      <Tag
        key={'list-' + blocks.length}
        className={`mkt-body ml-6 ${listKind === 'ordered' ? 'list-decimal' : 'list-disc'}`}
      >
        {listItems.map((item, itemIndex) => (
          <li key={itemIndex} className="pl-1">
            {inlineMarkup(item)}
          </li>
        ))}
      </Tag>,
    );
    listKind = null;
    listItems = [];
  };

  for (const [index, rawLine] of lines.entries()) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    if (/^\*\*(Primary|Secondary) CTA:\*\*/.test(line)) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph();
      flushList();
      const level = (heading[1] ?? '').length;
      const headingText = heading[2] ?? '';
      const className =
        level === 1
          ? 'mkt-display'
          : level === 2
            ? 'mkt-h2'
            : 'mt-8 text-xl font-semibold text-text-primary';
      const Tag = level === 1 ? 'h1' : level === 2 ? 'h2' : 'h3';
      blocks.push(
        <Tag key={'h-' + index} className={className}>
          {inlineMarkup(headingText)}
        </Tag>,
      );
      continue;
    }
    const orderedItem = /^\d+\.\s+(.+)$/.exec(line);
    if (orderedItem) {
      flushParagraph();
      if (listKind !== 'ordered') flushList();
      listKind = 'ordered';
      listItems.push(orderedItem[1] ?? '');
      continue;
    }
    const bullet = /^[-*]\s+(.+)$/.exec(line);
    if (bullet) {
      flushParagraph();
      if (listKind !== 'unordered') flushList();
      listKind = 'unordered';
      listItems.push(bullet[1] ?? '');
      continue;
    }
    if (listKind !== null && /^\s+/.test(rawLine)) {
      const lastItem = listItems.length - 1;
      if (lastItem >= 0) {
        listItems[lastItem] = `${listItems[lastItem]} ${line}`;
        continue;
      }
    }
    flushList();
    paragraph.push(line);
  }
  flushParagraph();
  flushList();

  return <div className="space-y-5">{blocks}</div>;
}

export function LaunchPackPage({ page }: Props) {
  const ctas = [page.primaryCta, page.secondaryCta].filter(
    (cta): cta is string => Boolean(cta),
  );
  return (
    <article className="mkt-container py-16 md:py-24" data-content-status={page.status}>
      <div className="mb-12 max-w-4xl border-b border-border-default pb-10">
        <div className="flex flex-wrap items-center gap-3">
          <span className="mkt-eyebrow">{page.pageType.replace(/-/g, ' ')}</span>
        </div>
        {page.seoDescription && <p className="mkt-lead mt-5 max-w-3xl">{page.seoDescription}</p>}
      </div>
      <div className="mkt-measure">
        <MarkdownBody body={page.body} />
      </div>
      {ctas.length > 0 && (
        <nav aria-label="Next steps" className="mt-12 flex flex-wrap gap-3">
          {ctas.map((cta, index) => {
            const href = ctaHref(page, cta);
            const external = isExternalHref(href);
            return (
              <a
                key={cta}
                href={href}
                className={
                  index === 0
                    ? 'rounded-md bg-accent px-4 py-2 text-sm font-semibold text-text-inverse'
                    : 'rounded-md border border-border-default px-4 py-2 text-sm font-semibold text-text-primary'
                }
                {...(external ? { target: '_blank', rel: 'noreferrer' } : {})}
              >
                {cta}
              </a>
            );
          })}
        </nav>
      )}
    </article>
  );
}
