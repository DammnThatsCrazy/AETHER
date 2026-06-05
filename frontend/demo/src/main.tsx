import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { isLocalMocked } from './lib/env';
import './styles/index.css';

async function bootstrap() {
  if (isLocalMocked()) {
    const { worker } = await import('./mocks/browser');
    await worker.start({ onUnhandledRequest: 'bypass' });
  }
  const root = document.getElementById('root');
  if (!root) throw new Error('Root element not found');
  createRoot(root).render(<StrictMode><App /></StrictMode>);
}

void bootstrap();
