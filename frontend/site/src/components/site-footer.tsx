import { useSite } from '@site/site/site-context';
import { FOOTER_COLUMNS } from '@site/site/navigation';

export function SiteFooter() {
  const { href } = useSite();
  return (
    <footer className="border-t border-line bg-stone-100 font-sans">
      <div className="mx-auto max-w-page px-6 pb-7 pt-12">
        <div className="grid gap-8 [grid-template-columns:repeat(auto-fit,minmax(160px,1fr))]">
          <div className="flex min-w-[200px] flex-col gap-3.5">
            <div className="flex items-center gap-3.5">
              <span className="flex items-center gap-[7px]">
                <img src="/logo-olympus-arch.svg" alt="" className="h-[15px] w-[15px]" />
                <span className="text-[14px] font-medium text-ink">Olympus Labs</span>
              </span>
              <span aria-hidden="true" className="h-3.5 w-px bg-line" />
              <span className="flex items-center gap-1.5">
                <img src="/logo-aether-layers.svg" alt="" className="h-[17px] w-[17px]" />
                <span className="text-[14px] font-medium text-ink">Aether</span>
              </span>
            </div>
            <p className="m-0 max-w-[260px] text-body-sm text-slate">
              Olympus Labs builds governed intelligence infrastructure. Aether is its customer-facing connection and
              relationship intelligence platform.
            </p>
          </div>
          {FOOTER_COLUMNS.map((column) => (
            <nav key={column.title} aria-label={column.title} className="flex flex-col gap-2.5">
              <span className="text-label uppercase text-slate">{column.title}</span>
              {column.links.map((l) => (
                <a
                  key={l.label}
                  href={href(l.site, l.path)}
                  className="text-body-sm leading-normal text-ink no-underline transition-colors duration-120 ease-site hover:text-cobalt"
                >
                  {l.label}
                </a>
              ))}
            </nav>
          ))}
        </div>
        <div className="mt-10 flex flex-wrap justify-between gap-3 border-t border-line pt-5 text-caption text-slate">
          <span>© 2026 Olympus Labs. All rights reserved.</span>
          <span className="flex gap-4 font-mono">
            <a href={href('aether', '/status')} className="text-slate no-underline">
              status.olympuslabsml.com
            </a>
            <span className="inline-flex items-center gap-1.5">
              <img src="/logo-aether-layers.svg" alt="" className="h-3.5 w-3.5" />
              Aether by
              <img src="/logo-olympus-arch.svg" alt="" className="h-[13px] w-[13px]" />
              Olympus Labs
            </span>
          </span>
        </div>
      </div>
    </footer>
  );
}
