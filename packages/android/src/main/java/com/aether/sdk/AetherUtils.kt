package com.aether.sdk

import org.json.JSONObject
import java.net.URI
import java.net.URLDecoder
import java.security.MessageDigest

internal val SENSITIVE_KEYS: Set<String> = setOf(
    "privatekey", "private_key", "seedphrase", "seed_phrase", "mnemonic",
    "secret", "secretkey", "secret_key", "password", "pin",
    "cardnumber", "card_number", "pan", "cvv", "cvc", "cvv2",
    "paymenttoken", "payment_token", "authcode", "auth_code"
)

// Bounds descent into pathological nesting; values at or beyond the cap pass through un-descended.
private const val SCRUB_MAX_DEPTH = 32

internal fun scrubSensitiveFields(props: Map<String, Any?>): Map<String, Any?> =
    props.mapValues { (key, value) ->
        if (key.lowercase() in SENSITIVE_KEYS) "[REDACTED]" else scrubNestedValue(value, depth = 1)
    }

private fun scrubNestedValue(value: Any?, depth: Int): Any? {
    if (depth >= SCRUB_MAX_DEPTH) return value
    return when (value) {
        is Map<*, *> -> value.entries.associate { (key, nested) ->
            key to if (key is String && key.lowercase() in SENSITIVE_KEYS) "[REDACTED]"
                   else scrubNestedValue(nested, depth + 1)
        }
        is List<*> -> value.map { scrubNestedValue(it, depth + 1) }
        else -> value
    }
}

internal fun normalizeWalletAddress(address: String, vm: String = "evm"): String =
    when (vm.lowercase()) {
        "evm" -> address.lowercase()
        else  -> address.trim()
    }

// =============================================================================
// ACQUISITION EVIDENCE (shared AcquisitionEvidence contract, schema v3)
//
// The SDK OBSERVES evidence and names the entry method; the backend classifies.
// Mirrors packages/shared/acquisition-evidence.ts field names exactly.
// Pure JVM (java.net / org.json only) so it stays unit-testable without an
// Android runtime.
// =============================================================================

/** Must match ACQUISITION_EVIDENCE_SCHEMA_VERSION in packages/shared/acquisition-evidence.ts. */
internal const val ACQUISITION_EVIDENCE_SCHEMA_VERSION = 3

/** Paid-click identifier query params preserved as evidence (never in transmitted URLs). */
internal val CLICK_ID_PARAMS: Set<String> = setOf(
    "gclid", "msclkid", "fbclid", "ttclid", "twclid",
    "li_fat_id", "rdt_cid", "scid", "dclid", "epik",
    "irclickid", "aff_id"
)

/**
 * Aether-owned opaque tokens. They are consumed into dedicated evidence fields
 * (referralToken / canonicalCampaignId) and MUST be removed from any URL string
 * that is transmitted anywhere.
 */
internal val AETHER_TOKEN_PARAMS: Set<String> = setOf("aether_ref", "aether_cid")

/** Click-id evidence key aliases for cross-platform parity with the shared contract. */
private val CLICK_ID_EVIDENCE_KEYS: Map<String, String> = mapOf(
    "li_fat_id" to "liEFatId",
    "rdt_cid" to "rdtCid",
)

private fun decodeUrlComponent(value: String): String =
    try { URLDecoder.decode(value, "UTF-8") } catch (_: Exception) { value }

/** Parse a raw (still-encoded) query string into decoded key/value pairs, order-preserving. */
internal fun parseQueryParams(rawQuery: String?): List<Pair<String, String>> {
    if (rawQuery.isNullOrEmpty()) return emptyList()
    return rawQuery.split("&").mapNotNull { pair ->
        if (pair.isEmpty()) return@mapNotNull null
        val parts = pair.split("=", limit = 2)
        val key = decodeUrlComponent(parts[0])
        if (key.isEmpty()) null else key to decodeUrlComponent(parts.getOrNull(1) ?: "")
    }
}

/**
 * Sanitize a landing / deep-link URL for transmission: strips the fragment,
 * all click-id params, and all Aether opaque tokens (aether_ref / aether_cid).
 * UTM params are retained — they are declarative campaign evidence, not secrets.
 * Operates textually so even URLs java.net.URI cannot parse are still sanitized.
 */
internal fun sanitizeAttributionUrl(url: String): String {
    val withoutFragment = url.substringBefore('#')
    val queryStart = withoutFragment.indexOf('?')
    if (queryStart < 0) return withoutFragment
    val base = withoutFragment.substring(0, queryStart)
    val rawQuery = withoutFragment.substring(queryStart + 1)
    val kept = rawQuery.split("&").filter { pair ->
        if (pair.isEmpty()) return@filter false
        val key = decodeUrlComponent(pair.substringBefore('=')).lowercase()
        key !in CLICK_ID_PARAMS && key !in AETHER_TOKEN_PARAMS
    }
    return if (kept.isEmpty()) base else base + "?" + kept.joinToString("&")
}

/** One-way SHA-256 of the destination path, hex, truncated to 24 chars. Null for empty paths. */
internal fun hashDestinationPath(path: String?): String? {
    if (path.isNullOrEmpty()) return null
    val digest = MessageDigest.getInstance("SHA-256").digest(path.toByteArray(Charsets.UTF_8))
    return digest.joinToString("") { "%02x".format(it) }.take(24)
}

/**
 * Build a canonical acquisitionEvidence JSONObject (shared schema v3) from
 * decoded query params plus the DESTINATION host/path. The destination host is
 * where the user LANDED — it is never a referrer and is never written to any
 * referrer field here.
 */
internal fun buildAcquisitionEvidence(
    params: List<Pair<String, String>>,
    destinationHost: String?,
    destinationPath: String?,
    entryMethod: String,
    observedAtIso: String,
): JSONObject {
    val evidence = JSONObject()
    val clickIds = JSONObject()
    for ((rawKey, value) in params) {
        if (value.isEmpty()) continue
        when (val key = rawKey.lowercase()) {
            "utm_source" -> evidence.put("utmSource", value)
            "utm_medium" -> evidence.put("utmMedium", value)
            "utm_campaign" -> evidence.put("utmCampaign", value)
            "utm_content" -> evidence.put("utmContent", value)
            "utm_term" -> evidence.put("utmTerm", value)
            "utm_id" -> evidence.put("utmId", value)
            // Opaque tokens: captured as fields, verified server-side, and
            // stripped from every transmitted URL string.
            "aether_ref" -> evidence.put("referralToken", value)
            "aether_cid" -> evidence.put("canonicalCampaignId", value)
            in CLICK_ID_PARAMS -> clickIds.put(CLICK_ID_EVIDENCE_KEYS[key] ?: key, value)
        }
    }
    if (clickIds.length() > 0) evidence.put("clickIds", clickIds)
    if (!destinationHost.isNullOrEmpty()) evidence.put("destinationDomain", destinationHost)
    hashDestinationPath(destinationPath)?.let { evidence.put("destinationPathHash", it) }
    evidence.put("entryMethod", entryMethod)
    evidence.put("schemaVersion", ACQUISITION_EVIDENCE_SCHEMA_VERSION)
    evidence.put("evidenceObservedAt", observedAtIso)
    return evidence
}

/**
 * The canonical evidence parser: parse a deep-link / app-link URI into an
 * acquisitionEvidence JSONObject. Returns null when the URL cannot be parsed.
 */
internal fun parseAcquisitionEvidenceFromUrl(
    url: String,
    entryMethod: String,
    observedAtIso: String,
): JSONObject? = try {
    val uri = URI(url)
    buildAcquisitionEvidence(
        params = parseQueryParams(uri.rawQuery),
        destinationHost = uri.host,
        destinationPath = uri.path,
        entryMethod = entryMethod,
        observedAtIso = observedAtIso,
    )
} catch (_: Exception) {
    null
}

/**
 * Parse a Google Play Install Referrer string (a query-string style payload,
 * e.g. "utm_source=google-play&utm_medium=organic") through the same canonical
 * evidence builder. There is no destination host/path in an install referrer.
 */
internal fun parseInstallReferrerEvidence(referrer: String, observedAtIso: String): JSONObject {
    val raw = referrer.trim().removePrefix("?")
    val params = if (raw.contains('=')) parseQueryParams(raw) else emptyList()
    return buildAcquisitionEvidence(
        params = params,
        destinationHost = null,
        destinationPath = null,
        entryMethod = "android_install_referrer",
        observedAtIso = observedAtIso,
    )
}
