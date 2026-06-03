export type DemoEnv = 'local-mocked' | 'local-live' | 'staging' | 'production';

export function getDemoEnv(): DemoEnv {
  const v = (import.meta.env.VITE_DEMO_ENV as string | undefined) ?? 'local-mocked';
  return (['local-mocked', 'local-live', 'staging', 'production'].includes(v) ? v : 'local-mocked') as DemoEnv;
}

export function isLocalMocked(): boolean {
  return getDemoEnv() === 'local-mocked';
}
