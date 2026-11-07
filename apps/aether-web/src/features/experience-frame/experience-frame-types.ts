/**
 * Client view of a governed 360 frame (`POST /v1/experience360/frames`).
 *
 * The server owns every state word. The schema validates shape only and keeps
 * state strings as the server sent them, so a new or unfamiliar state is shown
 * verbatim rather than being mapped to something friendlier. Slot `content` is
 * deliberately not part of this view: this surface shows state, policy, and
 * evidence counts, never a client-formatted value.
 */

import { z } from 'zod';

const policyDispositionSchema = z.object({
  state: z.string().optional(),
}).passthrough();

const slotSchema = z.object({
  id: z.string(),
  requirement: z.string(),
  state: z.string(),
  description: z.string().nullable().optional(),
  evidenceRefs: z.array(z.unknown()).default([]),
  limitations: z.array(z.string()).default([]),
  reasonCodes: z.array(z.string()).default([]),
  policyDisposition: policyDispositionSchema.optional(),
}).passthrough();

export const experienceFrameSchema = z.object({
  surfaceId: z.string(),
  subject: z.object({ kind: z.string(), id: z.string() }).passthrough(),
  state: z.string(),
  generatedAt: z.string(),
  asOf: z.string().nullable().optional(),
  slots: z.array(slotSchema),
  warnings: z.array(z.string()).default([]),
  degradation: z.object({ level: z.string().optional() }).passthrough().nullable().optional(),
  ownsCanonicalTruth: z.literal(false),
}).passthrough();

export type ExperienceFrame = z.infer<typeof experienceFrameSchema>;
export type ExperienceFrameSlot = ExperienceFrame['slots'][number];

export interface ExperienceFrameRequest {
  readonly surfaceId: string;
  readonly subject: { readonly kind: string; readonly id: string };
  readonly requestedSlotIds?: readonly string[];
  readonly asOf?: string;
}

/**
 * `restClient` types a schema's input and output as the same type; the `default([])`
 * fields make them differ, so the client is handed the parsed (output) shape.
 */
export const experienceFrameResponseSchema =
  experienceFrameSchema as unknown as z.ZodType<ExperienceFrame>;
