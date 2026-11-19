package com.aether.sdk

import android.app.ActivityManager
import android.os.Build
import org.json.JSONObject

/**
 * Automation evidence for actor classification (context.device.automation).
 *
 * Presence-only booleans. Nothing about the user, their input or their
 * assistive technology is read: accessibility services are deliberately NOT
 * inspected, so screen-reader and switch-access users are never flagged.
 *
 * - testHarness: the app is being driven by a test/automation harness (Android
 *   user test harness, the monkey, or an instrumentation test framework loaded
 *   in this process). Aether treats it as automation (`machine`), never "agent"
 *   and never proof of a human when false.
 * - emulator: the device looks like an emulator. Recorded as evidence only;
 *   developers use emulators, so it never changes the actor on its own.
 *
 * See docs/architecture/AGENT-DETECTION-RELIABILITY.md.
 */
internal object AutomationSignals {

    private val INSTRUMENTATION_CLASSES = listOf(
        "androidx.test.platform.app.InstrumentationRegistry",
        "androidx.test.espresso.Espresso",
        "androidx.test.uiautomator.UiDevice",
        "io.appium.uiautomator2.server.ServerInstrumentation",
    )

    fun collect(): JSONObject = JSONObject().apply {
        put("testHarness", isTestHarness())
        put("emulator", isEmulator(
            fingerprint = Build.FINGERPRINT,
            model = Build.MODEL,
            manufacturer = Build.MANUFACTURER,
            hardware = Build.HARDWARE,
            product = Build.PRODUCT,
            brand = Build.BRAND,
            device = Build.DEVICE,
        ))
    }

    fun isTestHarness(): Boolean {
        val harness = try {
            ActivityManager.isUserAMonkey() ||
                (Build.VERSION.SDK_INT >= 29 && ActivityManager.isRunningInUserTestHarness())
        } catch (_: Throwable) {
            false
        }
        return harness || instrumentationLoaded(INSTRUMENTATION_CLASSES)
    }

    internal fun instrumentationLoaded(classNames: List<String>): Boolean =
        classNames.any { name ->
            try {
                Class.forName(name, false, AutomationSignals::class.java.classLoader)
                true
            } catch (_: Throwable) {
                false
            }
        }

    internal fun isEmulator(
        fingerprint: String?,
        model: String?,
        manufacturer: String?,
        hardware: String?,
        product: String?,
        brand: String?,
        device: String?,
    ): Boolean {
        val fp = fingerprint.orEmpty().lowercase()
        val mdl = model.orEmpty().lowercase()
        val hw = hardware.orEmpty().lowercase()
        val prod = product.orEmpty().lowercase()
        return fp.startsWith("generic") ||
            fp.contains("emulator") ||
            mdl.contains("google_sdk") || mdl.contains("emulator") || mdl.contains("android sdk built for") ||
            manufacturer.orEmpty().contains("Genymotion") ||
            hw == "goldfish" || hw == "ranchu" ||
            prod.startsWith("sdk") || prod.contains("emulator") || prod.contains("simulator") ||
            (brand.orEmpty().startsWith("generic") && device.orEmpty().startsWith("generic"))
    }
}
