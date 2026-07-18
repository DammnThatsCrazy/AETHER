import type { ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { AuthProvider } from '@kyber/features/auth';
import { NotificationProvider } from '@kyber/features/notifications';
import { ThemeProvider, TimeProvider } from '@aether/ui';
import { AetherAuth0Provider } from '@kyber/lib/auth/auth0-provider';
import { JourneyProvider } from '@kyber/features/journey';
import { ErrorBoundary } from './error-boundary';

interface ProvidersProps {
  readonly children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <ErrorBoundary>
      <AetherAuth0Provider>
        <BrowserRouter>
          <ThemeProvider storageKey="kyber-theme">
            <TimeProvider>
              <AuthProvider>
                <JourneyProvider>
                  <NotificationProvider>
                    {children}
                  </NotificationProvider>
                </JourneyProvider>
              </AuthProvider>
            </TimeProvider>
          </ThemeProvider>
        </BrowserRouter>
      </AetherAuth0Provider>
    </ErrorBoundary>
  );
}
