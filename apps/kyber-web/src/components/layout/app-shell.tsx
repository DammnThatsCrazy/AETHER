import { Sidebar } from './sidebar';
import { TopBar } from './top-bar';
import type { ReactNode } from 'react';
import { DemoTenantBanner } from '@aether/ui';
import { useKyberScope } from '@kyber/features/auth/hooks';
import { useDemoSeedStatus } from '@kyber/features/demo-seed/use-demo-seed-status';

interface AppShellProps {
  readonly children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { tenantId } = useKyberScope();
  const demoSeed = useDemoSeedStatus(tenantId);
  const showDemoBanner = demoSeed.data?.seeded === true && demoSeed.data.is_demo_tenant === true;

  return (
    <div className="flex h-screen overflow-hidden bg-surface-base">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        {showDemoBanner && (
          <DemoTenantBanner
            tenantName={demoSeed.data?.tenant_name}
            datasetVersion={demoSeed.data?.dataset_version}
          />
        )}
        <main className="flex-1 overflow-auto p-4">
          {children}
        </main>
      </div>
    </div>
  );
}
