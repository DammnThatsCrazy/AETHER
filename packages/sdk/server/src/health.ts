// Server SDK health telemetry — tracks flush success/failure rates.

export interface SdkHealthSnapshot {
  eventsQueued: number;
  eventsDelivered: number;
  eventsFailed: number;
  flushErrors: number;
  lastFlushAt: string | null;
  lastErrorAt: string | null;
  lastError: string | null;
}

export class SdkHealthTracker {
  private eventsQueued = 0;
  private eventsDelivered = 0;
  private eventsFailed = 0;
  private flushErrors = 0;
  private lastFlushAt: string | null = null;
  private lastErrorAt: string | null = null;
  private lastError: string | null = null;

  recordQueued(n: number): void { this.eventsQueued += n; }
  recordDelivered(n: number): void { this.eventsDelivered += n; this.lastFlushAt = new Date().toISOString(); }
  recordFailed(n: number): void { this.eventsFailed += n; }
  recordFlushError(err: string): void {
    this.flushErrors++;
    this.lastErrorAt = new Date().toISOString();
    this.lastError = err;
  }

  snapshot(): SdkHealthSnapshot {
    return {
      eventsQueued: this.eventsQueued,
      eventsDelivered: this.eventsDelivered,
      eventsFailed: this.eventsFailed,
      flushErrors: this.flushErrors,
      lastFlushAt: this.lastFlushAt,
      lastErrorAt: this.lastErrorAt,
      lastError: this.lastError,
    };
  }
}
