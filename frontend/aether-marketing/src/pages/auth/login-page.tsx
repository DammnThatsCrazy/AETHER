import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import {
  APP_LOGIN_PATH,
  buildAppHandoffUrl,
  EMAIL_LABEL,
} from '@aether-marketing/lib/handoff';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { AuthCard, AUTH_PAGE_META, TextField, emailError } from '@aether-marketing/pages/auth/auth-ui';

/** Full-page document navigation is the correct handoff: the tenant session
 * lives on the application origin, so the public page moves the browser there
 * instead of pretending to authenticate in-place. Tests inject `navigate` so a
 * submit never fires a real navigation. */
function defaultNavigate(url: string): void {
  window.location.assign(url);
}

export function LoginPage({
  navigate,
}: {
  readonly navigate?: (url: string) => void;
}) {
  usePageMeta({
    title: 'Sign in — Aether by Olympus Labs',
    description: 'Sign in to your Aether workspace.',
    ...AUTH_PAGE_META,
  });

  const [email, setEmail] = useState('');
  const [emailProblem, setEmailProblem] = useState<string | undefined>(undefined);

  const go = navigate ?? defaultNavigate;

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const value = email.trim();
    const problem = emailError(value);
    setEmailProblem(problem);
    if (problem === undefined) {
      go(buildAppHandoffUrl(APP_LOGIN_PATH, { email: value }));
    }
  }

  return (
    <AuthCard
      eyebrow="Sign in"
      title="Sign in to your workspace"
      lead="Your workspace session lives in the Aether application. Enter your workspace email to continue there."
      links={[
        { label: 'Create an account', to: '/signup' },
        { label: 'Forgot your password?', to: '/forgot-password' },
      ]}
      note="Aether never stores your email or session on this public site — sign-in completes on the application origin."
    >
      <form noValidate onSubmit={handleSubmit} className="mt-8 flex flex-col gap-5">
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
        <Button type="submit" variant="primary" size="lg" className="w-full">
          Continue to sign-in
        </Button>
      </form>
    </AuthCard>
  );
}
