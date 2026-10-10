import { PageWrapper } from '@kyber/components/layout';
import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState } from '@aether/ui';
import { getEnvironment } from '@kyber/lib/env';

export function LabPage() {
  const environment = getEnvironment();

  return (
    <PageWrapper
      title="Lab"
      subtitle="Backend-backed operational diagnostics"
      actions={<Badge>{environment}</Badge>}
    >
      <Card>
        <CardHeader>
          <CardTitle>Runtime fixture tools removed</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            title="Lab data is unavailable"
            description="Browser-side scenario fixtures, replay simulation, sample responses, and fixture export are no longer part of the Kyber runtime. Use backend diagnostics and explicitly seeded backend demo data for operational inspection."
          />
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
