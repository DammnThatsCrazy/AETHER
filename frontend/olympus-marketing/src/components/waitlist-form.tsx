import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import { SelectField, TextField } from '@olympus-marketing/components/form-fields';
import { emailFieldError, requiredError } from '@olympus-marketing/lib/validation';

/**
 * Olympus Labs waitlist capture. There is no waitlist backend configured for
 * this build, so a submission is saved to `localStorage` in the visitor's own
 * browser and nowhere else — the success state says exactly that, in keeping
 * with the site's truthful-status discipline. A real intake channel can read
 * `readWaitlistEntries()` once one exists; nothing here pretends one already
 * does.
 */

const STORAGE_KEY = 'olympus.waitlist.entries.v1';

const ROLE_OPTIONS: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'founder-executive', label: 'Founder / executive' },
  { value: 'product', label: 'Product' },
  { value: 'engineering', label: 'Engineering' },
  { value: 'data-analytics', label: 'Data / analytics' },
  { value: 'marketing-growth', label: 'Marketing / growth' },
  { value: 'other', label: 'Other' },
];

export interface WaitlistEntry {
  readonly name: string;
  readonly email: string;
  readonly company: string;
  readonly role: string;
  readonly submittedAt: string;
}

/** Read every entry saved in this browser. Never throws — a blocked or absent
 * `localStorage` (private browsing, disabled storage) yields an empty list. */
export function readWaitlistEntries(): readonly WaitlistEntry[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as WaitlistEntry[]) : [];
  } catch {
    return [];
  }
}

function saveWaitlistEntry(entry: WaitlistEntry): void {
  try {
    const next = [...readWaitlistEntries(), entry];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Best effort only — a full or blocked store must never break the form.
  }
}

interface FieldErrors {
  readonly name?: string;
  readonly email?: string;
}

export function WaitlistForm({ className }: { readonly className?: string }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submittedEmail, setSubmittedEmail] = useState<string | undefined>(undefined);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedEmail = email.trim();

    const nextErrors: FieldErrors = {
      name: requiredError(trimmedName, 'Enter your name to join the waitlist.'),
      email: emailFieldError(
        trimmedEmail,
        'Enter your email to join the waitlist.',
        'Enter a valid email address.',
      ),
    };
    setErrors(nextErrors);
    if (nextErrors.name !== undefined || nextErrors.email !== undefined) return;

    saveWaitlistEntry({
      name: trimmedName,
      email: trimmedEmail,
      company: company.trim(),
      role,
      submittedAt: new Date().toISOString(),
    });
    setSubmittedEmail(trimmedEmail);
  }

  if (submittedEmail !== undefined) {
    return (
      <div role="status" className={className ?? 'rounded-lg border border-border-default bg-surface-raised p-6'}>
        <p className="text-base font-semibold text-text-primary">You’re on the list.</p>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          We saved {submittedEmail} in this browser. Olympus Labs has no live waitlist intake for this build, so
          nothing was sent anywhere — when workspace access opens, this is the detail we would reach out on.
        </p>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={handleSubmit} className={className ?? 'flex flex-col gap-5'}>
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          id="waitlist-name"
          label="Name"
          type="text"
          autoComplete="name"
          required
          value={name}
          onValueChange={(value) => {
            setName(value);
            setErrors((current) => ({ ...current, name: undefined }));
          }}
          error={errors.name}
        />
        <TextField
          id="waitlist-email"
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onValueChange={(value) => {
            setEmail(value);
            setErrors((current) => ({ ...current, email: undefined }));
          }}
          error={errors.email}
        />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          id="waitlist-company"
          label="Company"
          type="text"
          autoComplete="organization"
          optional
          value={company}
          onValueChange={setCompany}
        />
        <SelectField
          id="waitlist-role"
          label="Role"
          optional
          value={role}
          onValueChange={setRole}
          options={ROLE_OPTIONS}
          placeholder="Select a role"
        />
      </div>
      <Button type="submit" variant="primary" size="lg">
        Join the waitlist
      </Button>
      <p className="text-xs leading-relaxed text-text-muted">
        Saved in this browser only. Olympus Labs has no waitlist backend configured for this build, so nothing is
        sent to a server.
      </p>
    </form>
  );
}
