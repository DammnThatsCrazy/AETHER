import { getEnvironment } from '@shiki/lib/env';

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  readonly level: LogLevel;
  readonly message: string;
  readonly timestamp: string;
  readonly environment: string;
  readonly data?: unknown;
}

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
};

function getMinLevel(): number {
  const env = getEnvironment();
  if (env === 'production') return LOG_LEVELS.warn;
  if (env === 'staging') return LOG_LEVELS.info;
  return LOG_LEVELS.debug;
}

function emit(level: LogLevel, message: string, data?: unknown): void {
  if (LOG_LEVELS[level] < getMinLevel()) return;

  const entry: LogEntry = {
    level,
    message,
    timestamp: new Date().toISOString(),
    environment: getEnvironment(),
    data,
  };

  switch (level) {
    case 'debug':
      console.debug(`[SHIKI] ${entry.message}`, data ?? '');
      break;
    case 'info':
      console.info(`[SHIKI] ${entry.message}`, data ?? '');
      break;
    case 'warn':
      console.warn(`[SHIKI] ${entry.message}`, data ?? '');
      break;
    case 'error':
      console.error(`[SHIKI] ${entry.message}`, data ?? '');
      break;
  }

  // Hook for external error reporting (Sentry, DataDog, etc.)
  if (level === 'error' && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('shiki:error', { detail: entry }));
  }
}

export const log = {
  debug: (message: string, data?: unknown) => emit('debug', message, data),
  info: (message: string, data?: unknown) => emit('info', message, data),
  warn: (message: string, data?: unknown) => emit('warn', message, data),
  error: (message: string, data?: unknown) => emit('error', message, data),
};
