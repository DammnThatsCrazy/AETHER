import { useNavigate } from 'react-router-dom';
import { Card, CardHeader, CardTitle, CardContent, Button } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { isFeatureEnabled } from '@aether-app/lib/featureFlags';
import { ModelSelectionPanel } from '@aether-app/features/model-selection';
import { DecisionIntelligencePanel } from '@aether-app/components/decision-intelligence-panel';
import { OutcomeLedgerPanel } from '@aether-app/components/outcome-ledger-panel';

// Pure navigation targets — no metrics, counts, or fabricated status. The panels
// below are the only data-bearing surfaces and each renders its own backend
// truth (loading / empty / error / populated) independently.
const NEXT_STEPS: ReadonlyArray<{ readonly to: string; readonly label: string; readonly hint: string }> = [
  { to: '/activation', label: 'Activation', hint: 'Finish setup and prove first value' },
  { to: '/me', label: 'Usage & plan', hint: 'Review measured usage and limits' },
  { to: '/settings', label: 'Settings', hint: 'Manage API keys and tenant profile' },
  { to: '/integrations', label: 'Integrations', hint: 'Connect and monitor data sources' },
];

export function HomePage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-surface-base p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-sans font-semibold text-text-primary">Aether workspace</h1>
            <p className="text-text-secondary text-sm mt-1">
              Welcome{user ? `, ${user.displayName}` : ''} — your customer intelligence home.
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => void logout()}>
            Sign out
          </Button>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Where to next</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {NEXT_STEPS.map(step => (
                <button
                  key={step.to}
                  onClick={() => void navigate(step.to)}
                  className="text-left rounded-lg border border-border-subtle bg-surface-raised p-3 transition-colors hover:border-accent/50"
                >
                  <p className="text-sm font-medium text-text-primary">{step.label}</p>
                  <p className="text-xs text-text-secondary mt-0.5">{step.hint}</p>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        <OutcomeLedgerPanel />
        <DecisionIntelligencePanel />

        {/* ADR-008 D9: tenant model-routing preference. Feature-flag gated (D8)
            — the surface appears only when the operator enables the harness. */}
        {isFeatureEnabled('enableModelHarness') && (
          <ModelSelectionPanel {...(user?.id ? { tenantId: user.id } : {})} />
        )}
      </div>
    </div>
  );
}
