import { useState, type FormEvent } from 'react';
import { Button } from '@aether/ui';
import {
  APP_SIGNUP_PATH,
  buildAppHandoffUrl,
  EMAIL_LABEL,
  NAME_LABEL,
} from '@aether-marketing/lib/handoff';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { AuthCard, AUTH_PAGE_META, TextField, emailError } from '@aether-marketing/pages/auth/auth-ui';

/** Full-page document navigation is the correct handoff: the tenant workspace
 * is provisioned on the application origin, so the public page moves the
 * browser there instead of pretending to create a workspace in-place. Tests
 * inject `navigate` so a submit never fires a real navigation. */
function defaultNavigate(url: string): void {
  window.location.assign(url);
}

export function SignupPage({
  navigate,
}: {
  readonly navigate?: (url: string) => void;
}) {
  usePageMeta({
    title: 'Create a workspace — Aether by Olympus Labs',
    description: 'Aether is not yet generally available. When it opens to customers, create your Aether workspace from this public site.',
    ...AUTH_PAGE_META,
  });

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [nameProblem, setNameProblem] = useState<string | undefined>(undefined);
  const [emailProblem, setEmailProblem] = useState<string | undefined>(undefined);

  const go = navigate ?? defaultNavigate;

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const nameValue = name.trim();
    const emailValue = email.trim();

    const nameError = nameValue.length === 0 ? 'Enter your name to get started.' : undefined;
    const emailErrorText = emailError(emailValue);

    setNameProblem(nameError);
    setEmailProblem(emailErrorText);

    if (nameError === undefined && emailErrorText === undefined) {
      go(buildAppHandoffUrl(APP_SIGNUP_PATH, { name: nameValue, email: emailValue }));
    }
  }

  return (
    <AuthCard
      eyebrow="Start building"
      title="Create a workspace"
      lead="Aether is not yet generally available. When it opens to customers, your workspace is created in the Aether application — tell us who is starting it and we will take you there."
      links={[{ label: 'Already have an account? Sign in', to: '/login' }]}
      note="Workspace provisioning, invites, and billing will happen in the Aether application when Aether is generally available. Submitting this form hands your details to the application; it does not create an account today."
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
        <Button type="submit" variant="primary" size="lg" className="w-full">
          Continue to sign-up
        </Button>
      </form>
    </AuthCard>
  );
}
