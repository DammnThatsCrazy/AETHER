package com.aether.sdk

import org.junit.Assert.*
import org.junit.Test

/**
 * Truth Kernel §2.8 (batch health) + §2.6 (observe parity) + remote-manifest
 * wiring for the Android SDK. Manifest signature verification (§2.9) is covered
 * by ManifestSignatureTest against the shared vectors.
 */
class AetherManifestTest {

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
