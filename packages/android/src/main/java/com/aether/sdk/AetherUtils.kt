package com.aether.sdk

internal val SENSITIVE_KEYS: Set<String> = setOf(
    "privatekey", "private_key", "seedphrase", "seed_phrase", "mnemonic",
    "secret", "secretkey", "secret_key", "password", "pin",
    "cardnumber", "card_number", "pan", "cvv", "cvc", "cvv2",
    "paymenttoken", "payment_token", "authcode", "auth_code"
)

internal fun scrubSensitiveFields(props: Map<String, Any?>): Map<String, Any?> =
    props.mapValues { (key, value) ->
        if (key.lowercase() in SENSITIVE_KEYS) "[REDACTED]" else value
    }

internal fun normalizeWalletAddress(address: String, vm: String = "evm"): String =
    when (vm.lowercase()) {
        "evm" -> address.lowercase()
        else  -> address.trim()
    }
