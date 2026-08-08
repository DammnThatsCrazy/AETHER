export const REDUCED_MOTION = {
  mediaQuery: '(prefers-reduced-motion: reduce)',
  durationMs: 1,
  iterationCount: 1,
  preserve: ['visibility', 'focus', 'loading-label', 'progress-value'] as const,
  avoid: ['decorative transform', 'continuous pulse', 'autoplay layout motion'] as const,
} as const;

export function motionDuration(reducedMotion: boolean, duration: number): number {
  return reducedMotion ? REDUCED_MOTION.durationMs : duration;
}
