import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { getDemoConfig } from './lib/env';
import './styles/index.css';

function renderConfigurationError(root: HTMLElement, error: unknown): void {
  const message = error instanceof Error ? error.message : 'Invalid demo application configuration.';
  root.textContent = '';
  const main = document.createElement('main');
  main.setAttribute('role', 'alert');
  main.className = 'min-h-screen p-6';
  const heading = document.createElement('h1');
  heading.textContent = 'Demo application configuration error';
  const detail = document.createElement('p');
  detail.textContent = message;
  main.append(heading, detail);
  root.append(main);
}

const root = document.getElementById('root');
if (!root) throw new Error('Root element not found');

try {
  const config = getDemoConfig();
  createRoot(root).render(<StrictMode><App config={config} /></StrictMode>);
} catch (error) {
  renderConfigurationError(root, error);
}
