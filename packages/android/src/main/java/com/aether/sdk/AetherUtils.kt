package com.aether.sdk

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
