import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { ThemeProvider } from '@aether/ui';
import { AuthProvider } from '@aether-app/features/auth';
import { AetherAuth0Provider } from '@aether-app/lib/auth/auth0-provider';
import { ErrorBoundary } from './error-boundary';

interface ProvidersProps {
  readonly children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      <AetherAuth0Provider>
        <BrowserRouter>
          <ThemeProvider storageKey="aether-theme">
            <AuthProvider>
              {children}
            </AuthProvider>
          </ThemeProvider>
        </BrowserRouter>
      </AetherAuth0Provider>
    </ErrorBoundary>
  );
}
