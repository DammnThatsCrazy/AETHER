// =============================================================================
// Aether SDK — Android SDK manifest model, signature verification and intake
//
// Normative spec: docs/reference/sdks/manifest-signing.md. This file, the web
// verifier and the iOS verifier are tested against the same vectors in
// tests/fixtures/sdk/manifest-signing-vectors.json, so all three accept and
// reject exactly the same manifests.
//
// Deliberately free of android.* imports so the logic runs in plain JVM tests.
// =============================================================================

package com.aether.sdk

import org.json.JSONArray
import org.json.JSONObject
import java.math.BigInteger
import java.security.KeyFactory
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.X509EncodedKeySpec

data class SDKManifest(
    val manifest_version: String,
    val min_sdk_version: String,
    val schema_version: String,
    val rollout_percentage: Int,
    val features: Map<String, Boolean>,
    val published_at: String,
    val signature: String
)

typealias ManifestUpdateCallback = (SDKManifest) -> Unit

/** Thrown when a JSON value cannot be represented in the canonical signing form. */
class ManifestCanonicalizationException(message: String) : IllegalArgumentException(message)

/** ES256 (ECDSA P-256 / SHA-256, raw r||s) verification of SDK manifests. */
object ManifestSignature {
    const val ALG = "ecdsa-p256-sha256"

    private const val MAX_SAFE_INT = 9007199254740991L
    private val SIGNATURE_RE = Regex("^[A-Za-z0-9_-]{86}$")
    private val P256_ORDER = BigInteger(
        "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16
    )
    private const val B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

    /**
     * Deterministic JSON: sorted ASCII keys, no whitespace, integers only. Floats
     * are rejected because number formatting is where JSON implementations
     * disagree; no manifest field needs a fractional value.
     */
    fun canonicalJson(value: Any?): String {
        val sb = StringBuilder()
        writeCanonical(value, sb)
        return sb.toString()
    }

    private fun writeCanonical(value: Any?, sb: StringBuilder) {
        when {
            value == null || value === JSONObject.NULL -> sb.append("null")
            value is Boolean -> sb.append(if (value) "true" else "false")
            value is Int || value is Long || value is Short || value is Byte -> {
                val n = (value as Number).toLong()
                if (n > MAX_SAFE_INT || n < -MAX_SAFE_INT) {
                    throw ManifestCanonicalizationException("integer outside the safe range: $n")
                }
                sb.append(n)
            }
            value is Number -> throw ManifestCanonicalizationException("non-integer number: $value")
            value is String -> writeString(value, sb)
            value is JSONArray -> {
                sb.append('[')
                for (i in 0 until value.length()) {
                    if (i > 0) sb.append(',')
                    writeCanonical(value.get(i), sb)
                }
                sb.append(']')
            }
            value is JSONObject -> {
                val keys = value.keys().asSequence().toList()
                for (k in keys) {
                    if (k.any { it.code > 0x7f }) {
                        throw ManifestCanonicalizationException("non-ASCII object key: $k")
                    }
                }
                sb.append('{')
                keys.sorted().forEachIndexed { i, k ->
                    if (i > 0) sb.append(',')
                    writeString(k, sb)
                    sb.append(':')
                    writeCanonical(value.get(k), sb)
                }
                sb.append('}')
            }
            else -> throw ManifestCanonicalizationException("unsupported value type: ${value.javaClass.name}")
        }
    }

    /** Quote, backslash and C0 controls are escaped (lowercase \u00xx); all else literal. */
    private fun writeString(s: String, sb: StringBuilder) {
        sb.append('"')
        for (c in s) {
            when {
                c == '"' -> sb.append("\\\"")
                c == '\\' -> sb.append("\\\\")
                c == '\b' -> sb.append("\\b")
                c == '\u000C' -> sb.append("\\f")
                c == '\n' -> sb.append("\\n")
                c == '\r' -> sb.append("\\r")
                c == '\t' -> sb.append("\\t")
                c.code < 0x20 -> sb.append("\\u").append(String.format(java.util.Locale.ROOT, "%04x", c.code))
                else -> sb.append(c)
            }
        }
        sb.append('"')
    }

    /** Strict unpadded base64url; null when malformed. */
    fun base64UrlDecode(text: String): ByteArray? {
        if (text.length % 4 == 1) return null
        val out = java.io.ByteArrayOutputStream()
        var buffer = 0
        var bits = 0
        for (ch in text) {
            val v = B64URL.indexOf(ch)
            if (v < 0) return null
            buffer = (buffer shl 6) or v
            bits += 6
            if (bits >= 8) {
                bits -= 8
                out.write((buffer shr bits) and 0xff)
            }
        }
        return out.toByteArray()
    }

    private fun derInteger(raw: ByteArray): ByteArray {
        var start = 0
        while (start < raw.size - 1 && raw[start].toInt() == 0) start++
        var body = raw.copyOfRange(start, raw.size)
        if (body[0].toInt() and 0x80 != 0) body = byteArrayOf(0) + body
        return byteArrayOf(0x02, body.size.toByte()) + body
    }

    /** JCA's SHA256withECDSA wants DER; the wire format is raw r||s. */
    private fun rawToDer(raw: ByteArray): ByteArray {
        val r = derInteger(raw.copyOfRange(0, 32))
        val s = derInteger(raw.copyOfRange(32, 64))
        return byteArrayOf(0x30, (r.size + s.size).toByte()) + r + s
    }

    /**
     * Verify a parsed manifest (the manifest JSON object, `signature` included)
     * against the configured base64url SPKI P-256 public key. Fails closed.
     */
    fun verify(manifest: JSONObject, publicKeySpkiB64Url: String): Boolean {
        return try {
            val signature = manifest.opt("signature") as? String ?: return false
            if (!SIGNATURE_RE.matches(signature)) return false
            if (manifest.opt("signature_alg") != ALG) return false

            val body = JSONObject()
            for (k in manifest.keys()) if (k != "signature") body.put(k, manifest.get(k))
            val data = canonicalJson(body).toByteArray(Charsets.UTF_8)

            val spki = base64UrlDecode(publicKeySpkiB64Url) ?: return false
            val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(spki))
            if (key !is ECPublicKey || key.params.order != P256_ORDER) return false

            val sig = base64UrlDecode(signature) ?: return false
            if (sig.size != 64) return false
            val verifier = Signature.getInstance("SHA256withECDSA")
            verifier.initVerify(key)
            verifier.update(data)
            verifier.verify(rawToDer(sig))
        } catch (_: Exception) {
            false
        }
    }
}

/** Parses a manifest response and applies the signature gate (pure; no I/O). */
object ManifestIntake {
    /**
     * @param body raw `GET /v1/config/sdk/manifest` response. The backend wraps
     *   the manifest in an APIResponse envelope (`{"data": {...}}`).
     * @param publicKey base64url SPKI P-256 key, or null/empty to apply unverified.
     * @return the manifest to apply, or null when there is none or it is rejected
     *   (the caller keeps its last known-good manifest).
     */
    fun accept(body: String, publicKey: String?): SDKManifest? {
        return try {
            val root = JSONObject(body)
            val json = root.optJSONObject("data") ?: root
            if (!json.has("manifest_version")) return null // none published, or not a manifest

            if (!publicKey.isNullOrEmpty() && !ManifestSignature.verify(json, publicKey)) return null

            val featuresJson = json.optJSONObject("features")
            val features = mutableMapOf<String, Boolean>()
            featuresJson?.keys()?.forEach { key -> features[key] = featuresJson.optBoolean(key, false) }
            SDKManifest(
                manifest_version = json.optString("manifest_version", "0"),
                min_sdk_version = json.optString("min_sdk_version", "0"),
                schema_version = json.optString("schema_version", "0"),
                rollout_percentage = json.optInt("rollout_percentage", 100),
                features = features,
                published_at = json.optString("published_at", ""),
                signature = json.optString("signature", "")
            )
        } catch (_: Exception) {
            null
        }
    }
}
