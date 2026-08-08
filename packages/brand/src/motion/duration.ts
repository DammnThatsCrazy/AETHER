export const MOTION_DURATION = {
  instant: 0,
  micro: 120,
  standard: 180,
  panel: 240,
  complex: 320,
} as const;

export type MotionDuration = keyof typeof MOTION_DURATION;
