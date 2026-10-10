// =============================================================================
// Aether SDK — Jetpack Compose interaction modifier (optional integration)
//
// `Modifier.aetherTrack(id)` observes tap interactions on a composable WITHOUT
// consuming the gesture, so the tenant's own `clickable { … }` / `onClick`
// still fires. It carries only the stable, developer-assigned control id — no
// rendered text. Compose is a compileOnly dependency: this file only links
// when the host app already depends on Jetpack Compose.
// =============================================================================

package com.aether.sdk

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput

/**
 * Observe tap interactions on this composable and emit a canonical
 * `ui_interaction_observed` event carrying the stable [id]. The gesture is
 * observed (`requireUnconsumed = false`) but never consumed, so the tenant's
 * own click handling is unaffected.
 *
 * @param id stable, developer-assigned control identity (never rendered text)
 * @param controlType semantic control kind (defaults to "composable")
 * @param action interaction action label (defaults to "tap")
 * @param metadata optional sanitized extra properties (text/coordinate keys
 *   are stripped unless explicitly enabled in [AetherInteraction.Config])
 */
fun Modifier.aetherTrack(
    id: String,
    controlType: String = "composable",
    action: String = "tap",
    metadata: Map<String, Any?> = emptyMap(),
): Modifier = this.then(
    Modifier.pointerInput(id) {
        awaitEachGesture {
            // Observe the gesture without consuming it.
            awaitFirstDown(requireUnconsumed = false)
            val up = waitForUpOrCancellation()
            if (up != null) {
                AetherInteraction.observeInteraction(id, controlType, action, metadata)
            }
        }
    },
)
