// =============================================================================
// Aether SDK — Optional native UI interaction instrumentation (spec §12)
//
// Privacy-safe by construction:
//   - Disabled by default (config.enabled == false). Nothing is observed until
//     the host app opts in.
//   - Metadata-only. The rendered control text / label / value is NEVER
//     captured unless captureControlText is explicitly enabled.
//   - No coordinates unless captureCoordinates is explicitly enabled.
//   - Requires a STABLE control identifier (explicit Aether id, a stable
//     resource-entry name, or an accessibility-style tag) — never rendered
//     text — when requireStableIdentifiers is true (the default).
//   - Screen allow/deny lists gate emission per screen.
//   - No Accessibility Services, no view-tree scraping, no keyboard/text-field
//     content capture. The SDK observes explicit, developer-instrumented
//     controls only.
//
// Emission always flows through the canonical, consent-gated
// Aether.observe("ui_interaction_observed", …) path, so session id and
// consent-state travel on the standard event envelope.
// =============================================================================

package com.aether.sdk

import android.view.View
import java.util.UUID
import java.util.WeakHashMap

/**
 * Optional, explicit UI-interaction observer. Not an acquisition signal —
 * interaction events are kept entirely separate from AcquisitionEvidence and
 * are never used as acquisition proof.
 */
object AetherInteraction {

    /**
     * Instrumentation configuration. All privacy-affecting switches default to
     * the safest possible value.
     */
    data class Config(
        /** Master switch. When false, every observation is a no-op. */
        val enabled: Boolean = false,
        /** Capture the rendered control text/label. OFF by default. */
        val captureControlText: Boolean = false,
        /** Capture touch coordinates. OFF by default. */
        val captureCoordinates: Boolean = false,
        /** Drop interactions that lack a stable identifier. ON by default. */
        val requireStableIdentifiers: Boolean = true,
        /** When non-empty, only these screens may emit. */
        val allowlistedScreens: Set<String> = emptySet(),
        /** These screens never emit (takes precedence over the allowlist). */
        val denylistedScreens: Set<String> = emptySet(),
    )

    /** Reserved metadata keys scrubbed unless captureControlText is enabled. */
    private val CONTROL_TEXT_KEYS = setOf("text", "label", "title", "value", "content", "hint", "placeholder")

    /** Reserved metadata keys scrubbed unless captureCoordinates is enabled. */
    private val COORDINATE_KEYS = setOf("x", "y", "coordinates", "position", "touchX", "touchY")

    @Volatile
    private var config: Config = Config()

    @Volatile
    private var currentScreen: String? = null

    @Volatile
    private var currentNavigationId: String? = null

    /** Explicit, developer-assigned stable ids keyed weakly by View. */
    private val explicitIds = WeakHashMap<View, String>()

    /** Apply an instrumentation configuration. */
    @JvmStatic
    fun configure(config: Config) {
        this.config = config
    }

    /** Current configuration (immutable snapshot). */
    @JvmStatic
    fun currentConfig(): Config = config

    /**
     * Assign a stable Aether identifier to a View. Preferred over resource ids
     * for controls that lack a meaningful android:id. The id must be a stable,
     * developer-chosen token — never derived from rendered text.
     */
    @JvmStatic
    fun setAetherId(view: View, id: String) {
        explicitIds[view] = id
    }

    /**
     * Record the current screen (and optionally a navigation id) for
     * subsequent interaction events. Called by the navigation observer, or
     * directly by the host app.
     */
    @JvmStatic
    fun setCurrentScreen(screen: String, navigationId: String? = null) {
        currentScreen = screen
        currentNavigationId = navigationId ?: UUID.randomUUID().toString()
    }

    /** Clear the tracked screen/navigation context. */
    @JvmStatic
    fun clearScreen() {
        currentScreen = null
        currentNavigationId = null
    }

    /**
     * Explicit tracked-view helper. Emits one canonical
     * `ui_interaction_observed` for [view]. Does not attach any listener and
     * does not alter the view's behavior.
     */
    @JvmStatic
    @JvmOverloads
    fun trackInteraction(
        view: View,
        action: String = "tap",
        controlId: String? = null,
        controlType: String? = null,
        metadata: Map<String, Any?> = emptyMap(),
    ) {
        val id = controlId ?: stableIdFor(view)
        val type = controlType ?: view.javaClass.simpleName
        emit(id, type, action, metadata)
    }

    /**
     * Controlled click-listener instrumentation that does NOT replace the
     * tenant's click handler: the returned listener emits one interaction
     * observation and then invokes [delegate] (the tenant's own handler).
     * Assign it with `view.setOnClickListener(Aether.trackedClickListener(...))`.
     */
    @JvmStatic
    @JvmOverloads
    fun trackedClickListener(
        controlId: String,
        controlType: String = "button",
        delegate: View.OnClickListener? = null,
        metadata: Map<String, Any?> = emptyMap(),
    ): View.OnClickListener = View.OnClickListener { v ->
        emit(controlId, controlType, "tap", metadata)
        delegate?.onClick(v)
    }

    /**
     * Attach controlled click instrumentation to [view] while preserving the
     * tenant handler passed as [delegate]. The tenant handler is always
     * invoked; the observation is additive.
     */
    @JvmStatic
    @JvmOverloads
    fun instrumentClick(
        view: View,
        controlId: String? = null,
        controlType: String = "button",
        delegate: View.OnClickListener? = null,
        metadata: Map<String, Any?> = emptyMap(),
    ) {
        val id = controlId ?: stableIdFor(view)
        view.setOnClickListener(
            trackedClickListener(id ?: return, controlType, delegate, metadata),
        )
    }

    /**
     * Low-level id/type emission for integrations that do not hold a View
     * (Compose modifier, navigation observer).
     */
    @JvmStatic
    @JvmOverloads
    internal fun observeInteraction(
        controlId: String?,
        controlType: String,
        action: String,
        metadata: Map<String, Any?> = emptyMap(),
    ) {
        emit(controlId, controlType, action, metadata)
    }

    // --- internals -----------------------------------------------------------

    private fun emit(
        controlId: String?,
        controlType: String,
        action: String,
        metadata: Map<String, Any?>,
    ) {
        val cfg = config
        if (!cfg.enabled) return

        val screen = currentScreen
        if (!screenAllowed(cfg, screen)) return

        if (controlId.isNullOrEmpty()) {
            if (cfg.requireStableIdentifiers) {
                Aether.debugLog("ui_interaction_observed dropped — no stable control id")
                return
            }
        }

        val props = linkedMapOf<String, Any?>()
        props["controlId"] = controlId ?: "unidentified"
        props["controlType"] = controlType
        props["action"] = action
        screen?.let { props["screen"] = it }
        currentNavigationId?.let { props["navigationId"] = it }
        for ((k, v) in sanitizeMetadata(cfg, metadata)) props[k] = v

        Aether.observe("ui_interaction_observed", props)
    }

    private fun screenAllowed(cfg: Config, screen: String?): Boolean {
        val s = screen ?: return cfg.allowlistedScreens.isEmpty()
        if (cfg.denylistedScreens.contains(s)) return false
        if (cfg.allowlistedScreens.isNotEmpty() && !cfg.allowlistedScreens.contains(s)) return false
        return true
    }

    /**
     * Strip control-text and coordinate keys unless explicitly enabled. This
     * is defense in depth: even if a caller passes text through `metadata`, it
     * is dropped by default.
     */
    private fun sanitizeMetadata(cfg: Config, metadata: Map<String, Any?>): Map<String, Any?> {
        if (metadata.isEmpty()) return metadata
        val out = LinkedHashMap<String, Any?>(metadata.size)
        for ((key, value) in metadata) {
            val lower = key.lowercase()
            if (!cfg.captureControlText && CONTROL_TEXT_KEYS.contains(lower)) continue
            if (!cfg.captureCoordinates && COORDINATE_KEYS.contains(lower)) continue
            out[key] = value
        }
        return out
    }

    /**
     * Resolve a stable identifier for [view], preferring an explicit Aether id,
     * then a stable resource-entry name, then a String tag. Never rendered
     * text. Returns null when no stable id exists.
     */
    private fun stableIdFor(view: View): String? {
        explicitIds[view]?.let { return it }
        if (view.id != View.NO_ID) {
            try {
                return view.resources.getResourceEntryName(view.id)
            } catch (_: Exception) {
                // Dynamically generated ids have no entry name — not stable.
            }
        }
        (view.tag as? String)?.takeIf { it.isNotEmpty() }?.let { return it }
        return null
    }
}
