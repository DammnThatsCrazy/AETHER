import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import { SelectField, TextField } from '@olympus-marketing/components/form-fields';
import { emailFieldError, requiredError } from '@olympus-marketing/lib/validation';

const STORAGE_KEY = 'olympus.waitlist.entries.v1';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

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

async function submitLead(entry: WaitlistEntry): Promise<void> {
  if (!API_BASE) return;
  try {
    await fetch(`${API_BASE}/v1/contact/lead`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lead_type: 'waitlist',
        email: entry.email,
        name: entry.name,
        company: entry.company,
        role: entry.role,
        source: 'olympus-marketing',
      }),
    });
  } catch {
    // Best effort — localStorage is the local fallback.
  }
}

interface FieldErrors {
  readonly name?: string | undefined;
  readonly email?: string | undefined;
}

export function WaitlistForm({ className }: { readonly className?: string }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [role, setRole] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submittedEmail, setSubmittedEmail] = useState<string | undefined>(undefined);
  const [submitting, setSubmitting] = useState(false);

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

    const entry: WaitlistEntry = {
      name: trimmedName,
      email: trimmedEmail,
      company: company.trim(),
      role,
      submittedAt: new Date().toISOString(),
    };
    saveWaitlistEntry(entry);
    setSubmitting(true);
    submitLead(entry).finally(() => {
      setSubmitting(false);
      setSubmittedEmail(trimmedEmail);
    });
  }

  if (submittedEmail !== undefined) {
    return (
      <div role="status" className={className ?? 'rounded-lg border border-border-default bg-surface-raised p-6'}>
        <p className="text-base font-semibold text-text-primary">You're on the list.</p>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          We saved {submittedEmail}. Aether is coming soon — we're preparing for a closed alpha and will
          notify you when early access opens.
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
      <Button type="submit" variant="primary" size="lg" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Join the waitlist'}
      </Button>
      <p className="text-xs leading-relaxed text-text-muted">
        Aether is coming soon. Join the waitlist and we'll notify you when the closed alpha opens.
      </p>
    </form>
  );
}
