import { useAuth } from './auth-context';
import { isMockAuthAllowed } from '@shiki/lib/env';
import type { ShikiRole } from '@shiki/types';

const MOCK_ROLES: { role: ShikiRole; label: string; description: string }[] = [
  { role: 'shiki_executive_operator', label: 'Executive Operator', description: 'Broad read, approvals, interventions' },
  { role: 'shiki_engineering_command', label: 'Engineering Command', description: 'Full diagnostics, agent command, rollback' },
  { role: 'shiki_specialist_operator', label: 'Specialist Operator', description: 'Notes, assignments, limited approvals' },
  { role: 'shiki_observer', label: 'Observer', description: 'Read-only access' },
];

export function LoginPage() {
  const { login, switchMockUser, error } = useAuth();

  return (
    <div className="flex h-screen items-center justify-center bg-surface-base">
      <div className="w-full max-w-md space-y-6 p-8">
        <div className="text-center">
          <div className="font-mono text-3xl font-bold text-text-primary mb-1">SHIKI</div>
          <div className="text-text-secondary text-sm">Aether Command Surface</div>
        </div>

        {error && (
          <div className="shiki-card border-danger/50 text-danger text-sm">{error}</div>
        )}

        {isMockAuthAllowed() ? (
          <div className="space-y-3">
            <div className="text-text-secondary text-xs uppercase tracking-wider">Select Role (Local Mode)</div>
            {MOCK_ROLES.map(({ role, label, description }) => (
              <button
                key={role}
                onClick={() => switchMockUser(role)}
                className="w-full text-left shiki-card hover:border-accent/50 transition-colors cursor-pointer"
              >
                <div className="font-medium text-text-primary">{label}</div>
                <div className="text-text-secondary text-xs mt-1">{description}</div>
              </button>
            ))}
          </div>
        ) : (
          <button
            onClick={() => void login()}
            className="w-full rounded-md bg-accent px-4 py-3 text-text-inverse font-medium hover:bg-accent-hover transition-colors"
          >
            Sign in with SSO
          </button>
        )}
      </div>
    </div>
  );
}
