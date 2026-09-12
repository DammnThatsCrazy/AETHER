import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@aether/ui';
import { Eyebrow } from '@aether-marketing/components/marketing-section';
import { emailError, TextField } from '@aether-marketing/pages/auth/auth-ui';

/**
 * Reusable early-access capture, embeddable on any marketing page. Aether
 * already has a real workspace hand-off at `/signup`, so this section is
 * deliberately secondary to it: the primary path for a visitor ready now is
 * still the real sign-up flow, and this form is for a visitor who wants to be
 * notified when the closed alpha opens.
 */

const STORAGE_KEY = 'aether.marketing.early-access.v1';

function saveEmail(email: string): void {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = raw === null ? [] : JSON.parse(raw);
    const list: string[] = Array.isArray(parsed) ? (parsed as string[]) : [];
    if (!list.includes(email)) list.push(email);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // Best effort only — a full or blocked store must never break the form.
  }
}

export interface WaitlistSectionProps {
  /** 'waitlist' reads "Join the waitlist"; 'early-access' reads "Request early access". */
  readonly variant?: 'waitlist' | 'early-access';
  readonly eyebrow?: string;
  readonly title: string;
  readonly body: string;
  readonly id?: string;
  readonly className?: string;
}

export function WaitlistSection({
  variant = 'waitlist',
  eyebrow,
  title,
  body,
  id,
  className,
}: WaitlistSectionProps) {
  const fieldId = `${id ?? 'waitlist'}-email`;
  const [email, setEmail] = useState('');
  const [error, setError] = useState<string | undefined>(undefined);
  const [submittedEmail, setSubmittedEmail] = useState<string | undefined>(undefined);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmed = email.trim();
    const problem = emailError(trimmed);
    setError(problem);
    if (problem !== undefined) return;
    saveEmail(trimmed);
    setSubmittedEmail(trimmed);
  }

  const actionLabel = variant === 'waitlist' ? 'Join the waitlist' : 'Request early access';

  return (
    <section id={id} aria-label={title} className={className ?? 'border-b border-border-default bg-surface-sunken'}>
      <div className="mkt-container py-16 md:py-20">
        <div className="grid gap-8 lg:grid-cols-[1.1fr_1fr] lg:items-center">
          <div>
            {eyebrow !== undefined && <Eyebrow>{eyebrow}</Eyebrow>}
            <h2 className="mkt-h2 mt-3">{title}</h2>
            <p className="mkt-body mt-4 max-w-xl text-text-secondary">{body}</p>
            <p className="mt-4 text-sm text-text-secondary">
              Ready to start now?{' '}
              <Link to="/signup" className="text-accent underline underline-offset-2 mkt-motion-color hover:text-text-primary">
                Create a workspace
              </Link>{' '}
              goes straight into the real sign-up flow.
            </p>
          </div>
          <div className="rounded-md border border-border-default bg-surface-base p-6">
            {submittedEmail !== undefined ? (
              <div role="status">
                <p className="text-base font-semibold text-text-primary">You’re on the list.</p>
                <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                  We saved {submittedEmail}. Aether is coming soon — we’re preparing for a closed alpha and will
                  notify you when early access opens.
                </p>
              </div>
            ) : (
              <form noValidate onSubmit={handleSubmit} className="flex flex-col gap-4">
                <TextField
                  id={fieldId}
                  label="Work email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onValueChange={(value) => {
                    setEmail(value);
                    setError(undefined);
                  }}
                  error={error}
                />
                <Button type="submit" variant="primary" size="lg">
                  {actionLabel}
                </Button>
                <p className="text-xs leading-relaxed text-text-muted">
                  Aether is coming soon. We'll notify you when the closed alpha opens.
                </p>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
