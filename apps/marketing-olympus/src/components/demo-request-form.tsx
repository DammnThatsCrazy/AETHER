import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import { SelectField, TextareaField, TextField } from '@olympus-marketing/components/form-fields';
import { emailFieldError, requiredError } from '@olympus-marketing/lib/validation';

const STORAGE_KEY = 'olympus.demo-requests.v1';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

const USE_CASE_OPTIONS: readonly { readonly value: string; readonly label: string }[] = [
  { value: 'customer-intelligence', label: 'Customer Intelligence' },
  { value: 'campaign-attribution', label: 'Campaign Attribution' },
  { value: 'developer-analytics', label: 'Developer Analytics' },
  { value: 'other', label: 'Other' },
];

export interface DemoRequest {
  readonly name: string;
  readonly email: string;
  readonly company: string;
  readonly useCase: string;
  readonly message: string;
  readonly submittedAt: string;
}

/** Read every request saved in this browser. Never throws. */
export function readDemoRequests(): readonly DemoRequest[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DemoRequest[]) : [];
  } catch {
    return [];
  }
}

function saveDemoRequest(request: DemoRequest): void {
  try {
    const next = [...readDemoRequests(), request];
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Best effort only — a full or blocked store must never break the form.
  }
}

async function submitLead(request: DemoRequest): Promise<void> {
  if (!API_BASE) return;
  try {
    await fetch(`${API_BASE}/v1/contact/lead`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lead_type: 'demo-request',
        email: request.email,
        name: request.name,
        company: request.company,
        use_case: request.useCase,
        message: request.message,
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
  readonly company?: string | undefined;
  readonly useCase?: string | undefined;
}

export function DemoRequestForm({ className }: { readonly className?: string }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [useCase, setUseCase] = useState('');
  const [message, setMessage] = useState('');
  const [errors, setErrors] = useState<FieldErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const trimmedName = name.trim();
    const trimmedEmail = email.trim();
    const trimmedCompany = company.trim();

    const nextErrors: FieldErrors = {
      name: requiredError(trimmedName, 'Enter your name.'),
      email: emailFieldError(trimmedEmail, 'Enter your work email.', 'Enter a valid email address.'),
      company: requiredError(trimmedCompany, 'Enter your company.'),
      useCase: requiredError(useCase, 'Choose the closest use case.'),
    };
    setErrors(nextErrors);
    if (Object.values(nextErrors).some((value) => value !== undefined)) return;

    const entry: DemoRequest = {
      name: trimmedName,
      email: trimmedEmail,
      company: trimmedCompany,
      useCase,
      message: message.trim(),
      submittedAt: new Date().toISOString(),
    };
    saveDemoRequest(entry);
    setSubmitting(true);
    submitLead(entry).finally(() => {
      setSubmitting(false);
      setSubmitted(true);
    });
  }

  if (submitted) {
    return (
      <div role="status" className={className ?? 'rounded-lg border border-border-default bg-surface-raised p-6'}>
        <p className="text-base font-semibold text-text-primary">We’ll be in touch.</p>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          We've received your request. Our team will review it and reach out to schedule a demo — typically within 2
          business days.
        </p>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={handleSubmit} className={className ?? 'flex flex-col gap-5'}>
      <div className="grid gap-5 sm:grid-cols-2">
        <TextField
          id="demo-name"
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
          id="demo-email"
          label="Work email"
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
          id="demo-company"
          label="Company"
          type="text"
          autoComplete="organization"
          required
          value={company}
          onValueChange={(value) => {
            setCompany(value);
            setErrors((current) => ({ ...current, company: undefined }));
          }}
          error={errors.company}
        />
        <SelectField
          id="demo-use-case"
          label="Use case"
          required
          value={useCase}
          onValueChange={(value) => {
            setUseCase(value);
            setErrors((current) => ({ ...current, useCase: undefined }));
          }}
          options={USE_CASE_OPTIONS}
          placeholder="Select a use case"
          error={errors.useCase}
        />
      </div>
      <TextareaField
        id="demo-message"
        label="What are you hoping to solve?"
        optional
        rows={4}
        placeholder="A sentence or two of context helps us route your request."
        value={message}
        onValueChange={setMessage}
      />
      <Button type="submit" variant="primary" size="lg" disabled={submitting}>
        {submitting ? 'Submitting…' : 'Request a demo'}
      </Button>
      <p className="text-xs leading-relaxed text-text-muted">
        We'll reach out to schedule a walkthrough — typically within 2 business days.
      </p>
    </form>
  );
}
