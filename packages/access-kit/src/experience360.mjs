import * as z from 'zod/v4';

import { EXPERIENCE360_SURFACES } from './experience360-catalog.mjs';

// Wire contract for the existing governed 360 frame route
// (services/api/shared/intelligence_projections/routes.py):
//   POST /v1/experience360/frames  (a read; POST only because the body is structured)
// The adapter sends only the five fields below. It never sends tenant, actor,
// policy, lens, paging, time-range, purpose, or authorization-context fields:
// the server derives tenant and actor from the credential and evaluates policy
// before any projection read.

export const EXPERIENCE360_FRAME_PATH = '/v1/experience360/frames';
export const MAX_EXPERIENCE360_SLOTS = 32;
export const MAX_EXPERIENCE360_SUBJECT_ID_LENGTH = 256;
export const MAX_EXPERIENCE360_FRAME_SLOTS = 64;
export const MAX_EXPERIENCE360_FRAME_BYTES = 4 * 1024 * 1024;

const surfaceIds = Object.keys(EXPERIENCE360_SURFACES);
const RFC3339_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$/;
const SLOT_ID_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u;

function isRealRfc3339(value) {
  const match = RFC3339_PATTERN.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, offset] = match;
  const y = Number(year);
  const mo = Number(month);
  const d = Number(day);
  if (Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) return false;
  if (offset !== 'Z') {
    const [offsetHour, offsetMinute] = offset.slice(1).split(':').map(Number);
    if (offsetHour > 23 || offsetMinute > 59) return false;
  }
  // Date.parse is lenient about out-of-range days; require an exact calendar date.
  const calendar = new Date(Date.UTC(y, mo - 1, d));
  return calendar.getUTCFullYear() === y
    && calendar.getUTCMonth() === mo - 1
    && calendar.getUTCDate() === d;
}

export const experience360FrameInput = z.object({
  surface: z.enum(surfaceIds),
  subject: z.object({
    kind: z.string().min(1).max(64),
    id: z.string().min(1).max(MAX_EXPERIENCE360_SUBJECT_ID_LENGTH)
      .refine((value) => value === value.trim() && !CONTROL_CHARACTERS.test(value), {
        message: 'Subject IDs must not have surrounding whitespace or control characters.',
      }),
  }).strict(),
  requested_slots: z.array(z.string().regex(SLOT_ID_PATTERN))
    .min(1)
    .max(MAX_EXPERIENCE360_SLOTS)
    .optional(),
  as_of: z.string().max(64).refine(isRealRfc3339, {
    message: 'as_of must be an RFC 3339 timestamp with a timezone.',
  }).optional(),
  include_evidence: z.boolean().optional(),
}).strict().superRefine((input, context) => {
  const surface = EXPERIENCE360_SURFACES[input.surface];
  if (!surface) return;
  if (!surface.subjectKinds.includes(input.subject.kind)) {
    context.addIssue({
      code: 'custom', path: ['subject', 'kind'],
      message: 'Subject kind is not supported by this 360 surface.',
    });
  }
  if (input.requested_slots) {
    if (new Set(input.requested_slots).size !== input.requested_slots.length) {
      context.addIssue({ code: 'custom', path: ['requested_slots'], message: 'Slots must be unique.' });
    }
    if (input.requested_slots.some((slot) => !surface.slots.includes(slot))) {
      context.addIssue({
        code: 'custom', path: ['requested_slots'],
        message: 'A requested slot is not part of this 360 surface.',
      });
    }
  }
});

/** Validate input and build the exact request body; throws before any network use. */
export function buildExperience360FrameBody(input) {
  const parsed = experience360FrameInput.safeParse(input);
  if (!parsed.success) {
    throw new Error('Invalid input for Access Kit operation experience360.frame.get.');
  }
  const { surface, subject, requested_slots: slots, as_of: asOf, include_evidence: evidence } = parsed.data;
  return {
    surfaceId: surface,
    subject: { kind: subject.kind, id: subject.id },
    ...(slots ? { requestedSlotIds: [...slots] } : {}),
    ...(asOf !== undefined ? { asOf } : {}),
    ...(evidence !== undefined ? { includeEvidence: evidence } : {}),
  };
}

/**
 * Structural check only. The frame is returned to the caller verbatim: slot
 * states, evidence, limitations, policy dispositions, and degradation are the
 * server's and are never rewritten, promoted, or synthesized here.
 */
export function isFrameForRequest(frame, body) {
  return Boolean(frame)
    && typeof frame === 'object' && !Array.isArray(frame)
    && frame.surfaceId === body.surfaceId
    && frame.subject && typeof frame.subject === 'object'
    && frame.subject.kind === body.subject.kind
    && frame.subject.id === body.subject.id
    && Array.isArray(frame.slots)
    && frame.slots.length <= MAX_EXPERIENCE360_FRAME_SLOTS
    && Buffer.byteLength(JSON.stringify(frame), 'utf8') <= MAX_EXPERIENCE360_FRAME_BYTES;
}
