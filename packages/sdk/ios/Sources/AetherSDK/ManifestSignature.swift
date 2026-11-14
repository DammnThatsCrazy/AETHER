// =============================================================================
// Aether SDK — iOS SDK manifest signature verification and intake
//
// Normative spec: docs/reference/sdks/manifest-signing.md. This file, the web
// verifier and the Android verifier are tested against the same vectors in
// tests/fixtures/sdk/manifest-signing-vectors.json, so all three accept and
// reject exactly the same manifests.
// =============================================================================

import Foundation
import CryptoKit

enum ManifestCanonicalizationError: Error {
    case unsupported(String)
}

/// ES256 (ECDSA P-256 / SHA-256, raw r||s) verification of SDK manifests.
public enum ManifestSignature {
    static let alg = "ecdsa-p256-sha256"

    private static let maxSafeInt: Int64 = 9_007_199_254_740_991
    /// DER prefix of a P-256 SubjectPublicKeyInfo; the 65-byte uncompressed point follows.
    private static let spkiPrefix: [UInt8] = [
        0x30, 0x59, 0x30, 0x13, 0x06, 0x07, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x02, 0x01,
        0x06, 0x08, 0x2a, 0x86, 0x48, 0xce, 0x3d, 0x03, 0x01, 0x07, 0x03, 0x42, 0x00,
    ]
    private static let base64URLAlphabet = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

    // MARK: Canonical JSON

    /// Deterministic JSON: sorted ASCII keys, no whitespace, integers only. Floats
    /// are rejected because number formatting is where JSON implementations
    /// disagree; no manifest field needs a fractional value.
    static func canonicalJSON(_ value: Any) throws -> String {
        var out = ""
        try write(value, into: &out)
        return out
    }

    private static func write(_ value: Any, into out: inout String) throws {
        if value is NSNull {
            out += "null"
        } else if let number = value as? NSNumber {
            if CFGetTypeID(number as CFTypeRef) == CFBooleanGetTypeID() {
                out += number.boolValue ? "true" : "false"
            } else {
                out += String(try integerValue(of: number))
            }
        } else if let string = value as? String {
            writeString(string, into: &out)
        } else if let array = value as? [Any] {
            out += "["
            for (index, element) in array.enumerated() {
                if index > 0 { out += "," }
                try write(element, into: &out)
            }
            out += "]"
        } else if let object = value as? [String: Any] {
            for key in object.keys where key.unicodeScalars.contains(where: { $0.value > 0x7f }) {
                throw ManifestCanonicalizationError.unsupported("non-ASCII object key: \(key)")
            }
            let keys = object.keys.sorted { $0.utf8.lexicographicallyPrecedes($1.utf8) }
            out += "{"
            for (index, key) in keys.enumerated() {
                if index > 0 { out += "," }
                writeString(key, into: &out)
                out += ":"
                try write(object[key]!, into: &out)
            }
            out += "}"
        } else {
            throw ManifestCanonicalizationError.unsupported("unsupported value type: \(type(of: value))")
        }
    }

    private static func integerValue(of number: NSNumber) throws -> Int64 {
        let double = number.doubleValue
        guard double.isFinite, double == double.rounded(), abs(double) <= Double(maxSafeInt) else {
            throw ManifestCanonicalizationError.unsupported("non-integer or unsafe number: \(number)")
        }
        return number.int64Value
    }

    /// Quote, backslash and C0 controls are escaped (lowercase \u00xx); all else literal.
    private static func writeString(_ string: String, into out: inout String) {
        out += "\""
        for scalar in string.unicodeScalars {
            switch scalar.value {
            case 0x22: out += "\\\""
            case 0x5c: out += "\\\\"
            case 0x08: out += "\\b"
            case 0x0c: out += "\\f"
            case 0x0a: out += "\\n"
            case 0x0d: out += "\\r"
            case 0x09: out += "\\t"
            case 0x00..<0x20: out += String(format: "\\u%04x", scalar.value)
            default: out.unicodeScalars.append(scalar)
            }
        }
        out += "\""
    }

    // MARK: Verification

    /// Strict unpadded base64url; nil when malformed.
    static func base64URLDecode(_ text: String) -> Data? {
        guard text.count % 4 != 1, text.allSatisfy({ base64URLAlphabet.contains($0) }) else { return nil }
        var base64 = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        base64 += String(repeating: "=", count: (4 - base64.count % 4) % 4)
        return Data(base64Encoded: base64)
    }

    /// Extract the 65-byte uncompressed point from a P-256 SPKI, or nil if it is
    /// not exactly a P-256 SubjectPublicKeyInfo.
    private static func x963Point(fromSPKI spki: Data) -> Data? {
        let bytes = [UInt8](spki)
        guard bytes.count == spkiPrefix.count + 65, Array(bytes.prefix(spkiPrefix.count)) == spkiPrefix,
              bytes[spkiPrefix.count] == 0x04 else { return nil }
        return Data(bytes.suffix(65))
    }

    /// Verify a parsed manifest (the manifest JSON object, `signature` included)
    /// against the configured base64url SPKI P-256 public key. Fails closed.
    public static func verify(_ manifest: [String: Any], publicKey: String) -> Bool {
        guard let signature = manifest["signature"] as? String,
              signature.count == 86,
              let rawSignature = base64URLDecode(signature), rawSignature.count == 64,
              (manifest["signature_alg"] as? String) == alg
        else { return false }

        var body = manifest
        body.removeValue(forKey: "signature")
        guard let canonical = try? canonicalJSON(body),
              let spki = base64URLDecode(publicKey),
              let point = x963Point(fromSPKI: spki),
              let key = try? P256.Signing.PublicKey(x963Representation: point),
              let parsed = try? P256.Signing.ECDSASignature(rawRepresentation: rawSignature)
        else { return false }

        return key.isValidSignature(parsed, for: Data(canonical.utf8))
    }
}

/// Parses a manifest response and applies the signature gate (pure; no I/O).
enum ManifestIntake {
    /// - Parameters:
    ///   - data: raw `GET /v1/config/sdk/manifest` response. The backend wraps the
    ///     manifest in an APIResponse envelope (`{"data": {...}}`).
    ///   - publicKey: base64url SPKI P-256 key, or nil/empty to apply unverified.
    /// - Returns: the manifest to apply, or nil when there is none or it is
    ///   rejected (the caller keeps its last known-good manifest).
    static func accept(_ data: Data, publicKey: String?) -> SDKManifest? {
        guard let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        let json = (root["data"] as? [String: Any]) ?? root
        guard json["manifest_version"] != nil else { return nil } // none published, or not a manifest

        if let key = publicKey, !key.isEmpty, !ManifestSignature.verify(json, publicKey: key) { return nil }

        var features: [String: Bool] = [:]
        for (name, value) in (json["features"] as? [String: Any]) ?? [:] {
            if let flag = value as? Bool { features[name] = flag }
        }
        return SDKManifest(
            manifest_version: json["manifest_version"] as? String ?? "0",
            min_sdk_version: json["min_sdk_version"] as? String ?? "0",
            schema_version: json["schema_version"] as? String ?? "0",
            rollout_percentage: json["rollout_percentage"] as? Int ?? 100,
            features: features,
            published_at: json["published_at"] as? String ?? "",
            signature: json["signature"] as? String ?? ""
        )
    }
}
