import { useEffect, type ReactNode } from 'react';
import { SiteHeader } from './site-header';
import { SiteFooter } from './site-footer';

interface PageShellProps {
  title: string;
  /** Header nav label to mark as the current page. */
  active?: string;
  children: ReactNode;
}

/** Header + page + footer on the stone page surface, with the document title. */
export function PageShell({ title, active, children }: PageShellProps) {
  useEffect(() => {
    document.title = title;
  }, [title]);

  return (
    <div className="flex min-h-screen flex-col bg-stone-50 font-sans text-ink">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-control focus:bg-ink focus:px-3.5 focus:py-2 focus:text-body-sm focus:font-medium focus:text-stone-50"
      >
        Skip to content
      </a>
      <SiteHeader active={active} />
      <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
