// =============================================================================
// Aether SDK — SDK MANIFEST SIGNATURE VERIFICATION (ES256, canonical JSON)
//
// Normative spec: docs/reference/sdks/manifest-signing.md. This file and its
// iOS / Android counterparts are tested against the shared vectors in
// tests/fixtures/sdk/manifest-signing-vectors.json, so all three accept and
// reject exactly the same manifests.
//
// Fail closed: anything malformed, unsupported or unverifiable returns false.
// =============================================================================

export const MANIFEST_SIGNATURE_ALG = 'ecdsa-p256-sha256';

const SIGNATURE_RE = /^[A-Za-z0-9_-]{86}$/; // unpadded base64url of 64 raw bytes (r || s)
const ASCII_RE = /^[\x00-\x7f]*$/;

export class ManifestCanonicalizationError extends Error {}

/**
 * Deterministic JSON: sorted ASCII keys, no whitespace, integers only.
 * Floats are rejected because number formatting is where JSON implementations
 * disagree; no manifest field needs a fractional value.
 */
export function canonicalJson(value: unknown): string {
  if (value === null) return 'null';
  switch (typeof value) {
    case 'boolean':
      return value ? 'true' : 'false';
    case 'number':
      if (!Number.isSafeInteger(value)) {
        throw new ManifestCanonicalizationError(`non-integer or unsafe number: ${value}`);
      }
      return String(value);
    case 'string':
      // JSON.stringify escapes only quote, backslash and C0 controls (lowercase
      // \u00xx) and leaves everything else literal — the spec's string form.
      return JSON.stringify(value);
    case 'object': {
      if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
      const obj = value as Record<string, unknown>;
      const keys = Object.keys(obj);
      for (const key of keys) {
        if (!ASCII_RE.test(key)) throw new ManifestCanonicalizationError(`non-ASCII object key: ${key}`);
      }
      keys.sort();
      return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(obj[k])}`).join(',')}}`;
    }
    default:
      throw new ManifestCanonicalizationError(`unsupported value type: ${typeof value}`);
  }
}

function base64UrlToBytes(text: string): Uint8Array {
  const b64 = text.replace(/-/g, '+').replace(/_/g, '/');
  const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
  const bin = atob(padded);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * Verify a manifest (the parsed JSON object, `signature` included) against the
 * configured base64url SPKI P-256 public key.
 */
export async function verifyManifestSignature(
  manifest: Record<string, unknown>,
  publicKeySpkiB64Url: string,
): Promise<boolean> {
  try {
    if (typeof crypto === 'undefined' || !crypto.subtle) return false; // cannot verify => reject
    const signature = manifest.signature;
    if (typeof signature !== 'string' || !SIGNATURE_RE.test(signature)) return false;
    if (manifest.signature_alg !== MANIFEST_SIGNATURE_ALG) return false;

    const { signature: _omit, ...body } = manifest;
    const data = new TextEncoder().encode(canonicalJson(body));
    const key = await crypto.subtle.importKey(
      'spki',
      base64UrlToBytes(publicKeySpkiB64Url) as unknown as ArrayBuffer,
      { name: 'ECDSA', namedCurve: 'P-256' },
      false,
      ['verify'],
    );
    // WebCrypto ECDSA signatures are raw r || s, the wire format of the spec.
    return await crypto.subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' },
      key,
      base64UrlToBytes(signature) as unknown as ArrayBuffer,
      data as unknown as ArrayBuffer,
    );
  } catch {
    return false;
  }
}
