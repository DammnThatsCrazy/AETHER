/**
 * Shared building blocks for the marketing pages. The designs repeat a small
 * vocabulary (buttons, section heads, cards, step lists, the page hero and the
 * closing call to action); these keep every page on the same spacing and type.
 *
 * Runtime accents are passed as CSS variables (see `accentVars`) so hover
 * classes can still override resting colors; inline colors would win.
 */
import type { CSSProperties, ReactNode } from 'react';
import { ACCENTS, soft, tint, type Accent } from '@site/site/palette';

export function accentVars(accent: Accent): CSSProperties {
  const c = ACCENTS[accent];
  return {
    '--a-base': c.base,
    '--a-ink': c.ink,
    '--a-soft': soft(accent),
    '--a-line': tint(accent, 0.4),
  } as CSSProperties;
}

const mono = 'font-mono';

export function Glyph({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <span aria-hidden="true" className={`${mono} ${className}`}>
      {children}
    </span>
  );
}

/* Buttons ---------------------------------------------------------------- */

type ButtonVariant = 'solid' | 'soft' | 'ghost-dark';

const BUTTON_BASE =
  'inline-flex min-h-11 items-center justify-center gap-2 whitespace-nowrap rounded-control border px-5 text-[14px] font-medium no-underline ' +
  'transition-colors duration-120 ease-site';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  solid:
    'text-stone-50 [background:var(--a-ink)] [border-color:var(--a-ink)] hover:text-stone-50 hover:[background:var(--a-base)] hover:[border-color:var(--a-base)]',
  soft: '[background:var(--a-soft)] [border-color:var(--a-line)] [color:var(--a-ink)] hover:[border-color:var(--a-base)] hover:[color:var(--a-ink)]',
  'ghost-dark': 'border-[#3a3a40] bg-transparent text-bone hover:border-slate hover:bg-graphite-hover hover:text-bone',
};

export interface ButtonLinkProps {
  href: string;
  children: ReactNode;
  variant?: ButtonVariant;
  accent?: Accent;
  /** Mono glyph before the label. */
  glyph?: string;
  /** Image or other element before the label. */
  icon?: ReactNode;
  /** Adds a trailing mono arrow. */
  arrow?: boolean;
  className?: string;
}

export function ButtonLink({ href, children, variant = 'solid', accent = 'cobalt', glyph, icon, arrow, className = '' }: ButtonLinkProps) {
  return (
    <a href={href} className={`${BUTTON_BASE} ${BUTTON_VARIANTS[variant]} ${className}`} style={accentVars(accent)}>
      {icon}
      {glyph && <Glyph>{glyph}</Glyph>}
      {children}
      {arrow && <Glyph>→</Glyph>}
    </a>
  );
}

/* Type ------------------------------------------------------------------- */

/** Small uppercase label; accent ink on light surfaces, accent base on dark. */
export function Eyebrow({ accent, glyph, dark, children }: { accent: Accent; glyph?: string; dark?: boolean; children: ReactNode }) {
  const c = ACCENTS[accent];
  return (
    <span className="text-label uppercase" style={{ color: dark ? c.base : c.ink }}>
      {glyph && <Glyph>{glyph}</Glyph>} {children}
    </span>
  );
}

export function IconTile({ glyph, accent, size = 36 }: { glyph: string; accent: Accent; size?: 32 | 36 }) {
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center rounded-[10px] ${mono} ${size === 36 ? 'h-9 w-9 text-[16px]' : 'h-8 w-8 text-[14px]'}`}
      style={{ background: soft(accent), color: ACCENTS[accent].ink }}
    >
      {glyph}
    </span>
  );
}

/* Sections --------------------------------------------------------------- */

type Tone = 'paper' | 'stone' | 'dark';

const TONES: Record<Tone, string> = {
  paper: 'border-line bg-stone-50',
  stone: 'border-line bg-stone-100',
  dark: 'border-ink bg-ink text-bone',
};

export function Section({ id, tone = 'paper', children }: { id?: string; tone?: Tone; children: ReactNode }) {
  return (
    <section id={id} data-theme={tone === 'dark' ? 'dark' : undefined} className={`scroll-mt-14 border-b ${TONES[tone]}`}>
      <div className="mx-auto flex max-w-page flex-col gap-6 px-6 py-[clamp(64px,9vw,112px)]">{children}</div>
    </section>
  );
}

export interface SectionHeadProps {
  accent: Accent;
  glyph: string;
  eyebrow: string;
  title: ReactNode;
  /** Short lede shown beside the heading on wide screens. */
  lede?: ReactNode;
  dark?: boolean;
}

export function SectionHead({ accent, glyph, eyebrow, title, lede, dark }: SectionHeadProps) {
  return (
    <div className="grid items-end gap-x-8 gap-y-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr))]">
      <div className="flex flex-col gap-3">
        <Eyebrow accent={accent} glyph={glyph} dark={dark}>
          {eyebrow}
        </Eyebrow>
        <h2
          className={`m-0 text-balance text-[clamp(28px,3.6vw,44px)] font-medium leading-[1.06] tracking-[-0.028em] ${dark ? 'text-bone' : 'text-ink'}`}
        >
          {title}
        </h2>
      </div>
      {lede ? (
        <p className={`m-0 max-w-[560px] text-pretty text-[15px] leading-[1.6] ${dark ? 'text-mist' : 'text-graphite-body'}`}>{lede}</p>
      ) : (
        <span />
      )}
    </div>
  );
}

/* Cards ------------------------------------------------------------------ */

type CardVariant = 'plain' | 'rule' | 'tint' | 'dark';

const CARD_BASE = 'box-border flex min-w-0 flex-col gap-2.5 rounded-lg border p-6 no-underline transition-colors duration-120 ease-site';

const CARD_VARIANTS: Record<CardVariant, string> = {
  plain: 'border-line bg-stone-50 text-ink hover:border-line-strong hover:bg-stone-200 hover:text-ink',
  // Top rule keeps its accent on hover, so only the other sides change.
  rule: 'border-line border-t-[3px] bg-stone-50 text-ink hover:border-x-line-strong hover:border-b-line-strong hover:bg-stone-200 hover:text-ink',
  tint: 'text-ink [background:var(--a-soft)] [border-color:var(--a-line)] hover:text-ink hover:[border-color:var(--a-base)]',
  dark: 'border-ink bg-ink text-bone hover:border-graphite-hairline hover:bg-graphite-hover hover:text-bone',
};

export interface CardProps {
  variant?: CardVariant;
  accent?: Accent;
  /** CSS flex shorthand; the designs size cards by basis, not columns. */
  flex?: string;
  href?: string;
  /** Icon tile at the top of the card. */
  glyph?: string;
  eyebrow?: string;
  title?: ReactNode;
  large?: boolean;
  body?: ReactNode;
  /** Link-style call to action pinned to the bottom. */
  cta?: string;
  children?: ReactNode;
}

export function Card({ variant = 'plain', accent = 'cobalt', flex = '1 1 200px', href, glyph, eyebrow, title, large, body, cta, children }: CardProps) {
  const dark = variant === 'dark';
  const style: CSSProperties = { flex, ...accentVars(accent) };
  if (variant === 'rule') style.borderTopColor = ACCENTS[accent].base;
  const content = (
    <>
      {glyph && (
        <span className="flex items-center justify-between gap-2">
          <IconTile glyph={glyph} accent={accent} />
        </span>
      )}
      {eyebrow && <span className={`text-label uppercase ${dark ? 'text-mist' : 'text-slate'}`}>{eyebrow}</span>}
      {title && (
        <span className={large ? 'text-h' : 'text-[16px] font-medium leading-[1.3] tracking-[-0.1px]'}>{title}</span>
      )}
      {body && (
        <span className={`${large ? 'text-[15px]' : 'text-body-sm'} leading-[1.6] ${dark ? 'text-mist' : 'text-graphite-body'}`}>{body}</span>
      )}
      {children}
      {cta && (
        <span className="mt-auto text-body-sm font-medium" style={{ color: ACCENTS[accent].ink }}>
          {cta} <Glyph>→</Glyph>
        </span>
      )}
    </>
  );
  const className = `${CARD_BASE} ${CARD_VARIANTS[variant]}`;
  return href ? (
    <a href={href} className={className} style={style}>
      {content}
    </a>
  ) : (
    <div className={className} style={style}>
      {content}
    </div>
  );
}

export function CardRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-3">{children}</div>;
}

/** Marked list, e.g. ✓ allowed / ■ not allowed. */
export function MarkList({ items, mark, color }: { items: string[]; mark: string; color: string }) {
  return (
    <ul className="m-0 flex list-none flex-col gap-[7px] p-0">
      {items.map((item) => (
        <li key={item} className="flex gap-2.5 text-body-sm leading-[1.5]">
          <Glyph className="shrink-0">
            <span style={{ color }}>{mark}</span>
          </Glyph>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Numbered steps (01, 02, …) with an accent rule on each. */
export function StepList({ steps }: { steps: Array<{ title: string; body: string; accent: Accent }> }) {
  return (
    <ol className="m-0 flex list-none flex-wrap gap-3 p-0">
      {steps.map((s, i) => (
        <li
          key={s.title}
          className="flex min-w-0 flex-[1_1_180px] flex-col gap-2 rounded-card border border-t-[3px] border-line bg-stone-50 p-4 transition-colors duration-120 ease-site hover:[background:var(--a-soft)]"
          style={{ ...accentVars(s.accent), borderTopColor: ACCENTS[s.accent].base }}
        >
          <span className={`${mono} text-caption`} style={{ color: ACCENTS[s.accent].ink }}>
            {String(i + 1).padStart(2, '0')}
          </span>
          <span className="text-[15px] font-medium">{s.title}</span>
          <span className="text-body-sm leading-[1.55] text-graphite-body">{s.body}</span>
        </li>
      ))}
    </ol>
  );
}

/* Page hero -------------------------------------------------------------- */

export interface Crumb {
  label: string;
  href?: string;
}

export interface TocLink {
  id: string;
  label: string;
  accent: Accent;
}

export interface PageHeroProps {
  crumbs: Crumb[];
  accent: Accent;
  glyph: string;
  eyebrow: string;
  title: ReactNode;
  lede: ReactNode;
  actions?: ReactNode;
  toc?: TocLink[];
}

export function PageHero({ crumbs, accent, glyph, eyebrow, title, lede, actions, toc }: PageHeroProps) {
  return (
    <section className="border-b border-line bg-stone-50">
      <div className="mx-auto flex max-w-page flex-col gap-[22px] px-6 pb-[clamp(40px,6vw,64px)] pt-[clamp(40px,7vw,88px)]">
        <nav aria-label="Breadcrumb" className="flex gap-1.5 text-caption text-slate">
          {crumbs.map((c, i) => (
            <span key={c.label} className="flex gap-1.5">
              {i > 0 && <span aria-hidden="true">/</span>}
              {c.href ? (
                <a href={c.href} className="text-slate no-underline hover:text-ink">
                  {c.label}
                </a>
              ) : (
                <span aria-current="page" className="text-ink">
                  {c.label}
                </span>
              )}
            </span>
          ))}
        </nav>
        <span className="inline-flex items-center gap-2.5">
          <IconTile glyph={glyph} accent={accent} size={32} />
          <span className="text-label uppercase" style={{ color: ACCENTS[accent].ink }}>
            {eyebrow}
          </span>
        </span>
        <h1 className="m-0 max-w-[900px] text-balance text-[clamp(36px,5.6vw,60px)] font-medium leading-[1.04] tracking-[-0.03em]">
          {title}
        </h1>
        <p className="m-0 max-w-[640px] text-pretty text-[17px] leading-[1.6] text-graphite-body">{lede}</p>
        {actions && <div className="flex flex-wrap gap-3">{actions}</div>}
        {toc && (
          <nav aria-label="On this page" className="flex flex-wrap gap-1.5 pt-1.5">
            {toc.map((t) => (
              <a
                key={t.id}
                href={`#${t.id}`}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-stone-50 px-[11px] py-1.5 text-caption font-medium no-underline transition-colors duration-120 ease-site [color:var(--a-ink)] hover:[background:var(--a-soft)] hover:[border-color:var(--a-base)] hover:[color:var(--a-ink)]"
                style={accentVars(t.accent)}
              >
                <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ background: ACCENTS[t.accent].base }} />
                {t.label}
              </a>
            ))}
          </nav>
        )}
      </div>
    </section>
  );
}

/* Closing call to action ------------------------------------------------- */

export interface ClosingCtaProps {
  title: ReactNode;
  body: ReactNode;
  primary: { href: string; label: string; accent: Accent };
  secondary?: { href: string; label: string };
}

export function ClosingCta({ title, body, primary, secondary }: ClosingCtaProps) {
  return (
    <section data-theme="dark" className="bg-ink text-bone">
      <div className="mx-auto flex max-w-page flex-col gap-[18px] px-6 py-[clamp(72px,10vw,128px)]">
        <h2 className="m-0 max-w-[760px] text-balance text-[clamp(28px,4vw,46px)] font-medium leading-[1.05] tracking-[-0.025em] text-bone">
          {title}
        </h2>
        <p className="m-0 max-w-[560px] text-[15px] leading-[1.6] text-mist">{body}</p>
        <div className="flex flex-wrap gap-3">
          <ButtonLink href={primary.href} accent={primary.accent} arrow>
            {primary.label}
          </ButtonLink>
          {secondary && (
            <ButtonLink href={secondary.href} variant="ghost-dark">
              {secondary.label}
            </ButtonLink>
          )}
        </div>
      </div>
    </section>
  );
}
