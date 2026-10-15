package com.aether.sdk

import org.junit.Assert.*
import org.junit.Test

/**
 * Unit tests for Aether SDK internal utility functions.
 * Tests the sensitive field scrubber and EVM address normalisation
 * without requiring an Android runtime (pure JVM).
 */
class AetherUtilsTest {

    // -------------------------------------------------------------------------
    // Sensitive field scrubber
    // -------------------------------------------------------------------------

    @Test
    fun scrubSensitiveFields_redactsAllCanonicalKeys() {
        val sensitiveFields = listOf(
            "privatekey", "private_key",
            "seedphrase", "seed_phrase",
            "mnemonic",
            "secret", "secretkey", "secret_key",
            "password", "pin",
            "cardnumber", "card_number",
            "pan", "cvv", "cvc", "cvv2",
            "paymenttoken", "payment_token",
            "authcode", "auth_code",
        )
        for (field in sensitiveFields) {
            val input = mapOf(field to "super-secret-value", "safe" to "kept")
            val scrubbed = scrubSensitiveFields(input)
            assertEquals("Expected $field to be redacted", "[REDACTED]", scrubbed[field])
            assertEquals("Non-sensitive field must be preserved for $field", "kept", scrubbed["safe"])
        }
    }

    @Test
    fun scrubSensitiveFields_isCaseInsensitive() {
        val input = mapOf(
            "Password"   to "abc",
            "PASSWORD"   to "xyz",
            "CVV"        to "999",
            "CardNumber" to "4111111111111111",
        )
        val scrubbed = scrubSensitiveFields(input)
        assertEquals("[REDACTED]", scrubbed["Password"])
        assertEquals("[REDACTED]", scrubbed["PASSWORD"])
        assertEquals("[REDACTED]", scrubbed["CVV"])
        assertEquals("[REDACTED]", scrubbed["CardNumber"])
    }

    @Test
    fun scrubSensitiveFields_preservesNonSensitiveFields() {
        val input = mapOf(
            "userId"   to "u_123",
            "amount"   to 99.99,
            "currency" to "USD",
            "label"    to "checkout",
        )
        val scrubbed = scrubSensitiveFields(input)
        assertEquals("u_123", scrubbed["userId"])
        assertEquals(99.99, scrubbed["amount"])
        assertEquals("USD", scrubbed["currency"])
        assertEquals("checkout", scrubbed["label"])
    }

    @Test
    fun scrubSensitiveFields_doesNotMutateInput() {
        val input = mapOf("password" to "original")
        scrubSensitiveFields(input)
        assertEquals("original", input["password"])
    }

    @Test
    fun sensitiveKeys_containsExactly20Entries() {
        assertEquals(20, SENSITIVE_KEYS.size)
    }

    @Test
    fun sensitiveKeys_containsAllExpectedKeys() {
        val expected = setOf(
            "privatekey", "private_key", "seedphrase", "seed_phrase", "mnemonic",
            "secret", "secretkey", "secret_key", "password", "pin",
            "cardnumber", "card_number", "pan", "cvv", "cvc", "cvv2",
            "paymenttoken", "payment_token", "authcode", "auth_code",
        )
        assertEquals(expected, SENSITIVE_KEYS)
    }

    // -------------------------------------------------------------------------
    // EVM address normalisation
    // -------------------------------------------------------------------------

    @Test
    fun normalizeWalletAddress_lowercasesEVMAddresses() {
        assertEquals("0xabcdef123456", normalizeWalletAddress("0xABCDEF123456"))
        assertEquals("0xabcdef",       normalizeWalletAddress("0XAbCdEf"))
    }

    @Test
    fun normalizeWalletAddress_trimsWhitespaceForNonEVMChains() {
        assertEquals("SOLANA_ADDR", normalizeWalletAddress("  SOLANA_ADDR  ", vm = "svm"))
        assertEquals("BTC_ADDR",    normalizeWalletAddress("  BTC_ADDR  ",    vm = "bitcoin"))
    }

    @Test
    fun normalizeWalletAddress_defaultsToEVM() {
        assertEquals("0xabcd", normalizeWalletAddress("0xABCD"))
    }
}
