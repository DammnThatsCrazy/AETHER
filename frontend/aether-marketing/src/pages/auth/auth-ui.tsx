import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { cn } from '@aether/ui';
import { Eyebrow } from '@aether-marketing/components/marketing-section';
import { AETHER_MARKETING_URL } from '@aether-marketing/lib/env';

/**
 * Shared presentational pieces for the authentication threshold pages. The
 * pages stay body-only (AuthLayout wraps them) and each is a real form whose
 * submit builds an application-origin handoff — these helpers only keep the
 * quiet panel grammar and the accessible field wiring consistent across the
 * three routes.
 */

/** Authentication threshold routes are entry hand-offs to the protected Aether
 * application: they should not be indexed, and their canonical should resolve
 * to the marketing root rather than to a hand-off path that has no content of
 * its own. */
export const AUTH_PAGE_META = {
  robots: 'noindex,nofollow' as const,
  canonical: `${AETHER_MARKETING_URL}/`,
};

export interface AuthCardLink {
  readonly label: string;
  readonly to: string;
}

/** The calm centered card every threshold page renders inside the AuthLayout
 * main region. `children` is the route's real <form>. */
export function AuthCard({
  eyebrow,
  title,
  lead,
  children,
  links = [],
  note,
}: {
  readonly eyebrow: string;
  readonly title: string;
  readonly lead: string;
  readonly children: ReactNode;
  readonly links?: readonly AuthCardLink[] | undefined;
  readonly note: string;
}) {
  return (
    <section
      aria-label={eyebrow}
      className="w-full max-w-md rounded-lg border border-border-default bg-surface-base p-8 md:p-10"
    >
      <Eyebrow>{eyebrow}</Eyebrow>
      <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary">{title}</h1>
      <p className="mt-4 text-sm leading-relaxed text-text-secondary">{lead}</p>

      {children}

      {links.length > 0 && (
        <ul className="mt-6 flex flex-col items-center gap-3 text-sm">
          {links.map((link) => (
            <li key={link.to}>
              <Link
                to={link.to}
                className="text-accent underline underline-offset-2 mkt-motion-color hover:text-text-primary"
              >
                {link.label}
              </Link>
            </li>
          ))}
        </ul>
      )}

      <p className="mkt-body mt-8 border-t border-border-default pt-5 text-text-secondary">
        {note}
      </p>
    </section>
  );
}

interface TextFieldProps {
  readonly id: string;
  readonly label: string;
  readonly type?: 'text' | 'email';
  readonly autoComplete?: string;
  readonly required?: boolean;
  readonly value: string;
  readonly onValueChange: (value: string) => void;
  readonly error?: string | undefined;
}

/** A labeled input with honest inline validation: an error paragraph is wired
 * to the control via aria-invalid + aria-describedby so the failure is
 * programmatically discoverable. */
export function TextField({
  id,
  label,
  type = 'text',
  autoComplete,
  required = false,
  value,
  onValueChange,
  error,
}: TextFieldProps) {
  const errorId = `${id}-error`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-text-primary">
        {label}
      </label>
      <input
        id={id}
        name={id}
        type={type}
        autoComplete={autoComplete}
        required={required}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        aria-invalid={error !== undefined}
        {...(error !== undefined ? { 'aria-describedby': errorId } : {})}
        className={cn(
          'mt-2 w-full rounded-md border bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-1',
          error !== undefined
            ? 'border-danger focus:ring-danger'
            : 'border-border-default focus:ring-border-focus',
        )}
      />
      {error !== undefined && (
        <p id={errorId} role="alert" className="mt-1.5 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Required + shape validation for the work-email field shared by every
 * threshold form. Returns an error message, or undefined when the value is a
 * plausible email address. */
export function emailError(email: string): string | undefined {
  if (email.length === 0) {
    return 'Enter your work email to continue.';
  }
  if (!EMAIL_PATTERN.test(email)) {
    return 'Enter a valid work email address.';
  }
  return undefined;
}
