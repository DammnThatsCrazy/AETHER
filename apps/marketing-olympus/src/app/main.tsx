import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AppRouter } from './router';
import { ErrorBoundary } from './error-boundary';
import { analyticsFromEnv, initAnalytics } from '@olympus-marketing/lib/analytics';
import '@olympus-marketing/styles/index.css';

// Analytics is a no-op unless VITE_ANALYTICS_PROVIDER/VITE_ANALYTICS_PROPERTY_ID
// are explicitly set at build time (see src/lib/analytics.ts).
initAnalytics(analyticsFromEnv());

const rootEl = document.getElementById('root');
if (!rootEl) throw new Error('Root element not found');

createRoot(rootEl).render(
  <StrictMode>
    <BrowserRouter>
      <ErrorBoundary>
        <AppRouter />
      </ErrorBoundary>
    </BrowserRouter>
  </StrictMode>,
);
