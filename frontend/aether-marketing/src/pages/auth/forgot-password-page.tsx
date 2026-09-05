import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import { APP_LOGIN_PATH, buildAppHandoffUrl, EMAIL_LABEL } from '@aether-marketing/lib/handoff';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { AuthCard, AUTH_PAGE_META, TextField, emailError } from '@aether-marketing/pages/auth/auth-ui';

/** There is no password-reset endpoint on this public site, so the recovery
 * handoff truthfully points back at the Aether application sign-in — a reset
 * stays scoped to the origin that holds the user's credentials. Tests inject
 * `navigate` so a submit never fires a real navigation. */
function defaultNavigate(url: string): void {
  window.location.assign(url);
}

export function ForgotPasswordPage({
  navigate,
}: {
  readonly navigate?: (url: string) => void;
}) {
  usePageMeta({
    title: 'Reset your password — Aether by Olympus Labs',
    description: 'Reset your Aether workspace password.',
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
      // Recovery is handled from the application sign-in: entering the email
      // carries the prefill to the environment that holds the credentials.
      go(buildAppHandoffUrl(APP_LOGIN_PATH, { email: value }));
    }
  }

  return (
    <AuthCard
      eyebrow="Password recovery"
      title="Reset your password"
      lead="Password recovery is handled inside the Aether application, so a reset stays scoped to the environment that holds your credentials. Enter your workspace email to continue there."
      links={[
        { label: 'Return to sign in', to: '/login' },
        { label: 'Back to the Aether home page', to: '/' },
      ]}
      note="The public site does not send password-reset email — recovery begins where your credentials live."
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
          Continue to recovery
        </Button>
      </form>
    </AuthCard>
  );
}
