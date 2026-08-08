package com.aether.sdk

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Truth Kernel §2.9 (manifest signature verification) + §2.8 (batch health)
 * + §2.6 (observe parity) for the Android SDK.
 */
class AetherManifestTest {

    private fun manifest(signature: String) = SDKManifest(
        manifest_version = "2026.07.12-1",
        min_sdk_version = "8.0.0",
        schema_version = "8.12.0",
        rollout_percentage = 100,
        features = mapOf("heatmaps" to true, "funnels" to false),
        published_at = "2026-07-12T00:00:00Z",
        signature = signature,
    )

    private fun sign(m: SDKManifest, key: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        return mac.doFinal(canonicalManifestString(m).toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }

    private fun agent() = AetherHealthAgent(endpoint = "https://api.test", apiKey = "k")

    @Test
    fun `valid HMAC signature is accepted`() {
        val key = "sdk-config-secret"
        val unsigned = manifest("")
        val signed = manifest(sign(unsigned, key))
        assertTrue(agent().verifyManifestSignature(signed, key))
    }

    @Test
    fun `signature from a different key is rejected`() {
        val unsigned = manifest("")
        val wrong = manifest(sign(unsigned, "attacker-key"))
        assertFalse(agent().verifyManifestSignature(wrong, "sdk-config-secret"))
    }

    @Test
    fun `unsigned manifest is rejected`() {
        assertFalse(agent().verifyManifestSignature(manifest(""), "sdk-config-secret"))
    }

    @Test
    fun `empty verification key fails closed`() {
        val signed = manifest(sign(manifest(""), "k"))
        assertFalse(agent().verifyManifestSignature(signed, ""))
    }

    @Test
    fun `canonical manifest string is feature-order independent`() {
        val a = manifest("x").copy(features = mapOf("a" to true, "b" to false))
        val b = manifest("y").copy(features = mapOf("b" to false, "a" to true))
        assertEquals(canonicalManifestString(a), canonicalManifestString(b))
    }

    @Test
    fun `BatchHealth holds the five counters`() {
        val h = BatchHealth(accepted = 3, duplicate = 1, rejected = 0, droppedByConsent = 2, queueDepth = 5)
        assertEquals(3, h.accepted)
        assertEquals(1, h.duplicate)
        assertEquals(0, h.rejected)
        assertEquals(2, h.droppedByConsent)
        assertEquals(5, h.queueDepth)
    }

    @Test
    fun `observe with a non-canonical type is a no-op`() {
        // Not initialized + unknown type must never enqueue.
        Aether.observe("definitely_not_a_real_event_type", mapOf("x" to 1))
        assertEquals(0, Aether.queueDepth())
    }

    // -------------------------------------------------------------------
    // Remote Manifest Wiring (rollout sampling + feature flags)
    //
    // Aether is never initialize()d in this test module, so enqueueEvent()'s
    // isInitialized guard would make an end-to-end track()-then-queueDepth()
    // assertion vacuous regardless of the sampling gate. Aether.shouldSample
    // is the pure decision function the gate calls, so it is exercised
    // directly with injected rolls for a deterministic test.
    // isFeatureEnabled() has no such guard and is exercised through the
    // public singleton.
    // -------------------------------------------------------------------

    @Test
    fun `rollout_percentage of 0 samples events out`() {
        // rollout_percentage=0 -> samplingRate=0.0. Every roll in [0,1) must
        // be sampled OUT, including the roll=0.0 boundary.
        assertFalse(Aether.shouldSample(rate = 0.0, roll = 0.0))
        assertFalse(Aether.shouldSample(rate = 0.0, roll = 0.5))
        assertFalse(Aether.shouldSample(rate = 0.0, roll = 0.999))
    }

    @Test
    fun `rollout_percentage of 100 keeps every event`() {
        // rollout_percentage=100 -> samplingRate=1.0. Every roll in [0,1)
        // must be kept.
        assertTrue(Aether.shouldSample(rate = 1.0, roll = 0.0))
        assertTrue(Aether.shouldSample(rate = 1.0, roll = 0.999))
    }

    @Test
    fun `partial rollout sampling is roll-dependent`() {
        // rollout_percentage=50 -> samplingRate=0.5: keep when roll < rate.
        assertTrue(Aether.shouldSample(rate = 0.5, roll = 0.0))
        assertTrue(Aether.shouldSample(rate = 0.5, roll = 0.499))
        assertFalse(Aether.shouldSample(rate = 0.5, roll = 0.5))
        assertFalse(Aether.shouldSample(rate = 0.5, roll = 0.999))
    }

    @Test
    fun `manifest feature flag is honored by isFeatureEnabled`() {
        val previous = Aether.manifestFeatureOverrides
        try {
            Aether.manifestFeatureOverrides = mapOf("remote_beta_ui" to true)
            assertTrue(Aether.isFeatureEnabled("remote_beta_ui"))

            Aether.manifestFeatureOverrides = mapOf("remote_beta_ui" to false)
            assertFalse(Aether.isFeatureEnabled("remote_beta_ui", default = true))
        } finally {
            Aether.manifestFeatureOverrides = previous
        }
    }

    @Test
    fun `isFeatureEnabled falls back to default when no manifest override`() {
        val previous = Aether.manifestFeatureOverrides
        try {
            Aether.manifestFeatureOverrides = emptyMap()
            assertFalse(Aether.isFeatureEnabled("flag_absent_everywhere"))
            assertTrue(Aether.isFeatureEnabled("flag_absent_everywhere", default = true))
        } finally {
            Aether.manifestFeatureOverrides = previous
        }
    }
}
