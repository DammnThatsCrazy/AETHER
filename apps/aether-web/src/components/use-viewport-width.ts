import { useEffect, useState } from 'react';

/** Current window inner width, updated on resize (SSR/test safe default 1280). */
export function useViewportWidth(): number {
  const [width, setWidth] = useState(() => (typeof window === 'undefined' ? 1280 : window.innerWidth));
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return width;
}

/** Persisted boolean preference (localStorage), tolerant of blocked storage. */
export function readStoredFlag(key: string): boolean | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : raw === '1';
  } catch {
    return null;
  }
}

export function writeStoredFlag(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0');
  } catch {
    // Storage unavailable (private mode); the preference just isn't remembered.
  }
}
