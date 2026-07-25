import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Providers } from './providers';
import { AppRouter } from './router';
import { log } from '@aether-app/lib/logging';
import { getEnvironment, getStartupValidationSummary } from '@aether-app/lib/env';
import { cleanupLegacyMockWorker } from '@aether-app/lib/browser/legacy-mock-cleanup';
import '@aether-app/styles/index.css';

log.info(`[AETHER] Starting — env=${getEnvironment()} dataSource=backend`);

const validation = getStartupValidationSummary();
if (!validation.ok) {
  log.warn('[AETHER] Environment validation issues:', { results: validation.results.filter(r => !r.valid) });
}

async function bootstrap() {
  await cleanupLegacyMockWorker();

  const root = document.getElementById('root');
  if (!root) throw new Error('Root element not found');

  createRoot(root).render(
    <StrictMode>
      <Providers>
        <AppRouter />
      </Providers>
    </StrictMode>,
  );
}

void bootstrap();
