import { MockModeBanner } from '@aether/ui';
import { Sidebar } from './sidebar';
import { TopBar } from './top-bar';
import { getRuntimeMode, isEnvExplicit } from '@kyber/lib/env';
import type { ReactNode } from 'react';

interface AppShellProps {
  readonly children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex h-screen overflow-hidden bg-surface-base">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar />
        {/* Honesty guard: never let in-browser mock data read as live. */}
        <MockModeBanner
          mode={getRuntimeMode()}
          envVarName="VITE_KYBER_ENV"
          envExplicit={isEnvExplicit()}
        />
        <main className="flex-1 overflow-auto p-4">
          {children}
        </main>
      </div>
    </div>
  );
}
