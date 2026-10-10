import { describe, expect, it } from 'vitest';
import { createPublicKey, createVerify, randomBytes } from 'node:crypto';

import { derivePublicKey, generateP256KeyPair, P256Signer, signChallenge } from '../index';

// ── Node-side helpers ──────────────────────────────────────────────────────
// Node crypto is used here ONLY as the independent verifier. The signer in
// `src/p256.ts` is pure TypeScript and never imports it.

/** CSPRNG built on Node's crypto — injected into the signer by the test. */
const nodeRng = (length: number): Uint8Array => new Uint8Array(randomBytes(length));

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

function derLength(length: number): Uint8Array {
  if (length < 0x80) return Uint8Array.of(length);
  if (length < 0x100) return Uint8Array.of(0x81, length);
  throw new Error('test DER: length too large');
}

/** DER INTEGER from fixed-width big-endian bytes (minimal two's complement). */
function derInteger(value: Uint8Array): Uint8Array {
  let i = 0;
  while (i < value.length - 1 && value[i] === 0) i += 1;
  let trimmed = value.subarray(i);
  if (trimmed.length === 0) trimmed = Uint8Array.of(0);
  if ((trimmed[0] & 0x80) !== 0) {
    trimmed = concatBytes(Uint8Array.of(0x00), trimmed);
  }
  return concatBytes(Uint8Array.of(0x02), derLength(trimmed.length), trimmed);
}

/** Convert the raw P1363 `r || s` signature to the DER form Node's verifier wants. */
function p1363ToDer(raw: Uint8Array): Buffer {
  const contents = concatBytes(derInteger(raw.subarray(0, 32)), derInteger(raw.subarray(32, 64)));
  return Buffer.from(concatBytes(Uint8Array.of(0x30), derLength(contents.length), contents));
}

function loadPublicKey(publicKeyB64Url: string): ReturnType<typeof createPublicKey> {
  return createPublicKey({
    key: Buffer.from(publicKeyB64Url, 'base64url'),
    format: 'der',
    type: 'spki',
  });
}

function padTo4(input: string): string {
  const rem = input.length % 4;
  return rem === 0 ? input : input + '='.repeat(4 - rem);
}

const challengeText = 'kyber-step-up:capability=kyber.workforce.execute:ts=2026-08-07T00:00:00Z';
const challengeBytes = Buffer.from(challengeText, 'utf8');
const challengeB64 = challengeBytes.toString('base64url'); // unpadded, as the backend sends

describe('P256Signer (pure-TS ECDSA P-256 / ES256)', () => {
  it('generates a P-256 key pair whose SPKI imports as an EC P-256 public key', () => {
    const { privateKey, publicKey } = generateP256KeyPair(nodeRng);
    const key = loadPublicKey(publicKey);
    expect(key.asymmetricKeyType).toBe('ec');
    expect(key.asymmetricKeyDetails?.namedCurve).toBe('prime256v1');
    // The private key is the raw 32-byte scalar, base64url-encoded.
    expect(Buffer.from(privateKey, 'base64url')).toHaveLength(32);
  });

  it('signs a challenge and verifies against Node crypto over SHA-256 of the challenge bytes', () => {
    const { privateKey, publicKey } = generateP256KeyPair(nodeRng);
    const signatureB64 = signChallenge(privateKey, challengeB64);
    const raw = Buffer.from(signatureB64, 'base64url');

    const verifier = createVerify('SHA256');
    verifier.update(challengeBytes);
    expect(verifier.verify(loadPublicKey(publicKey), p1363ToDer(raw))).toBe(true);
  });

  it('accepts both padded and unpadded base64url challenges', () => {
    const { privateKey, publicKey } = generateP256KeyPair(nodeRng);
    const padded = padTo4(challengeB64);
    expect(padded.length % 4).toBe(0);

    // Padding is ignored at decode time, so the signature is byte-identical.
    const sigUnpadded = signChallenge(privateKey, challengeB64);
    const sigPadded = signChallenge(privateKey, padded);
    expect(sigPadded).toBe(sigUnpadded);

    const verifier = createVerify('SHA256');
    verifier.update(challengeBytes);
    expect(verifier.verify(loadPublicKey(publicKey), p1363ToDer(Buffer.from(sigPadded, 'base64url')))).toBe(true);
  });

  it('is deterministic: same key + same challenge yields the same signature', () => {
    const { privateKey } = generateP256KeyPair(nodeRng);
    const first = signChallenge(privateKey, challengeB64);
    const second = signChallenge(privateKey, challengeB64);
    expect(second).toBe(first);
  });

  it('produces a raw P1363 signature of exactly 64 bytes (r || s)', () => {
    const { privateKey } = generateP256KeyPair(nodeRng);
    const signatureB64 = signChallenge(privateKey, challengeB64);
    expect(Buffer.from(signatureB64, 'base64url')).toHaveLength(64);
  });

  it('matches the RFC 6979 A.2.5 known-answer test vector (P-256 / SHA-256, "sample")', () => {
    // Test vector straight from RFC 6979 Appendix A.2.5. Node's OpenSSL signs
    // with a RANDOM k, so byte-for-byte determinism is checked against the RFC's
    // published (r, s) for the fixed key and message instead.
    const vectorPrivateKey = Buffer.from(
      'c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721',
      'hex',
    ).toString('base64url');
    const expectedR = 'efd48b2aacb6a8fd1140dd9cd45e81d69d2c877b56aaf991c34d0ea84eaf3716';
    const expectedS = 'f7cb1c942d657c41d436c7a1b6e29f65f3e900dbb9aff4064dc4ab2f843acda8';

    const challengeB64 = Buffer.from('sample', 'utf8').toString('base64url');
    const raw = Buffer.from(signChallenge(vectorPrivateKey, challengeB64), 'base64url');
    expect(raw).toHaveLength(64);
    expect(raw.subarray(0, 32).toString('hex')).toBe(expectedR);
    expect(raw.subarray(32, 64).toString('hex')).toBe(expectedS);
  });

  it('derivePublicKey recomputes the SPKI for a private scalar (round-trip with generateP256KeyPair)', () => {
    const { privateKey, publicKey } = generateP256KeyPair(nodeRng);
    expect(derivePublicKey(privateKey)).toBe(publicKey);
    // And a second call is stable (deterministic derivation).
    expect(derivePublicKey(privateKey)).toBe(publicKey);
  });

  it('derivePublicKey matches the RFC 6979 A.2.5 known public point for the vector key', () => {
    // RFC 6979 Appendix A.2.5 (P-256 / SHA-256, "sample") fixes the key pair:
    // private scalar c9af...6721, public point Q = (60fed4..., 7903fe...).
    const vectorPrivateKey = Buffer.from(
      'c9afa9d845ba75166b5c215767b1d6934e50c3db36e89b127b8a622b120f6721',
      'hex',
    ).toString('base64url');
    const knownQx = '60fed4ba255a9d31c961eb74c6356d68c049b8923b61fa6ce669622e60f29fb6';
    const knownQy = '7903fe1008b8bc99a41ae9e95628bc64f2f1b20c2d7e9f5177a3c294d4462299';

    const spki = Buffer.from(derivePublicKey(vectorPrivateKey), 'base64url');
    // SPKI DER: algorithm header (19 bytes) then BIT STRING 0x03 0x42 0x00 || 0x04 || X || Y.
    const point = spki.subarray(spki.length - 65);
    expect(point[0]).toBe(0x04);
    expect(point.subarray(1, 33).toString('hex')).toBe(knownQx);
    expect(point.subarray(33).toString('hex')).toBe(knownQy);
  });

  it('derivePublicKey rejects an out-of-range private scalar', () => {
    expect(() => derivePublicKey('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')).toThrow();
  });

  it('generates keys through the global CSPRNG fallback when no RNG is passed', () => {
    const { privateKey, publicKey } = generateP256KeyPair();
    const key = loadPublicKey(publicKey);
    expect(key.asymmetricKeyType).toBe('ec');
    expect(Buffer.from(privateKey, 'base64url')).toHaveLength(32);
  });

  it('exposes the same functions through the P256Signer namespace', () => {
    const { privateKey, publicKey } = P256Signer.generateP256KeyPair(nodeRng);
    const signatureB64 = P256Signer.signChallenge(privateKey, challengeB64);
    const verifier = createVerify('SHA256');
    verifier.update(challengeBytes);
    expect(verifier.verify(loadPublicKey(publicKey), p1363ToDer(Buffer.from(signatureB64, 'base64url')))).toBe(true);
  });

  it('rejects an out-of-range private scalar', () => {
    // All-zero decodes to scalar 0, which is not a valid P-256 private key.
    expect(() => signChallenge('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', challengeB64)).toThrow();
  });
});
