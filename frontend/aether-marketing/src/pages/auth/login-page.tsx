import { Button } from '@aether/ui';
import { usePageMeta } from '@aether-marketing/lib/meta';
import { AuthCard, AUTH_PAGE_META } from '@aether-marketing/pages/auth/auth-ui';

export function LoginPage({
  navigate: _navigate,
}: {
  readonly navigate?: (url: string) => void;
}) {
  usePageMeta({
    title: 'Sign in — Aether by Olympus Labs',
    description: 'Aether is not yet generally available. Sign-in will open when early access begins.',
    ...AUTH_PAGE_META,
  });

  return (
    <AuthCard
      eyebrow="Sign in"
      title="Sign in to your workspace"
      lead="Aether is not yet generally available. When early access opens, you will sign in to your workspace from here."
      links={[
        { label: 'Join the waitlist', to: '/signup' },
      ]}
      note="Workspace sign-in, SSO, and session management will be available in the Aether application when Aether opens to customers."
    >
      <div className="mt-8 rounded-md border border-accent/30 bg-accent/5 p-5">
        <p className="text-sm font-medium text-text-primary">Coming soon</p>
        <p className="mt-2 text-sm leading-relaxed text-text-secondary">
          Aether is preparing for a closed alpha. Join the waitlist and we will notify you when
          workspace sign-in is available.
        </p>
        <p className="mt-4">
          <Button asChild variant="primary" size="md">
            <a href="/signup">Join the waitlist</a>
          </Button>
        </p>
      </div>
    </AuthCard>
  );
}
