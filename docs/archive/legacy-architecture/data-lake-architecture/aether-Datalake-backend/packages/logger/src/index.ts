export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'fatal';

export interface LogContext {
  service?: string;
  requestId?: string;
  projectId?: string;
  traceId?: string;
  [key: string]: unknown;
}

interface LogEntry {
  level: LogLevel;
  message: string;
  timestamp: string;
  service: string;
  context?: LogContext;
  error?: { message: string; stack?: string; code?: string };
  duration_ms?: number;
  [key: string]: unknown;
}

const LOG_LEVELS: Record<LogLevel, number> = {
  debug: 10,
  info: 20,
  warn: 30,
  error: 40,
  fatal: 50,
};

export class Logger {
  private service: string;
  private level: LogLevel;
  private context: LogContext;

  constructor(service: string, level: LogLevel = 'info', context: LogContext = {}) {
    this.service = service;
    this.level = level;
    this.context = context;
  }

  child(context: LogContext): Logger {
    return new Logger(this.service, this.level, { ...this.context, ...context });
  }

  debug(message: string, meta?: Record<string, unknown>): void {
    this.log('debug', message, meta);
  }

  info(message: string, meta?: Record<string, unknown>): void {
    this.log('info', message, meta);
  }

  warn(message: string, meta?: Record<string, unknown>): void {
    this.log('warn', message, meta);
  }

  error(message: string, error?: Error | unknown, meta?: Record<string, unknown>): void {
    const errorObj = error instanceof Error
      ? { message: error.message, stack: error.stack, code: (error as any).code }
      : error
        ? { message: String(error) }
        : undefined;

    this.log('error', message, { ...meta, error: errorObj });
  }

  fatal(message: string, error?: Error | unknown, meta?: Record<string, unknown>): void {
    const errorObj = error instanceof Error
      ? { message: error.message, stack: error.stack, code: (error as any).code }
      : undefined;

    this.log('fatal', message, { ...meta, error: errorObj });
  }

  private log(level: LogLevel, message: string, meta?: Record<string, unknown>): void {
    if (LOG_LEVELS[level] < LOG_LEVELS[this.level]) return;

    const entry: LogEntry = {
      level,
      message,
      timestamp: new Date().toISOString(),
      service: this.service,
      context: Object.keys(this.context).length > 0 ? this.context : undefined,
      ...meta,
    };

    const output = JSON.stringify(entry);

    if (level === 'error' || level === 'fatal') {
      process.stderr.write(output + '\n');
    } else {
      process.stdout.write(output + '\n');
    }
  }
}

export function createLogger(service: string, level?: LogLevel): Logger {
  return new Logger(
    service,
    level ?? (process.env.LOG_LEVEL as LogLevel) ?? 'info',
  );
}
