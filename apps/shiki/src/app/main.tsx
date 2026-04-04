import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Providers } from './providers';
import { AppRouter } from './router';
import { log } from '@shiki/lib/logging';
import { getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import '@shiki/styles/index.css';

log.info(`[SHIKI] Starting — env=${getEnvironment()} mode=${getRuntimeMode()}`);

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

createRoot(root).render(
  <StrictMode>
    <Providers>
      <AppRouter />
    </Providers>
  </StrictMode>,
);
