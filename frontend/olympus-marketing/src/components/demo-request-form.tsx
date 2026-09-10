import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import { SelectField, TextareaField, TextField } from '@olympus-marketing/components/form-fields';
import { emailFieldError, requiredError } from '@olympus-marketing/lib/validation';

/**
 * Demo-request capture for Olympus Labs. Same honest-storage contract as
 * `waitlist-form.tsx`: there is no scheduling or CRM backend wired into this
 * build, so a request is saved to `localStorage` in the visitor's own browser
 * and the success state says so plainly instead of implying a call is booked.
 */

const STORAGE_KEY = 'olympus.demo-requests.v1';

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

    saveDemoRequest({
      name: trimmedName,
      email: trimmedEmail,
      company: trimmedCompany,
      useCase,
      message: message.trim(),
      submittedAt: new Date().toISOString(),
    });
    setSubmitted(true);
  }

  if (submitted) {
    return (
      <div role="status" className={className ?? 'rounded-lg border border-border-default bg-surface-raised p-6'}>
        <p className="text-base font-semibold text-text-primary">We’ll be in touch.</p>
        <p className="mt-2 max-w-md text-sm leading-relaxed text-text-secondary">
          We saved your request in this browser. Olympus Labs has no scheduling backend wired into this build, so no
          call is booked yet — reach us directly through the contact channels on this page if you need a faster
          response.
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
      <Button type="submit" variant="primary" size="lg">
        Request a demo
      </Button>
      <p className="text-xs leading-relaxed text-text-muted">
        Saved in this browser only. Olympus Labs has no scheduling backend configured for this build, so nothing is
        sent to a server.
      </p>
    </form>
  );
}
