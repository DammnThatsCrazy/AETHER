import type { CanonicalConsentReceipt } from './integration-consent';
import type { ConsentPurpose } from './consent';

export type ConsentReceiptState = CanonicalConsentReceipt['state'];

export interface CanonicalConsentReceiptInput {
  tenant_id: string;
  subject_id?: string;
  anonymous_id?: string;
  purposes: readonly ConsentPurpose[];
  state: ConsentReceiptState;
  source: string;
  provider?: string;
  policy_version: string;
  jurisdiction_context?: string;
  mode?: string;
  lawful_basis?: string;
  granted_at?: string;
  denied_at?: string;
  revoked_at?: string;
  expires_at?: string;
  gpc_observed?: boolean;
  dnt_observed?: boolean;
  provider_consent_id?: string;
  metadata?: Readonly<Record<string, unknown>>;
}

const HASH_FIELDS: readonly (keyof CanonicalConsentReceiptInput)[] = [
  'tenant_id',
  'subject_id',
  'anonymous_id',
  'purposes',
  'state',
  'source',
  'provider',
  'policy_version',
  'jurisdiction_context',
  'mode',
  'lawful_basis',
  'granted_at',
  'denied_at',
  'revoked_at',
  'expires_at',
  'gpc_observed',
  'dnt_observed',
  'provider_consent_id',
  'metadata',
];

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
    .join(',')}}`;
}

function hashValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (Array.isArray(value)) {
    return [...new Set(value.map(String))].sort().join('\u001f');
  }
  if (typeof value === 'object') {
    return Object.keys(value as object).length === 0 ? '' : canonicalJson(value);
  }
  return String(value);
}

function fallbackSha256(input: Uint8Array): Uint8Array {
  const constants = new Uint32Array([
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ]);
  const bitLength = input.length * 8;
  const paddedLength = Math.ceil((input.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(input);
  padded[input.length] = 0x80;
  const view = new DataView(padded.buffer);
  view.setUint32(paddedLength - 4, bitLength >>> 0);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000));

  const state = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ]);
  const words = new Uint32Array(64);
  const rotateRight = (value: number, amount: number) =>
    (value >>> amount) | (value << (32 - amount));

  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4);
    }
    for (let index = 16; index < 64; index += 1) {
      const x = words[index - 15]!;
      const y = words[index - 2]!;
      const s0 = rotateRight(x, 7) ^ rotateRight(x, 18) ^ (x >>> 3);
      const s1 = rotateRight(y, 17) ^ rotateRight(y, 19) ^ (y >>> 10);
      words[index] = (words[index - 16]! + s0 + words[index - 7]! + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e!, 6) ^ rotateRight(e!, 11) ^ rotateRight(e!, 25);
      const choice = (e! & f!) ^ (~e! & g!);
      const temp1 = (h! + sum1 + choice + constants[index]! + words[index]!) >>> 0;
      const sum0 = rotateRight(a!, 2) ^ rotateRight(a!, 13) ^ rotateRight(a!, 22);
      const majority = (a! & b!) ^ (a! & c!) ^ (b! & c!);
      const temp2 = (sum0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d! + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    const next = [a!, b!, c!, d!, e!, f!, g!, h!];
    for (let index = 0; index < 8; index += 1) {
      state[index] = (state[index]! + next[index]!) >>> 0;
    }
  }
  const output = new Uint8Array(32);
  const outputView = new DataView(output.buffer);
  state.forEach((value, index) => outputView.setUint32(index * 4, value));
  return output;
}

export function canonicalConsentReceiptPreimage(input: CanonicalConsentReceiptInput): string {
  let preimage = 'aether-consent-receipt/v1\n';
  const encoder = new TextEncoder();
  for (const field of HASH_FIELDS) {
    const value = hashValue(input[field]);
    preimage += `${field}=${encoder.encode(value).byteLength}:${value}\n`;
  }
  return preimage;
}

export async function buildCanonicalConsentReceipt(
  input: CanonicalConsentReceiptInput,
): Promise<CanonicalConsentReceipt> {
  if (!input.tenant_id.trim()) throw new Error('tenant_id is required');
  if (!input.subject_id?.trim() && !input.anonymous_id?.trim()) {
    throw new Error('subject_id or anonymous_id is required');
  }
  if (input.purposes.length === 0) throw new Error('at least one purpose is required');

  const normalized: CanonicalConsentReceiptInput = {
    ...input,
    purposes: [...new Set(input.purposes)].sort(),
    metadata: input.metadata ?? {},
  };
  const bytes = new TextEncoder().encode(canonicalConsentReceiptPreimage(normalized));
  const digest = globalThis.crypto?.subtle
    ? new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes))
    : fallbackSha256(bytes);
  const hex = Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('');
  return {
    ...normalized,
    purposes: normalized.purposes,
    receipt_id: `ccr_${hex.slice(0, 32)}`,
    integrity_hash: `sha256:${hex}`,
    idempotency_key: `consent-receipt:${hex}`,
  };
}
