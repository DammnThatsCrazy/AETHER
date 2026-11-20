package com.aether.sdk

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutomationSignalsTest {

    private fun emulator(
        fingerprint: String = "google/oriole/oriole:14/UQ1A/1:user/release-keys",
        model: String = "Pixel 6",
        manufacturer: String = "Google",
        hardware: String = "oriole",
        product: String = "oriole",
        brand: String = "google",
        device: String = "oriole",
    ) = AutomationSignals.isEmulator(fingerprint, model, manufacturer, hardware, product, brand, device)

    @Test
    fun realDeviceIsNotAnEmulator() {
        assertFalse(emulator())
    }

    @Test
    fun standardEmulatorsAreDetected() {
        assertTrue(emulator(hardware = "ranchu"))
        assertTrue(emulator(hardware = "goldfish"))
        assertTrue(emulator(fingerprint = "generic/sdk_gphone64_x86_64/emu64x:14/..."))
        assertTrue(emulator(product = "sdk_gphone64_arm64"))
        assertTrue(emulator(model = "Android SDK built for x86"))
        assertTrue(emulator(manufacturer = "Genymotion"))
    }

    @Test
    fun instrumentationDetectionLooksForLoadedClasses() {
        assertTrue(AutomationSignals.instrumentationLoaded(listOf("java.lang.String")))
        assertFalse(AutomationSignals.instrumentationLoaded(listOf("com.example.DoesNotExist")))
    }
}
