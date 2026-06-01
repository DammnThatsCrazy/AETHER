import { Card, CardHeader, CardContent, Button, Badge } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { DecisionIntelligencePanel } from '@aether-app/components/decision-intelligence-panel';

export function HomePage() {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-surface-base p-8">
      <div className="max-w-2xl mx-auto space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-sans font-semibold text-text-primary">Aether</h1>
            <p className="text-text-secondary text-sm mt-1">Customer Portal</p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="success">Connected</Badge>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              Sign out
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader>
            <h2 className="text-text-primary font-medium">Welcome{user ? `, ${user.displayName}` : ''}</h2>
          </CardHeader>
          <CardContent>
            <p className="text-text-secondary text-sm">
              This is the Aether customer portal. Features will be added here as the product grows.
            </p>
          </CardContent>
        </Card>

        <DecisionIntelligencePanel />
      </div>
    </div>
  );
}
