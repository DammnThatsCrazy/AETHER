import { cn } from '../utils/cn';

export type RuntimeDataMode = 'mocked' | 'live';

/**
 * Global honesty guard: whenever a deployment is serving in-browser MOCK data,
 * every surface in the app must say so — mock fixtures may never be presented as
 * live. This is presentational only; each app passes its own resolved runtime
 * mode (from `isLocalMocked()` / `getRuntimeMode()`) and whether the governing
 * `VITE_*_ENV` var was explicitly set. A MISSING env var defaults to
 * `local-mocked`, which is the dangerous case the `envExplicit=false` branch
 * calls out loudly so mocks never silently ship looking live.
 */
export interface MockModeBannerProps {
  readonly mode: RuntimeDataMode;
  /** Name of the governing env var, e.g. `VITE_AETHER_ENV` / `VITE_KYBER_ENV`. */
  readonly envVarName: string;
  /** Whether the env var was explicitly set (vs. defaulted to `local-mocked`). */
  readonly envExplicit: boolean;
  readonly className?: string | undefined;
}

export function MockModeBanner({ mode, envVarName, envExplicit, className }: MockModeBannerProps) {
  // Live mode: never render — no honesty caveat needed.
  if (mode !== 'mocked') return null;

  const undeclared = !envExplicit;

  return (
    <div
      role="status"
      data-mock-mode="active"
      data-env-explicit={envExplicit ? 'true' : 'false'}
      className={cn(
        'flex flex-wrap items-center gap-x-2 gap-y-1 border-b px-4 py-1.5 text-xs font-mono',
        undeclared
          ? 'border-danger/40 bg-danger/10 text-danger'
          : 'border-warning/40 bg-warning/10 text-warning',
        className,
      )}
    >
      <span className="font-semibold uppercase tracking-wide">
        {undeclared ? '⛔ Mock data' : '● Mock data'}
      </span>
      <span className="text-text-secondary">
        Every capability state on this screen is served by the in-browser mock
        service worker — <strong className="text-inherit">not live</strong>.
      </span>
      {undeclared ? (
        <span>
          {envVarName} is not set, so it defaulted to <code>local-mocked</code>.
          Set it explicitly to avoid shipping mocks that look live.
        </span>
      ) : (
        <span className="text-text-muted">({envVarName}=local-mocked)</span>
      )}
    </div>
  );
}
