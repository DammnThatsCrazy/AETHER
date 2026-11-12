export declare const MANIFEST_SIGNATURE_ALG = "ecdsa-p256-sha256";
export declare class ManifestCanonicalizationError extends Error {
}
/**
 * Deterministic JSON: sorted ASCII keys, no whitespace, integers only.
 * Floats are rejected because number formatting is where JSON implementations
 * disagree; no manifest field needs a fractional value.
 */
export declare function canonicalJson(value: unknown): string;
/**
 * Verify a manifest (the parsed JSON object, `signature` included) against the
 * configured base64url SPKI P-256 public key.
 */
export declare function verifyManifestSignature(manifest: Record<string, unknown>, publicKeySpkiB64Url: string): Promise<boolean>;
