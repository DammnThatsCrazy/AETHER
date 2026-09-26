import { useLocation } from 'react-router-dom';
import { PageShell } from '@site/components/page-shell';
import { useSite } from '@site/site/site-context';
import { NOT_FOUND_LINKS, type AccentId } from '@site/site/navigation';

// Full class strings per accent so Tailwind keeps them in the build.
const ACCENT_CLASSES: Record<AccentId, { card: string; chip: string }> = {
  cobalt: { card: 'border-t-cobalt hover:border-cobalt hover:bg-cobalt/[0.12]', chip: 'bg-cobalt/[0.12] text-cobalt-ink' },
  sage: { card: 'border-t-sage hover:border-sage hover:bg-sage/[0.15]', chip: 'bg-sage/[0.15] text-sage-ink' },
  ochre: { card: 'border-t-ochre hover:border-ochre hover:bg-ochre/[0.16]', chip: 'bg-ochre/[0.16] text-ochre-ink' },
  steel: { card: 'border-t-steel hover:border-steel hover:bg-steel/[0.14]', chip: 'bg-steel/[0.14] text-steel-ink' },
};

export function NotFoundPage() {
  const { site, href } = useSite();
  const { pathname } = useLocation();

  return (
    <PageShell title="Page not found">
      <div
        data-screen-label="404"
        className="mx-auto flex w-full max-w-[1200px] flex-col gap-7 px-6 py-[clamp(48px,9vw,120px)]"
      >
        <div className="flex max-w-[640px] flex-col gap-4">
          <span className="inline-flex items-center gap-2.5">
            <span className="rounded-full bg-ember/[0.12] px-2.5 py-1 font-mono text-body-sm text-ember-ink">■ 404</span>
            <code className="max-w-[360px] overflow-hidden text-ellipsis whitespace-nowrap font-mono text-caption text-slate">
              {pathname}
            </code>
          </span>
          <h1 className="m-0 text-[clamp(36px,5.6vw,60px)] font-medium leading-[1.04] tracking-[-0.03em]">
            This page does not exist
          </h1>
          <p className="m-0 text-[16px] leading-[1.6] text-graphite-body">
            The link may be old, or the page may have moved. Nothing was lost — pick up from one of these.
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          {NOT_FOUND_LINKS[site].map((l) => {
            const accent = ACCENT_CLASSES[l.accent];
            return (
              <a
                key={l.label}
                href={href(l.site, l.path)}
                className={
                  'flex min-h-[150px] flex-[1_1_220px] flex-col gap-2 rounded-lg border border-t-[3px] border-line bg-stone-50 p-6 ' +
                  'text-ink no-underline transition-colors duration-120 ease-site ' +
                  accent.card
                }
              >
                <span
                  aria-hidden="true"
                  className={`flex h-9 w-9 items-center justify-center rounded-[10px] font-mono text-[16px] ${accent.chip}`}
                >
                  {l.glyph}
                </span>
                <span className="mt-auto text-[16px] font-medium">{l.label}</span>
                <span className="text-body-sm text-graphite-body">{l.body}</span>
              </a>
            );
          })}
        </div>
      </div>
    </PageShell>
  );
}
