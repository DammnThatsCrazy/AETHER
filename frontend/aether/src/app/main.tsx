import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Providers } from './providers';
import { AppRouter } from './router';
import { log } from '@aether-app/lib/logging';
import { getEnvironment, getRuntimeMode, getStartupValidationSummary } from '@aether-app/lib/env';
import '@aether-app/styles/index.css';

log.info(`[AETHER] Starting — env=${getEnvironment()} mode=${getRuntimeMode()}`);

const validation = getStartupValidationSummary();
if (!validation.ok) {
  log.warn('[AETHER] Environment validation issues:', { results: validation.results.filter(r => !r.valid) });
}

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

createRoot(root).render(
  <StrictMode>
    <Providers>
      <AppRouter />
    </Providers>
  </StrictMode>,
);
