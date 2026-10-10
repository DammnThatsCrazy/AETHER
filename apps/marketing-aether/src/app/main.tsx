import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AppRouter } from '@aether-marketing/app/router';
import { ErrorBoundary } from '@aether-marketing/app/error-boundary';
import { analyticsFromEnv, initAnalytics } from '@aether-marketing/lib/analytics';
import '@aether-marketing/styles/index.css';

// Analytics is a no-op unless VITE_ANALYTICS_PROVIDER/VITE_ANALYTICS_PROPERTY_ID
// are explicitly set at build time (see src/lib/analytics.ts).
initAnalytics(analyticsFromEnv());

const root = document.getElementById('root');
if (root === null) {
  throw new Error('Aether marketing root element #root was not found.');
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AppRouter />
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
