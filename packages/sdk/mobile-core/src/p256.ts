/**
 * Pure-TypeScript ECDSA P-256 signer (ES256, RFC 7518).
 *
 * Implements the full signing stack — SHA-256, HMAC-SHA256, base64url codecs,
 * and the P-256 elliptic-curve math with RFC 6979 deterministic nonces — with
 * zero imports and no platform crypto, so the same bytes verify on iOS, Android
 * and in Node. This is the client half of the Kyber step-up / proof-key flow:
 *
 *  1. `generateP256KeyPair` produces a private scalar (32 bytes, base64url) and
 *     its DER SubjectPublicKeyInfo (SPKI) encoding (base64url). The SPKI is
 *     enrolled with the backend via `registerProofKey`.
 *  2. When a step-up challenge arrives, `signChallenge` computes
 *     `raw ES256 signature (r || s, 64 bytes, base64url)` over SHA-256 of the
 *     decoded challenge bytes, using RFC 6979 so the signature is deterministic
 *     (no RNG needed at signing time).
 *
 * The backend accepts BOTH the raw 64-byte P1363 form we emit and DER, so the
 * P1363 encoding is used directly as the `signature` field.
 *
 * ## Platform note on randomness
 *
 * `signChallenge` needs no entropy (RFC 6979). Key *generation* does, so
 * `generateP256KeyPair` accepts an injected CSPRNG; when none is passed it falls
 * back to `globalThis.crypto.getRandomValues` (present in modern browsers, React
 * Native, and Node >= 19) and throws a clear error where neither exists.
 *
 * ## Math note
 *
 * All scalar arithmetic uses native `bigint` (ES2020), matching this package's
 * compile target. The P-256 group order is a 256-bit prime, so every scalar fits
 * exactly in 32 bytes.
 */

// ── P-256 domain parameters (SEC 2 / RFC 8422) ─────────────────────────────
//
// Curve: y^2 = x^3 + a·x + b (mod p), with base point G of prime order n.
const P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffffn; // field modulus
const A = P - 3n; // P-256 short-Weierstrass a-coefficient
const B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604bn;
const GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296n;
const GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5n;
const N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551n; // group order
const BASE_POINT: Point = { x: GX, y: GY };

/** Bit length of the group order — for P-256 with SHA-256 this is exactly 256. */
const QLEN = 256;
/** Bytes per scalar: ceil(256 / 8) = 32. */
const SCALAR_BYTES = 32;

/** An affine curve point; `null` is the point at infinity. */
type Point = { x: bigint; y: bigint } | null;

// ── Base64url codecs ───────────────────────────────────────────────────────
// Implemented by hand (no `atob`/`Buffer`): the SDK targets platform-agnostic
// runtimes and this module must stay import-free.

const BASE64_URL_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function base64UrlEncode(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const n = (b0 << 16) | (b1 << 8) | b2;
    out += BASE64_URL_CHARS[(n >> 18) & 63];
    out += BASE64_URL_CHARS[(n >> 12) & 63];
    if (i + 1 < bytes.length) out += BASE64_URL_CHARS[(n >> 6) & 63];
    if (i + 2 < bytes.length) out += BASE64_URL_CHARS[n & 63];
  }
  return out;
}

/** 6-bit value per base64 character (standard alphabet; URL chars are normalized first). */
function buildDecodeLookup(): Int16Array {
  const lookup = new Int16Array(128).fill(-1);
  const standard = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  for (let i = 0; i < standard.length; i++) lookup[standard.charCodeAt(i)] = i;
  return lookup;
}
const BASE64_DECODE = buildDecodeLookup();

function base64UrlDecode(input: string): Uint8Array {
  let s = input.trim();
  // Accept the URL-safe alphabet (`-`, `_`) and the standard one (`+`, `/`).
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  const rem = s.length % 4;
  if (rem === 1) throw new Error('base64url: invalid encoded length');
  // The challenge may arrive padded or unpadded — restore padding if absent.
  if (rem === 2) s += '==';
  else if (rem === 3) s += '=';
  const groups = s.length / 4;
  const out = new Uint8Array(groups * 3 - (s.endsWith('==') ? 2 : s.endsWith('=') ? 1 : 0));
  let o = 0;
  for (let i = 0; i < s.length; i += 4) {
    const a = BASE64_DECODE[s.charCodeAt(i)];
    const b = BASE64_DECODE[s.charCodeAt(i + 1)];
    const c = s.charCodeAt(i + 2) === 61 ? -1 : BASE64_DECODE[s.charCodeAt(i + 2)];
    const d = s.charCodeAt(i + 3) === 61 ? -1 : BASE64_DECODE[s.charCodeAt(i + 3)];
    if (a < 0 || b < 0) throw new Error('base64url: invalid character');
    const n = (a << 18) | (b << 12) | ((c < 0 ? 0 : c) << 6) | (d < 0 ? 0 : d);
    out[o++] = (n >> 16) & 0xff;
    if (c >= 0) out[o++] = (n >> 8) & 0xff;
    if (d >= 0) out[o++] = n & 0xff;
  }
  return out;
}

// ── Byte / integer helpers ─────────────────────────────────────────────────
function bytesToBigInt(bytes: Uint8Array): bigint {
  let v = 0n;
  for (const b of bytes) v = (v << 8n) | BigInt(b);
  return v;
}

/** Fixed-width big-endian encoding (`int2octets` in RFC 6979 terms). */
function bigIntToBytesBE(value: bigint, length: number): Uint8Array {
  const out = new Uint8Array(length);
  let v = value;
  for (let i = length - 1; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return out;
}

function concatBytes(...arrays: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const a of arrays) total += a.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) {
    out.set(a, offset);
    offset += a.length;
  }
  return out;
}

// ── SHA-256 (FIPS 180-4) ───────────────────────────────────────────────────
// Pure 32-bit arithmetic. Intermediate bitwise results may be signed int32 in
// JS, but every result is re-masked with `>>> 0`, and modular addition is
// congruent under the int32 ↔ uint32 reinterpretation, so the digest is exact.

const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

const H256_INIT = new Uint32Array([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

function rotr32(x: number, n: number): number {
  return ((x >>> n) | (x << (32 - n))) >>> 0;
}

function sha256(message: Uint8Array): Uint8Array {
  const bitLength = BigInt(message.length) * 8n;
  const lenHi = Number((bitLength >> 32n) & 0xffffffffn);
  const lenLo = Number(bitLength & 0xffffffffn);
  // Pad: 0x80, zeros, then the 64-bit big-endian bit length.
  const paddedLen = Math.ceil((message.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLen);
  padded.set(message);
  padded[message.length] = 0x80;
  padded[paddedLen - 8] = (lenHi >>> 24) & 0xff;
  padded[paddedLen - 7] = (lenHi >>> 16) & 0xff;
  padded[paddedLen - 6] = (lenHi >>> 8) & 0xff;
  padded[paddedLen - 5] = lenHi & 0xff;
  padded[paddedLen - 4] = (lenLo >>> 24) & 0xff;
  padded[paddedLen - 3] = (lenLo >>> 16) & 0xff;
  padded[paddedLen - 2] = (lenLo >>> 8) & 0xff;
  padded[paddedLen - 1] = lenLo & 0xff;

  const h = new Uint32Array(H256_INIT);
  const w = new Uint32Array(64);
  for (let off = 0; off < paddedLen; off += 64) {
    for (let i = 0; i < 16; i++) {
      const j = off + i * 4;
      w[i] = ((padded[j] << 24) | (padded[j + 1] << 16) | (padded[j + 2] << 8) | padded[j + 3]) >>> 0;
    }
    for (let i = 16; i < 64; i++) {
      const s0 = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      const s1 = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = h[0];
    let b = h[1];
    let c = h[2];
    let d = h[3];
    let e = h[4];
    let f = h[5];
    let g = h[6];
    let hh = h[7];
    for (let i = 0; i < 64; i++) {
      const S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (hh + S1 + ch + K256[i] + w[i]) >>> 0;
      const S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      hh = g;
      g = f;
      f = e;
      e = (d + t1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0;
    h[1] = (h[1] + b) >>> 0;
    h[2] = (h[2] + c) >>> 0;
    h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0;
    h[5] = (h[5] + f) >>> 0;
    h[6] = (h[6] + g) >>> 0;
    h[7] = (h[7] + hh) >>> 0;
  }

  const out = new Uint8Array(32);
  for (let i = 0; i < 8; i++) {
    out[i * 4] = (h[i] >>> 24) & 0xff;
    out[i * 4 + 1] = (h[i] >>> 16) & 0xff;
    out[i * 4 + 2] = (h[i] >>> 8) & 0xff;
    out[i * 4 + 3] = h[i] & 0xff;
  }
  return out;
}

// ── HMAC-SHA256 (RFC 2104) — needed by RFC 6979 ────────────────────────────
function hmacSha256(key: Uint8Array, message: Uint8Array): Uint8Array {
  const BLOCK = 64;
  let k = key;
  if (k.length > BLOCK) k = sha256(k);
  const ipad = new Uint8Array(BLOCK);
  const opad = new Uint8Array(BLOCK);
  for (let i = 0; i < BLOCK; i++) {
    const kb = i < k.length ? k[i] : 0;
    ipad[i] = kb ^ 0x36;
    opad[i] = kb ^ 0x5c;
  }
  const inner = new Uint8Array(BLOCK + message.length);
  inner.set(ipad);
  inner.set(message, BLOCK);
  const innerHash = sha256(inner);
  const outer = new Uint8Array(BLOCK + 32);
  outer.set(opad);
  outer.set(innerHash, BLOCK);
  return sha256(outer);
}

// ── Modular arithmetic (all mod the field prime P unless stated) ───────────
function mod(a: bigint, m: bigint): bigint {
  const r = a % m;
  return r < 0n ? r + m : r;
}

/** Modular inverse via the extended Euclidean algorithm. */
function modInverse(a: bigint, m: bigint): bigint {
  let oldR = mod(a, m);
  let r = m;
  let oldS = 1n;
  let s = 0n;
  while (r !== 0n) {
    const q = oldR / r;
    [oldR, r] = [r, oldR - q * r];
    [oldS, s] = [s, oldS - q * s];
  }
  if (oldR !== 1n) throw new Error('modular inverse does not exist');
  return mod(oldS, m);
}

// ── Elliptic-curve point arithmetic (short Weierstrass form) ───────────────
function pointDouble(p: Point): Point {
  if (p === null) return null;
  if (p.y === 0n) return null; // y = 0 is a point of order 2 (never on P-256 for order-n points)
  const lambda = mod((3n * p.x * p.x + A) * modInverse(2n * p.y, P), P);
  const x3 = mod(lambda * lambda - 2n * p.x, P);
  const y3 = mod(lambda * (p.x - x3) - p.y, P);
  return { x: x3, y: y3 };
}

function pointAdd(p: Point, q: Point): Point {
  if (p === null) return q;
  if (q === null) return p;
  if (p.x === q.x) {
    if (mod(p.y + q.y, P) === 0n) return null; // p = -q
    return pointDouble(p); // p = q
  }
  const lambda = mod((q.y - p.y) * modInverse(mod(q.x - p.x, P), P), P);
  const x3 = mod(lambda * lambda - p.x - q.x, P);
  const y3 = mod(lambda * (p.x - x3) - p.y, P);
  return { x: x3, y: y3 };
}

/** Double-and-add scalar multiplication (k·P). */
function scalarMult(k: bigint, point: Point): Point {
  let result: Point = null;
  let addend = point;
  let kk = mod(k, N);
  while (kk > 0n) {
    if ((kk & 1n) === 1n) result = pointAdd(result, addend);
    addend = pointDouble(addend);
    kk >>= 1n;
  }
  return result;
}

// ── RFC 6979 deterministic nonce ───────────────────────────────────────────
// k is derived from HMAC over (private key ‖ message digest), so the same
// (key, message) always yields the same k — no CSPRNG at signing time and no
// nonce-reuse hazard across devices.
function rfc6979K(privateScalar: bigint, digest: Uint8Array): bigint {
  const int2octets = (x: bigint) => bigIntToBytesBE(x, SCALAR_BYTES);
  // qlen == 256 == digest length, so bits2int(h1) is the digest itself.
  const bits2octets = int2octets(mod(bytesToBigInt(digest), N));
  const x2o = int2octets(privateScalar);
  const zero = Uint8Array.of(0x00);
  const one = Uint8Array.of(0x01);

  let V = new Uint8Array(SCALAR_BYTES).fill(0x01);
  let K = new Uint8Array(SCALAR_BYTES); // all-zero
  K = hmacSha256(K, concatBytes(V, zero, x2o, bits2octets));
  V = hmacSha256(K, V);
  K = hmacSha256(K, concatBytes(V, one, x2o, bits2octets));
  V = hmacSha256(K, V);
  for (;;) {
    V = hmacSha256(K, V);
    // One HMAC iteration already yields qlen = 256 bits.
    const k = bytesToBigInt(V);
    if (k >= 1n && k <= N - 1n) return k;
    K = hmacSha256(K, concatBytes(V, zero));
    V = hmacSha256(K, V);
  }
}

// ── DER (SPKI) helpers ─────────────────────────────────────────────────────
function derLength(length: number): Uint8Array {
  if (length < 0x80) return Uint8Array.of(length);
  if (length < 0x100) return Uint8Array.of(0x81, length);
  if (length < 0x10000) return Uint8Array.of(0x82, (length >> 8) & 0xff, length & 0xff);
  throw new Error('DER length too large');
}

function derSequence(contents: Uint8Array): Uint8Array {
  return concatBytes(Uint8Array.of(0x30), derLength(contents.length), contents);
}

function derOid(encoded: Uint8Array): Uint8Array {
  return concatBytes(Uint8Array.of(0x06), derLength(encoded.length), encoded);
}

function derBitString(contents: Uint8Array): Uint8Array {
  return concatBytes(Uint8Array.of(0x03), derLength(contents.length + 1), Uint8Array.of(0x00), contents);
}

// DER encodings of the two algorithm OIDs used by the SPKI.
const OID_EC_PUBLIC_KEY = Uint8Array.of(0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01); // 1.2.840.10045.2.1
const OID_PRIME256V1 = Uint8Array.of(0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07); // 1.2.840.10045.3.1.7

/** SPKI: AlgorithmIdentifier + the uncompressed EC point (0x04 ‖ X ‖ Y). */
function spkiFromPoint(x: bigint, y: bigint): string {
  const point = concatBytes(Uint8Array.of(0x04), bigIntToBytesBE(x, SCALAR_BYTES), bigIntToBytesBE(y, SCALAR_BYTES));
  const algorithm = derSequence(concatBytes(derOid(OID_EC_PUBLIC_KEY), derOid(OID_PRIME256V1)));
  const spki = derSequence(concatBytes(algorithm, derBitString(point)));
  return base64UrlEncode(spki);
}

// ── Public API ─────────────────────────────────────────────────────────────

/** A CSPRNG that returns exactly `length` random bytes (injected by the host). */
export type RandomBytesSource = (length: number) => Uint8Array;

/** Runtime fallback for key generation: Web Crypto, when the platform exposes it. */
function defaultRandomBytes(length: number): Uint8Array {
  const gc = (globalThis as { crypto?: { getRandomValues?: (buf: Uint8Array) => Uint8Array } }).crypto;
  if (typeof gc?.getRandomValues !== 'function') {
    throw new Error(
      'generateP256KeyPair needs a CSPRNG: pass a randomBytes source, or run where ' +
        'globalThis.crypto.getRandomValues exists (browsers, React Native, Node >= 19).',
    );
  }
  const out = new Uint8Array(length);
  gc.getRandomValues(out);
  return out;
}

/**
 * Generate an ECDSA P-256 key pair.
 *
 * `privateKey` is the raw 32-byte private scalar (base64url, unpadded).
 * `publicKey` is the DER SubjectPublicKeyInfo (SPKI) encoding of the public
 * point (base64url, unpadded) — the exact value to enroll with
 * `registerProofKey`.
 */
export function generateP256KeyPair(
  randomBytes: RandomBytesSource = defaultRandomBytes,
): { privateKey: string; publicKey: string } {
  // Rejection-sample d uniformly in [1, n-1]. The top 32 bits of n are 0xFFFFFFFF
  // so a candidate in [n, 2^256) is astronomically unlikely; the loop terminates
  // in practice on the first or second draw.
  let d = 0n;
  for (;;) {
    const candidate = bytesToBigInt(randomBytes(SCALAR_BYTES));
    if (candidate >= 1n && candidate < N) {
      d = candidate;
      break;
    }
  }
  const publicPoint = scalarMult(d, BASE_POINT);
  if (publicPoint === null) throw new Error('P-256 scalar multiplication returned the point at infinity');
  return {
    privateKey: base64UrlEncode(bigIntToBytesBE(d, SCALAR_BYTES)),
    publicKey: spkiFromPoint(publicPoint.x, publicPoint.y),
  };
}

/**
 * Sign a Kyber step-up challenge with ECDSA P-256 / SHA-256 (ES256, RFC 7518).
 *
 * The challenge is a base64url string (padded or unpadded); the signed message is
 * SHA-256 over its decoded bytes. The nonce is derived per RFC 6979, so signing is
 * deterministic and needs no randomness.
 *
 * Returns the raw P1363 signature `r ‖ s` (32 bytes each, 64 bytes total),
 * base64url-encoded (unpadded) — accepted directly by the backend's
 * `_normalize_signature` and `verify_proof`.
 */
export function signChallenge(privateKeyB64url: string, challengeB64url: string): string {
  const d = bytesToBigInt(base64UrlDecode(privateKeyB64url));
  if (d < 1n || d >= N) throw new Error('signChallenge: private key is not a valid P-256 scalar');
  const digest = sha256(base64UrlDecode(challengeB64url));
  const z = bytesToBigInt(digest); // qlen == 256, so the digest is the full message representative
  const k = rfc6979K(d, digest);
  for (;;) {
    const rPoint = scalarMult(k, BASE_POINT);
    if (rPoint === null) continue;
    const r = mod(rPoint.x, N);
    if (r === 0n) continue;
    const s = mod(modInverse(k, N) * mod(z + r * d, N), N);
    if (s === 0n) continue;
    return base64UrlEncode(concatBytes(bigIntToBytesBE(r, SCALAR_BYTES), bigIntToBytesBE(s, SCALAR_BYTES)));
  }
}

/**
 * Derive the DER SPKI public key (base64url) for a private scalar.
 *
 * P-256 public-key derivation is deterministic — the public point is `d * G` —
 * so an install can re-derive the enrolled public key from the private key it
 * persisted, and a re-registration reuses the SAME key instead of churning a
 * fresh pair. This is the client half of durable attestation: the private
 * half never leaves the keystore, and the SPKI it produces is exactly what
 * `registerProofKey` enrolls.
 */
export function derivePublicKey(privateKeyB64url: string): string {
  const d = bytesToBigInt(base64UrlDecode(privateKeyB64url));
  if (d < 1n || d >= N) throw new Error('derivePublicKey: private key is not a valid P-256 scalar');
  const point = scalarMult(d, BASE_POINT);
  if (point === null) throw new Error('derivePublicKey: P-256 scalar multiplication returned the point at infinity');
  return spkiFromPoint(point.x, point.y);
}

/** Namespaced convenience accessor matching the package's other signer exports. */
export const P256Signer = {
  generateP256KeyPair,
  derivePublicKey,
  signChallenge,
} as const;
