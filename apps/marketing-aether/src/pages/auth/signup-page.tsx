import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import {
  EMAIL_LABEL,
  NAME_LABEL,
} from '@aether-marketing/lib/handoff';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { AuthCard, AUTH_PAGE_META, TextField, emailError } from '@aether-marketing/pages/auth/auth-ui';

const STORAGE_KEY = 'aether.marketing.signup.v1';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

function saveSignup(name: string, email: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ name, email, ts: Date.now() }));
  } catch {
    // Best effort — a full or blocked store must never break the form.
  }
}

async function submitLead(name: string, email: string): Promise<void> {
  if (!API_BASE) return;
  try {
    await fetch(`${API_BASE}/v1/contact/lead`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lead_type: 'signup', name, email, source: 'aether-marketing' }),
    });
  } catch {
    // Best effort — localStorage is the local fallback.
  }
}

export function SignupPage({
  navigate: _navigate,
}: {
  readonly navigate?: (url: string) => void;
}) {
  usePageMeta({
    title: 'Create a workspace — Aether by Olympus Labs',
    description: 'Aether is not yet generally available. Join the waitlist and we will notify you when early access opens.',
    ...AUTH_PAGE_META,
  });

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [nameProblem, setNameProblem] = useState<string | undefined>(undefined);
  const [emailProblem, setEmailProblem] = useState<string | undefined>(undefined);
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const nameValue = name.trim();
    const emailValue = email.trim();

    const nameError = nameValue.length === 0 ? 'Enter your name to get started.' : undefined;
    const emailErrorText = emailError(emailValue);

    setNameProblem(nameError);
    setEmailProblem(emailErrorText);

    if (nameError === undefined && emailErrorText === undefined) {
      saveSignup(nameValue, emailValue);
      setSubmitting(true);
      submitLead(nameValue, emailValue).finally(() => {
        setSubmitting(false);
        setSubmitted(true);
      });
    }
  }

  if (submitted) {
    return (
      <AuthCard
        eyebrow="You're on the list"
        title="We'll be in touch"
        lead="Aether is preparing for a closed alpha. We saved your details and will notify you when early access opens."
        links={[{ label: 'Back to the home page', to: '/' }]}
        note=""
      >
        <div className="mt-8 rounded-md border border-accent/30 bg-accent/5 p-5">
          <p className="text-sm font-medium text-text-primary">What happens next?</p>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            We are onboarding early partners in small cohorts. When your cohort opens, you will
            receive an invitation with workspace provisioning, SSO setup, and your first connector
            walkthrough.
          </p>
        </div>
      </AuthCard>
    );
  }

  return (
    <AuthCard
      eyebrow="Start building"
      title="Create a workspace"
      lead="Aether is not yet generally available. Join the waitlist and we will notify you when early access opens."
      links={[{ label: 'Already have an account? Sign in', to: '/login' }]}
      note="Workspace provisioning, invites, and billing will happen in the Aether application when Aether is generally available."
    >
      <form noValidate onSubmit={handleSubmit} className="mt-8 flex flex-col gap-5">
        <TextField
          id="name"
          label={NAME_LABEL}
          type="text"
          autoComplete="name"
          required
          value={name}
          onValueChange={(value) => {
            setName(value);
            setNameProblem(undefined);
          }}
          error={nameProblem}
        />
        <TextField
          id="email"
          label={EMAIL_LABEL}
          type="email"
          autoComplete="email"
          required
          value={email}
          onValueChange={(value) => {
            setEmail(value);
            setEmailProblem(undefined);
          }}
          error={emailProblem}
        />
        <Button type="submit" variant="primary" size="lg" className="w-full" disabled={submitting}>
          {submitting ? 'Submitting…' : 'Join the waitlist'}
        </Button>
      </form>
    </AuthCard>
  );
}
