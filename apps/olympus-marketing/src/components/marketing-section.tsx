import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { cn } from '@aether/ui';

export function Eyebrow({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return <p className={cn('mkt-eyebrow', className)}>{children}</p>;
}

export interface CtaLink {
  readonly label: string;
  readonly to: string;
  readonly external?: boolean;
}

export function CtaBand({
  title,
  body,
  primary,
  secondary,
}: {
  readonly title: string;
  readonly body: string;
  readonly primary: CtaLink;
  readonly secondary?: CtaLink;
}) {
  return (
    <section aria-label="Next step" className="border-t border-border-default bg-surface-raised">
      <div className="mkt-container py-16 md:py-24">
        <div className="mkt-measure">
          <h2 className="mkt-h2">{title}</h2>
          <p className="mkt-lead mt-4">{body}</p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            {primary.external ? (
              <Button asChild variant="primary" size="lg">
                <a href={primary.to} target="_blank" rel="noreferrer">
                  {primary.label}
                </a>
              </Button>
            ) : (
              <Button asChild variant="primary" size="lg">
                <Link to={primary.to}>{primary.label}</Link>
              </Button>
            )}
            {secondary !== undefined &&
              (secondary.external ? (
                <Button asChild variant="secondary" size="lg">
                  <a href={secondary.to} target="_blank" rel="noreferrer">
                    {secondary.label}
                  </a>
                </Button>
              ) : (
                <Button asChild variant="secondary" size="lg">
                  <Link to={secondary.to}>{secondary.label}</Link>
                </Button>
              ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function PageHero({
  eyebrow,
  title,
  lead,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly lead: string;
}) {
  return (
    <section className="border-b border-border-default">
      <div className="mkt-container py-20 md:py-28">
        <Eyebrow>{eyebrow}</Eyebrow>
        <h1 className="mkt-display mt-4 max-w-4xl">{title}</h1>
        <p className="mkt-lead mt-6 max-w-2xl">{lead}</p>
      </div>
    </section>
  );
}
