// =============================================================================
// Aether SDK — AndroidX Navigation destination observer (optional integration)
//
// Bridges AndroidX Navigation destination changes into the interaction module's
// screen context, so subsequent `ui_interaction_observed` events carry the
// current screen and a per-destination navigation id. Navigation is a
// compileOnly dependency: this file only links when the host app already
// depends on androidx.navigation.
// =============================================================================

package com.aether.sdk

import androidx.navigation.NavController
import androidx.navigation.NavDestination

/**
 * A [NavController.OnDestinationChangedListener] that records the current
 * screen (destination route, falling back to the label or id) and mints a new
 * navigation id per destination. Register it with
 * `navController.addOnDestinationChangedListener(Aether.navigationObserver())`.
 */
object AetherInteractionNavigation {

    @JvmStatic
    fun listener(): NavController.OnDestinationChangedListener =
        NavController.OnDestinationChangedListener { _, destination, _ ->
            AetherInteraction.setCurrentScreen(screenNameFor(destination))
        }

    private fun screenNameFor(destination: NavDestination): String {
        destination.route?.takeIf { it.isNotEmpty() }?.let { return it }
        destination.label?.toString()?.takeIf { it.isNotEmpty() }?.let { return it }
        return "destination_${destination.id}"
    }
}
