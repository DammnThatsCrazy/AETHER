import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { getDemoEnv } from './lib/env';
import './styles/index.css';

async function bootstrap() {
  // Fail closed before anything renders: VITE_DEMO_ENV has no default.
  getDemoEnv();
  // Compared against the build-time literal rather than a helper call so the
  // branch is statically eliminated: outside `local-mocked` the MSW worker
  // chunk is never emitted, not merely never executed.
  if (import.meta.env.VITE_DEMO_ENV === 'local-mocked') {
    const { worker } = await import('./mocks/browser');
    await worker.start({ onUnhandledRequest: 'bypass' });
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('Root element not found');
  createRoot(root).render(<StrictMode><App /></StrictMode>);
}

void bootstrap();
