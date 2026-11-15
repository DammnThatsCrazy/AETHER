import * as z from 'zod/v4';

import { AccessApiError, getExperience360Frame, requestAether } from './api.mjs';
import { EXPERIENCE360_SURFACES } from './experience360-catalog.mjs';
import { normalizeInteractionOutcome } from './interaction.mjs';

// Named Profile360 reads for design-partner agents and operators. Every call
// goes to an existing governed tenant route: frames through
// POST /v1/experience360/frames, identifier lookup through
// POST /v1/profile/resolve (the identifier stays in the body, never the URL).
// The server derives tenant and actor from the credential and evaluates policy
// before any provider read; nothing here widens, promotes or synthesizes a
// slot state, freshness verdict or evidence reference.

export const PROFILE360_SURFACE = 'profile360';
export const PROFILE360_RESOLVE_PATH = '/v1/profile/resolve';
export const MAX_PROFILE360_SLOT_SELECTION = 8;
export const PROFILE360_IDENTIFIER_KINDS = Object.freeze([
  'email', 'wallet', 'device', 'session', 'social', 'customer',
]);

const profile = EXPERIENCE360_SURFACES[PROFILE360_SURFACE];
const subjectId = z.string().trim().min(1).max(256);
const subjectKind = z.enum(profile.subjectKinds).optional();
const slotId = z.enum(profile.slots);
const asOf = z.string().max(64).optional();
const slotList = (max) => z.array(slotId).min(1).max(max)
  .refine((slots) => new Set(slots).size === slots.length, { message: 'Slots must be unique.' });

export const profile360GetInput = z.object({
  entity_id: subjectId,
  subject_kind: subjectKind,
  as_of: asOf,
  include_evidence: z.boolean().optional(),
}).strict();

export const profile360SlotGetInput = z.object({
  entity_id: subjectId,
  slots: slotList(MAX_PROFILE360_SLOT_SELECTION),
  subject_kind: subjectKind,
  as_of: asOf,
}).strict();

export const profile360EvidenceGetInput = z.object({
  entity_id: subjectId,
  slots: slotList(profile.slots.length).optional(),
  subject_kind: subjectKind,
  as_of: asOf,
}).strict();

export const profile360SearchInput = z.object(Object.fromEntries(
  PROFILE360_IDENTIFIER_KINDS.map((kind) => [kind, z.string().trim().min(1).max(kind === 'email' ? 320 : 256).optional()]),
)).strict().refine(
  (input) => Object.values(input).filter((value) => value !== undefined).length === 1,
  { message: 'Pass exactly one identifier.' },
);

function frameInput({ entity_id: id, subject_kind: kind, as_of: at }, extra = {}) {
  return {
    surface: PROFILE360_SURFACE,
    subject: { kind: kind ?? 'entity', id },
    ...(at !== undefined ? { as_of: at } : {}),
    ...extra,
  };
}

export function getProfile360(input, env = process.env) {
  return getExperience360Frame(frameInput(input, {
    include_evidence: input.include_evidence ?? true,
  }), env);
}

export function getProfile360Slots(input, env = process.env) {
  return getExperience360Frame(frameInput(input, {
    requested_slots: [...input.slots], include_evidence: true,
  }), env);
}

function evidenceView(slot) {
  return {
    id: slot.id,
    state: slot.state,
    ...(slot.freshness !== undefined ? { freshness: slot.freshness } : {}),
    evidenceRefs: Array.isArray(slot.evidenceRefs) ? slot.evidenceRefs : [],
    provenance: Array.isArray(slot.provenance) ? slot.provenance : [],
    claims: (Array.isArray(slot.claims) ? slot.claims : []).map((claim) => ({
      id: claim?.id,
      kind: claim?.kind,
      evidenceRefs: Array.isArray(claim?.evidenceRefs) ? claim.evidenceRefs : [],
    })),
    reasonCodes: Array.isArray(slot.reasonCodes) ? slot.reasonCodes : [],
    ...(slot.policyDisposition !== undefined ? { policyDisposition: slot.policyDisposition } : {}),
  };
}

/** Evidence, provenance, freshness and reasons per slot; slot content is omitted. */
export async function getProfile360Evidence(input, env = process.env) {
  const result = await getExperience360Frame(frameInput(input, {
    ...(input.slots ? { requested_slots: [...input.slots] } : {}),
    include_evidence: true,
  }), env);
  const frame = result.data;
  return {
    ...result,
    data: {
      view: 'profile360_evidence',
      surfaceId: frame.surfaceId,
      subject: frame.subject,
      ...(frame.generatedAt !== undefined ? { generatedAt: frame.generatedAt } : {}),
      ...(frame.freshness !== undefined ? { freshness: frame.freshness } : {}),
      slots: frame.slots.map(evidenceView),
    },
  };
}

/** Resolve exactly one identifier to the canonical profile/entity ID. */
export async function searchProfile360(input, env = process.env) {
  const parsed = profile360SearchInput.safeParse(input);
  if (!parsed.success) throw new Error('Invalid input for Access Kit operation profile360.search.');
  const body = Object.fromEntries(Object.entries(parsed.data).filter(([, value]) => value !== undefined));
  const result = await requestAether(PROFILE360_RESOLVE_PATH, undefined, env, {
    method: 'POST', operation: 'query', body,
  });
  const resolved = result.data?.resolved_user_id;
  if (typeof resolved !== 'string' || !resolved || resolved.length > 256) {
    throw new AccessApiError('Aether API returned an unexpected identifier resolution response.', {
      requestId: result.requestId,
      interaction: normalizeInteractionOutcome({
        operation: 'query', httpStatus: result.interaction.http_status,
        requestId: result.requestId, responseOk: true, contractError: true,
      }),
    });
  }
  return {
    ...result,
    data: { entity_id: resolved, subject: { kind: 'entity', id: resolved } },
  };
}
