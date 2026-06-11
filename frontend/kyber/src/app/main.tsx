import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Providers } from './providers';
import { AppRouter } from './router';
import { log } from '@kyber/lib/logging';
import { getEnvironment, getRuntimeMode, getStartupValidationSummary, isLocalMocked } from '@kyber/lib/env';
import '@kyber/styles/index.css';

log.info(`[KYBER] Starting — env=${getEnvironment()} mode=${getRuntimeMode()}`);

const validation = getStartupValidationSummary();
if (!validation.ok) {
  log.warn('[KYBER] Environment validation issues:', { results: validation.results.filter(r => !r.valid) });
}

async function bootstrap() {
  if (isLocalMocked()) {
    try {
      const { worker } = await import('../mocks/browser');
      // Timeout guards against service worker registration hanging in headless/CI environments.
      await Promise.race([
        worker.start({ onUnhandledRequest: 'bypass' }),
        new Promise<void>((_, reject) =>
          setTimeout(() => reject(new Error('MSW startup timeout')), 5000),
        ),
      ]);
      log.info('[KYBER] MSW mock service worker started');
    } catch (e) {
      log.warn('[KYBER] MSW startup skipped (rendering without mocks):', e);
    }
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
}

void bootstrap();
