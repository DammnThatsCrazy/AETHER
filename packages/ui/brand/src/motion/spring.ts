export interface SpringToken {
  readonly stiffness: number;
  readonly damping: number;
  readonly mass: number;
}

/** Controlled springs only; no default bounce in the product interaction language. */
export const MOTION_SPRING = {
  responsive: { stiffness: 320, damping: 30, mass: 1 },
  panel: { stiffness: 260, damping: 32, mass: 1 },
  graph: { stiffness: 220, damping: 34, mass: 1.1 },
} as const satisfies Readonly<Record<string, SpringToken>>;

export type MotionSpring = keyof typeof MOTION_SPRING;
