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
      <SiteHeader active={active} />
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooter />
    </div>
  );
}
