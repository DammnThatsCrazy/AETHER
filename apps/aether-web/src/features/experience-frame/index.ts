/**
 * Governed 360 frame display: per-slot state shown exactly as the server
 * reports it. The client never recomputes a state or formats slot content.
 */

export { ExperienceFramePanel, ExperienceFrameSlots, slotStateVariant } from './experience-frame-slots';
export type { ExperienceFramePanelProps, ExperienceFrameSlotsProps } from './experience-frame-slots';
export { useExperienceFrame } from './use-experience-frame';
export { experienceFrameSchema } from './experience-frame-types';
export type { ExperienceFrame, ExperienceFrameRequest, ExperienceFrameSlot } from './experience-frame-types';
