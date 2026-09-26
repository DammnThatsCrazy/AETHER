import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useSite } from '@site/site/site-context';
import { HEADER_NAV, type SiteLink } from '@site/site/navigation';

const secondaryButton =
  'inline-flex items-center justify-center whitespace-nowrap rounded-control border border-line bg-stone-100 font-medium text-ink ' +
  'transition-colors duration-120 ease-site hover:border-line-strong hover:bg-stone-200';
const primaryButton =
  'inline-flex items-center justify-center whitespace-nowrap rounded-control bg-ink font-medium text-stone-50 ' +
  'transition-colors duration-120 ease-site hover:bg-cobalt-ink';

/** `active` is the nav label to highlight; pages pass their own. */
export function SiteHeader({ active = '' }: { active?: string }) {
  const { site, href } = useSite();
  const nav = HEADER_NAV[site];
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const to = (l: SiteLink) => href(l.site, l.path);

  // Close the mobile menu whenever the route changes.
  useEffect(() => setOpen(false), [location.pathname]);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-stone-50 font-sans">
      <div className="mx-auto flex h-14 max-w-page items-center justify-between gap-6 px-6">
        <div className="flex shrink-0 items-center gap-2.5">
          {site === 'aether' ? (
            <>
              <a href={href('aether', '/')} aria-label="Aether home" className="flex items-center gap-2 text-ink no-underline">
                <img src="/logo-aether-layers.svg" alt="" className="block h-[22px] w-[22px]" />
                <span className="text-[17px] font-medium tracking-[-0.4px]">Aether</span>
              </a>
              <span className="text-caption text-slate">
                by{' '}
                <a href={href('olympus', '/')} className="text-slate underline underline-offset-2">
                  Olympus Labs
                </a>
              </span>
            </>
          ) : (
            <a href={href('olympus', '/')} aria-label="Olympus Labs home" className="flex items-center gap-[9px] text-ink no-underline">
              <img src="/logo-olympus-arch.svg" alt="" className="block h-[18px] w-[18px]" />
              <span className="text-[16px] font-medium tracking-[-0.3px]">Olympus Labs</span>
            </a>
          )}
        </div>

        <nav aria-label="Primary" className="hidden items-center gap-0.5 min-[1000px]:flex">
          {nav.items.map((item) => (
            <a
              key={item.label}
              href={to(item)}
              aria-current={item.label === active ? 'page' : undefined}
              className={
                'rounded px-2.5 py-2 text-body-sm font-medium leading-normal no-underline transition-colors duration-120 ease-site hover:text-ink ' +
                (item.label === active ? 'text-ink' : 'text-slate')
              }
            >
              {item.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-2 min-[1000px]:flex">
          <a href={to(nav.secondary)} className={`${secondaryButton} min-h-9 px-3.5 text-body-sm`}>
            {nav.secondary.label}
          </a>
          <a href={to(nav.primary)} className={`${primaryButton} min-h-9 px-3.5 text-body-sm`}>
            {nav.primary.label}
          </a>
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="site-mobile-nav"
          aria-label={open ? 'Close menu' : 'Open menu'}
          className="flex h-11 w-11 items-center justify-center rounded border-0 bg-transparent font-mono text-lg text-ink min-[1000px]:hidden"
        >
          {open ? '✕' : '≡'}
        </button>
      </div>

      {open && (
        <nav id="site-mobile-nav" aria-label="Mobile" className="border-t border-line bg-stone-50 px-6 pb-5 pt-2 min-[1000px]:hidden">
          <div className="flex flex-col">
            {nav.items.map((item) => (
              <a
                key={item.label}
                href={to(item)}
                className="flex justify-between border-b border-line-soft py-3 text-[15px] text-ink no-underline"
              >
                <span>{item.label}</span>
                <span aria-hidden="true" className="font-mono text-slate">
                  →
                </span>
              </a>
            ))}
          </div>
          <div className="mt-4 flex flex-col gap-2">
            <a href={to(nav.secondary)} className={`${secondaryButton} min-h-[42px] px-[18px] text-[14px]`}>
              {nav.secondary.label}
            </a>
            <a href={to(nav.primary)} className={`${primaryButton} min-h-[42px] px-[18px] text-[14px]`}>
              {nav.primary.label}
            </a>
          </div>
        </nav>
      )}
    </header>
  );
}
