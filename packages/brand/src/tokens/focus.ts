export const FOCUS_RING = {
  width: 2,
  offset: 2,
  color: 'var(--color-border-focus)',
  style: 'solid',
} as const;

export const focusStyles = {
  keyboard: {
    outline: `${FOCUS_RING.width}px ${FOCUS_RING.style} ${FOCUS_RING.color}`,
    outlineOffset: `${FOCUS_RING.offset}px`,
  },
  within: {
    boxShadow: `0 0 0 ${FOCUS_RING.width}px ${FOCUS_RING.color}`,
  },
} as const;

/** Small visual icons still need accessible interactive hit targets. */
export const MINIMUM_INTERACTIVE_TARGET = {
  pointer: 44,
  compactKeyboard: 32,
} as const;
